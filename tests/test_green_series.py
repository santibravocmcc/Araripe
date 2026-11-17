"""D4B: the green series of the live release — documents, database, scripts, lanes."""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.publication import conditional_store as cs
from src.publication import delivery_boundary as dbnd
from src.publication import retention
from src.publication import state_chain as sc
from src.publication.run_inputs import ReadOnlyStore
from src.timeseries import green_rows as gr
from src.timeseries import green_series as gs
from tests.fake_object_store import FakeS3

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
DEPOSIT_LANE = WORKFLOWS / "v2_green_deposit_lane.yml"
SERIES_LANE = WORKFLOWS / "v2_green_timeseries.yml"
REBUILD_LANE = WORKFLOWS / "v2_green_series_rebuild.yml"
PUBLISH_LANE = WORKFLOWS / "v2_operational_publish.yml"
SECRET = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")
R2_ANY = re.compile(r"secrets\.R2_")
BUCKET = cs.STAGING_BUCKET


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)  # dataclasses resolve their module
    spec.loader.exec_module(module)
    return module


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ── documents and members ────────────────────────────────────────────────────


GENERATION = gr.generation_identity(
    algorithm_version="1.1.0", baseline_version="2.1.0",
    monitoring_extent_id="araripe-implementation-rectangle-v1",
    source_collection_id="COPERNICUS/S2_SR_HARMONIZED",
    composition_method_id="datatake_mosaic-v1")


def _stats(mean):
    return {name: {"valid_pixels": 900, "total_pixels": 1000, "mean": mean,
                   "median": mean, "std": 0.05, "min": -0.5, "max": 0.9}
            for name in gr.SERIES_INDICES}


def _document(n: int, dates, *, qa="accepted", generation=GENERATION):
    acquisitions = [{
        "acquisition_id": f"acq-v3-{n:02d}{i:062d}", "observed_on": day,
        "datatake_id": f"GS2B_{day}", "scene_ids": [f"S/{day}"],
        "source_metadata_sha256": f"{n:02d}{i:062d}", "ledger_status": "complete_zero_alerts",
        "qa_status": qa, "qa_reason": None if qa == "accepted" else "scene-anomaly",
        "composite_sha256": f"{i:064d}", "valid_pixels": 900, "total_pixels": 1000,
        "indices": _stats(0.1 * (i + 1)),
    } for i, day in enumerate(dates)]
    return {"schema": gr.ROWS_SCHEMA, "ledger_id": f"pl-v3-{n:064d}",
            "run_manifest_id": f"run-v3-{n:064d}", "region": gr.REGION,
            "generation": dict(generation), "acquisitions": acquisitions,
            "superseded": [], "absent": []}


def _member(document, first, last):
    n = document["ledger_id"][-2:]
    return {"release_id": f"rel-g1-{n:0>64}", "ledger_id": document["ledger_id"],
            "run_manifest_id": document["run_manifest_id"],
            "first_observed_on": first, "last_observed_on": last}


def _chain():
    a = _document(1, ["2026-01-02", "2026-01-04"])
    b = _document(2, ["2026-01-22"], qa="rejected_quality")
    c = _document(3, ["2026-02-06", "2026-02-09"])
    manifest = {"release_id": "rel-g3-" + "9" * 64, "members": [
        _member(c, "2026-02-01", "2026-02-12"),   # listed out of order on purpose
        _member(a, "2026-01-01", "2026-01-15"),
        _member(b, "2026-01-16", "2026-01-31"),
    ]}
    return manifest, [a, b, c]


def test_documents_are_chosen_per_member_in_chain_order():
    manifest, docs = _chain()
    chosen = gs.select_documents(manifest, list(reversed(docs)))
    assert [d["ledger_id"] for d in chosen] == [d["ledger_id"] for d in docs]


def test_a_member_without_rows_is_a_hole_and_is_refused():
    """The state every run deposited before D4B is in: no series is published."""

    manifest, docs = _chain()
    with pytest.raises(gs.SeriesIncomplete) as caught:
        gs.select_documents(manifest, [docs[0], docs[2]])
    assert [m["ledger_id"] for m in caught.value.missing] == [docs[1]["ledger_id"]]
    assert "v2_green_series_rebuild.yml" in str(caught.value)


def test_a_document_of_no_member_is_ignored():
    """series/ also holds runs the live release does not (yet) include."""

    manifest, docs = _chain()
    stray = _document(7, ["2026-03-01"])
    assert len(gs.select_documents(manifest, docs + [stray])) == 3


def test_two_different_documents_for_one_member_are_refused():
    manifest, docs = _chain()
    other = copy.deepcopy(docs[0])
    other["acquisitions"][0]["indices"]["ndmi"]["mean"] = 0.999
    with pytest.raises(gs.SeriesRejected, match="two different"):
        gs.select_documents(manifest, docs + [other])
    assert len(gs.select_documents(manifest, docs + [copy.deepcopy(docs[0])])) == 3


def test_one_series_is_one_generation():
    manifest, docs = _chain()
    docs[2]["generation"] = gr.generation_identity(
        algorithm_version="1.2.0", baseline_version="2.1.0",
        monitoring_extent_id="araripe-implementation-rectangle-v1",
        source_collection_id="COPERNICUS/S2_SR_HARMONIZED",
        composition_method_id="datatake_mosaic-v1")
    with pytest.raises(gs.SeriesRejected, match="one generation"):
        gs.select_documents(manifest, docs)


def test_a_release_without_members_is_not_a_series_source():
    with pytest.raises(gs.SeriesRejected, match="chain release"):
        gs.select_documents({"release_id": "rel-g1-" + "1" * 64}, [])


def test_the_rows_document_must_name_the_runs_own_ledger():
    _, docs = _chain()
    gs.check_rows_document(docs[0], ledger={"ledger_id": docs[0]["ledger_id"],
                                            "run_manifest_id": docs[0]["run_manifest_id"]})
    with pytest.raises(gs.SeriesRejected, match="ledger_id"):
        gs.check_rows_document(docs[0], ledger={"ledger_id": docs[1]["ledger_id"],
                                                "run_manifest_id": docs[0]["run_manifest_id"]})


def test_the_key_is_beside_the_run_never_under_it():
    assert gs.series_key("ci-42") == "series/ci-42/timeseries_rows.json"
    assert not gs.series_key("ci-42").startswith(dbnd.RUNS_ROOT)
    assert gs.run_id_of("series/ci-42/timeseries_rows.json") == "ci-42"
    assert gs.run_id_of("runs/ci-42/timeseries_rows.json") is None
    for bad in ("", "a/b", "..", "."):
        with pytest.raises(gs.SeriesRejected):
            gs.series_key(bad)


# ── the database ─────────────────────────────────────────────────────────────


def test_the_same_documents_build_the_same_bytes(tmp_path):
    """Built from empty, so an unchanged series opens no pull request."""

    manifest, docs = _chain()
    chosen = gs.select_documents(manifest, docs)
    gs.build_database(tmp_path / "a.db", chosen)
    gs.build_database(tmp_path / "b.db", chosen)
    assert gs.sha256_file(tmp_path / "a.db") == gs.sha256_file(tmp_path / "b.db")


def test_the_database_is_never_updated_in_place(tmp_path):
    manifest, docs = _chain()
    (tmp_path / gs.DATABASE_NAME).write_bytes(b"")
    with pytest.raises(gs.SeriesRejected, match="from empty"):
        gs.build_database(tmp_path / gs.DATABASE_NAME, gs.select_documents(manifest, docs))


def test_the_signal_states_the_database_and_the_series(tmp_path):
    manifest, docs = _chain()
    chosen = gs.select_documents(manifest, docs)
    db = tmp_path / gs.DATABASE_NAME
    gs.build_database(db, chosen)
    signal = gs.build_signal(db, release_id=manifest["release_id"], documents=chosen,
                             published_utc="2026-11-17T12:00:00Z", run_url=None)
    assert signal["schema"] == gs.SIGNAL_SCHEMA
    assert signal["database"]["sha256"] == gs.sha256_file(db)
    assert signal["series"] == {
        "generation_id": GENERATION["generation_id"],
        "first_observed_on": "2026-01-02", "last_observed_on": "2026-02-09",
        "last_accepted_observed_on": "2026-02-09", "acquisitions": 5, "accepted": 4}
    assert gs.unchanged(signal, dict(signal, published_utc="later"))
    assert not gs.unchanged(signal, dict(signal, release_id="rel-g3-" + "8" * 64))
    assert not gs.unchanged(None, signal)


def test_the_legacy_names_are_not_reused():
    assert gs.DATABASE_NAME != "timeseries.db" and gs.SIGNAL_NAME != "RELEASE.json"


# ── the deposit script ───────────────────────────────────────────────────────


def _write(tmp_path, document, ledger_id=None):
    rows = tmp_path / "timeseries_rows.json"
    rows.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"ledger_id": ledger_id or document["ledger_id"],
                                  "run_manifest_id": document["run_manifest_id"]}))
    return rows, ledger


def test_the_deposit_writes_once_and_a_rerun_is_unchanged(tmp_path):
    script = _load("deposit_green_series")
    fake = FakeS3()
    store = cs.ConditionalStore(fake, BUCKET)
    rows, ledger = _write(tmp_path, _chain()[1][0])
    key, outcome = script.deposit(store, "ci-42", rows, ledger)
    assert (key, outcome.result) == ("series/ci-42/timeseries_rows.json", "created")
    assert fake.body(key) == rows.read_bytes()
    assert script.deposit(store, "ci-42", rows, ledger)[1].result == "unchanged"
    assert fake.keys() == [key]


def test_the_deposit_never_overwrites_different_rows(tmp_path):
    script = _load("deposit_green_series")
    store = cs.ConditionalStore(FakeS3(), BUCKET)
    script.deposit(store, "ci-42", *_write(tmp_path, _chain()[1][0]))
    changed = copy.deepcopy(_chain()[1][0])
    changed["acquisitions"][0]["indices"]["nbr"]["mean"] = 0.5
    with pytest.raises(cs.ImmutableObjectConflict):
        script.deposit(store, "ci-42", *_write(tmp_path, changed))


def test_the_deposit_refuses_rows_of_another_run(tmp_path):
    script = _load("deposit_green_series")
    fake = FakeS3()
    rows, ledger = _write(tmp_path, _chain()[1][0], ledger_id="pl-v3-" + "f" * 64)
    with pytest.raises(gs.SeriesRejected):
        script.deposit(cs.ConditionalStore(fake, BUCKET), "ci-42", rows, ledger)
    assert fake.keys() == []


# ── the series build, read-only ──────────────────────────────────────────────


def _bucket(manifest, documents, runs=None):
    objects = {f"releases/{manifest['release_id']}/release.json":
               (json.dumps(manifest).encode(), "application/json")}
    for run_id, document in zip(runs or [f"ci-{i}" for i in range(len(documents))], documents):
        objects[gs.series_key(run_id)] = (json.dumps(document).encode(), "application/json")
    return FakeS3(objects)


@pytest.fixture
def builder(monkeypatch):
    script = _load("build_green_series")

    def pointer(store):
        manifests = [k for k in store._client.objects if k.endswith("/release.json")]
        return {"release_id": manifests[0].split("/")[1]}, '"etag"'

    monkeypatch.setattr(script.ap, "read_pointer", pointer)
    return script


def test_the_build_follows_the_live_release(builder, tmp_path):
    manifest, docs = _chain()
    fake = _bucket(manifest, docs + [_document(8, ["2026-04-01"])])
    store = ReadOnlyStore(fake, BUCKET)
    out = builder.command_build(store, tmp_path / "out", None)
    assert out == {"changed": "true", "release_id": manifest["release_id"]}
    signal = json.loads((tmp_path / "out" / gs.SIGNAL_NAME).read_text())
    assert signal["series"]["acquisitions"] == 5
    assert not [w for w in fake.writes]


def test_the_build_says_unchanged_for_the_published_series(builder, tmp_path):
    manifest, docs = _chain()
    store = ReadOnlyStore(_bucket(manifest, docs), BUCKET)
    builder.command_build(store, tmp_path / "first", None)
    out = builder.command_build(store, tmp_path / "second",
                                tmp_path / "first" / gs.SIGNAL_NAME)
    assert out["changed"] == "false"


def test_the_build_refuses_a_hole(builder, tmp_path):
    manifest, docs = _chain()
    store = ReadOnlyStore(_bucket(manifest, docs[:2]), BUCKET)
    with pytest.raises(gs.SeriesIncomplete):
        builder.command_build(store, tmp_path / "out", None)
    assert not (tmp_path / "out" / gs.DATABASE_NAME).exists()


def test_the_build_follows_the_listing_cursor(builder, tmp_path):
    manifest, docs = _chain()
    fake = _bucket(manifest, docs)
    fake.page_size = 1
    assert builder.command_build(ReadOnlyStore(fake, BUCKET), tmp_path / "o", None)["changed"] == "true"
    fake.drop_continuation_token = True
    with pytest.raises(gs.SeriesRejected, match="continuation"):
        builder.list_series_run_ids(ReadOnlyStore(fake, BUCKET))


def test_missing_lists_chain_runs_without_rows_oldest_first(builder, tmp_path, monkeypatch):
    path = ("ci-1", "ci-2", "ci-3", "ci-4")
    monkeypatch.setattr(builder.sc, "resolve_head",
                        lambda store: sc.ChainHead(path, (), ()))
    objects = {f"runs/{r}/ledger.json": (f'{{"run": "{r}"}}'.encode(), "application/json")
               for r in path}
    objects[gs.series_key("ci-2")] = (b"{}", "application/json")
    fake = FakeS3(objects)
    out = builder.command_missing(ReadOnlyStore(fake, BUCKET), tmp_path / "plan", 2)
    assert out == {"count": "2", "remaining": "1"}
    plan = json.loads((tmp_path / "plan" / "plan.json").read_text())
    assert plan["this_dispatch"] == ["ci-1", "ci-3"] and plan["missing"] == ["ci-1", "ci-3", "ci-4"]
    assert json.loads((tmp_path / "plan" / "ci-3" / "ledger.json").read_text()) == {"run": "ci-3"}
    assert not fake.writes


@pytest.mark.parametrize("script", ["build_green_series.py"])
def test_the_series_reader_cannot_express_a_write(script):
    """The series job's identity is the candidate's, through a ReadOnlyStore."""

    tree = ast.parse((ROOT / "scripts" / script).read_text(encoding="utf-8"))
    names = {getattr(c.func, "attr", getattr(c.func, "id", ""))
             for c in ast.walk(tree) if isinstance(c, ast.Call)}
    assert "ReadOnlyStore" in names and "ConditionalStore" not in names
    assert not names & {"put_if_absent", "put_if_match", "put_if_pointer_absent"}
    for call in ast.walk(tree):
        if isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "build_client":
            assert not any(k.arg == "profile_fallback" for k in call.keywords)


# ── the bucket's policies name the new prefix ───────────────────────────────


def test_retention_keeps_the_rows_as_the_only_copy():
    item = retention.StoredKey("series/ci-42/timeseries_rows.json", 10,
                               datetime(2026, 1, 1, tzinfo=timezone.utc))
    disposition = retention.classify(item, pointer=None, runs={},
                                     as_of=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert (disposition.action, disposition.reason) == (
        retention.RETAIN, "series_rows_are_the_only_copy")


def test_the_route_never_serves_the_rows():
    exposure = dbnd.classify_key("series/ci-42/timeseries_rows.json",
                                 live_release_id="rel-g3-" + "9" * 64)
    assert (exposure.exposure, exposure.reason) == (dbnd.PRIVATE, "series_rows")


# ── the lanes ────────────────────────────────────────────────────────────────


def _steps(path, job):
    return _yaml(path)["jobs"][job]["steps"]


def _named(path, job, fragment):
    (step,) = [s for s in _steps(path, job) if fragment in s["name"]]
    return step


def test_the_detect_job_measures_rows_with_no_credential_after_the_detection():
    steps = _steps(DEPOSIT_LANE, "detect")
    names = [s["name"] for s in steps]
    rows = _named(DEPOSIT_LANE, "detect", "Measure the series rows")
    detect = names.index("Detect, from the predecessor's state or an empty one, as the green account")
    hand = names.index("Hand the detection's outputs to the deposit job")
    assert detect < names.index(rows["name"]) < hand
    assert "green_timeseries.py rows" in rows["run"]
    assert not SECRET.findall(str(rows.get("env") or {}))
    assert rows["if"] == "steps.enumerated.outputs.deposit == 'true'"
    assert "${{ runner.temp }}/replay/timeseries_rows.json" in \
        steps[hand]["with"]["path"].splitlines()


def test_the_deposit_job_writes_the_rows_after_the_prefix_validated():
    names = [s["name"] for s in _steps(DEPOSIT_LANE, "deposit")]
    write = _named(DEPOSIT_LANE, "deposit", "series rows beside it")
    assert names.index("Re-read the prefix and validate it, writing nothing") \
        < names.index(write["name"]) == len(names) - 1
    assert set(SECRET.findall(str(write["env"]))) == {
        "R2_STAGING_ACCESS_KEY_ID", "R2_STAGING_SECRET_ACCESS_KEY"}
    assert "deposit_green_series.py" in write["run"] and "runs/" not in write["run"]


def test_the_deposit_lane_keeps_the_jobs_the_promotion_gate_reads():
    """chained_promotion_gate.py promotes only on exactly these three jobs."""

    gate = _load("chained_promotion_gate")
    assert tuple(_yaml(DEPOSIT_LANE)["jobs"]) == gate.JOBS


def test_the_publication_never_gains_contents_write():
    """The green release path has no git in it (v2_operational_publish.yml header)."""

    doc = _yaml(PUBLISH_LANE)
    assert doc["permissions"] == {"contents": "read"}
    for name, job in doc["jobs"].items():
        assert (job.get("permissions") or {}).get("contents", "read") == "read", name


def test_only_the_series_publish_job_may_write_contents():
    for path in sorted(WORKFLOWS.glob("v2_*.yml")):
        doc = _yaml(path)
        top = (doc.get("permissions") or {}).get("contents")
        assert top == "read", path.name
        for name, job in doc["jobs"].items():
            if (job.get("permissions") or {}).get("contents") == "write":
                assert (path.name, name) == ("v2_green_timeseries.yml", "publish")


def test_the_series_publish_job_holds_no_bucket_identity_and_no_environment():
    job = _yaml(SERIES_LANE)["jobs"]["publish"]
    assert "environment" not in job
    assert job["permissions"] == {"contents": "write", "pull-requests": "write"}
    text = yaml.safe_dump(job)
    assert set(SECRET.findall(text)) == {"GITHUB_TOKEN"}


def test_the_series_build_job_holds_only_the_read_only_script():
    job = _yaml(SERIES_LANE)["jobs"]["build"]
    assert job["environment"] == "v2-staging" and "permissions" not in job
    holding = [s for s in job["steps"] if R2_ANY.search(str(s.get("env") or {}))]
    assert len(holding) == 1
    assert re.findall(r"scripts/[a-z_]+\.py", holding[0]["run"]) == ["scripts/build_green_series.py"]
    assert not R2_ANY.search(str(job.get("env") or {}))


def test_no_rebuild_step_mixes_earth_engine_and_the_bucket():
    """The detection modules import config.settings, which loads the .env."""

    for name, job in _yaml(REBUILD_LANE)["jobs"].items():
        for step in job["steps"]:
            secrets = set(SECRET.findall(str(step.get("env") or {})))
            if "GEE_GREEN_SA_KEY" in secrets:
                assert not any(s.startswith("R2_") for s in secrets), step["name"]
            if "rebuild_green_series.py" in (step.get("run") or ""):
                assert secrets == {"GEE_GREEN_SA_KEY"} and "--service-account" in step["run"]


def test_no_series_lane_pushes_to_main_or_names_a_pointer():
    for path in (SERIES_LANE, REBUILD_LANE):
        text = "\n".join(line.split("#", 1)[0] for line in path.read_text().splitlines()
                         if not line.lstrip().startswith("#"))
        assert not re.search(r"git push[^\n]*\bmain\b", text), path.name
        assert "pointers/" not in text and "publish_green_release" not in text
        assert "timeseries.db" not in text.replace("green_series.db", "")
        assert "RELEASE.json" not in text


def test_the_publish_step_follows_section_6_1():
    step = _named(SERIES_LANE, "publish", "Publish the green series")
    assert step["shell"] == "bash"
    assert not re.search(r"\bexit 0\b", step["run"])
    assert "gh pr create" in step["run"] and "gh pr merge" in step["run"]


# ── the publish step, executed ───────────────────────────────────────────────


def _run_publish(tmp_path, *, stray: bool):
    """Run the workflow's own publish script against a throwaway remote."""

    if shutil.which("git") is None:
        pytest.skip("git is not available")
    step = _named(SERIES_LANE, "publish", "Publish the green series")
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1",
           "GITHUB_RUN_ID": "4242", "GITHUB_SERVER_URL": "https://example.invalid",
           "GITHUB_REPOSITORY": "o/r", "SERIES": str(tmp_path / "series")}
    run = lambda *a, cwd=work: subprocess.run(a, cwd=cwd, env=env, check=True,  # noqa: E731
                                             capture_output=True, text=True)
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True,
                   capture_output=True, env=env)
    work.mkdir()
    run("git", "init", "-b", "main")
    run("git", "config", "user.email", "t@example.invalid")
    run("git", "config", "user.name", "t")
    (work / "data" / "timeseries").mkdir(parents=True)
    (work / "data" / "timeseries" / "keep").write_text("x")
    (work / "README").write_text("r")
    run("git", "add", "-A")
    run("git", "commit", "-m", "base")
    run("git", "remote", "add", "origin", str(remote))
    run("git", "push", "origin", "main")
    main_before = run("git", "rev-parse", "main").stdout.strip()
    (tmp_path / "series").mkdir()
    (tmp_path / "series" / "green_series.db").write_bytes(b"db")
    (tmp_path / "series" / "GREEN_SERIES.json").write_text("{}\n")
    if stray:
        (work / "README").write_text("changed outside data/timeseries/")
        run("git", "add", "README")
    calls = tmp_path / "gh_calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n'
                                'case "$1 $2" in "pr create") echo https://example.invalid/pr/1;; esac\n')
    (bin_dir / "gh").chmod(0o755)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    done = subprocess.run(["bash", "-c", step["run"]], cwd=work, env=env,
                          capture_output=True, text=True)
    heads = subprocess.run(["git", "--git-dir", str(remote), "for-each-ref",
                            "--format=%(refname) %(objectname)"], capture_output=True,
                           text=True, env=env).stdout.split("\n")
    refs = dict(line.split(" ", 1) for line in heads if line)
    gh = calls.read_text().splitlines() if calls.exists() else []
    return done, refs, main_before, gh


def test_the_publish_step_opens_and_merges_a_pr_and_never_moves_main(tmp_path):
    done, refs, main_before, gh = _run_publish(tmp_path, stray=False)
    assert done.returncode == 0, done.stderr
    assert refs["refs/heads/main"] == main_before
    assert "refs/heads/auto/timeseries-4242" in refs
    assert gh[0].startswith("pr create --base main --head auto/timeseries-4242")
    assert gh[1].startswith("pr merge https://example.invalid/pr/1 --squash")


def test_the_publish_step_refuses_a_change_outside_data_timeseries(tmp_path):
    done, refs, main_before, gh = _run_publish(tmp_path, stray=True)
    assert done.returncode == 1
    assert "refusing to open a PR touching paths outside data/timeseries/" in done.stdout
    assert set(refs) == {"refs/heads/main"} and refs["refs/heads/main"] == main_before
    assert gh == []


# ── the reconstruction binds a re-pulled composite to its sealed hash ───────


def _tif(path: Path, value: float) -> bytes:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    data = np.full((4, 8, 8), value, dtype="float32")
    data[:, 0, 0] = -9999.0
    with rasterio.open(path, "w", driver="GTiff", width=8, height=8, count=4,
                       dtype="float32", transform=from_origin(0, 8, 1, 1)) as dst:
        dst.write(data)
    return path.read_bytes()


def _rebuild_ledger(sealed: str):
    acq = {"acquisition_id": "acq-v3-" + "1" * 64, "datatake_id": "GS2B_X",
           "scene_ids": ["S/X"], "identity_inputs_sha256": "2" * 64,
           "composite_method_id": "datatake_mosaic-v1",
           "collection_id": "COPERNICUS/S2_SR_HARMONIZED"}
    low = dict(acq, acquisition_id="acq-v3-" + "3" * 64, datatake_id="GS2A_Y")
    return {"ledger_id": "pl-v3-" + "a" * 64, "run_manifest_id": "run-v3-x",
            "monitoring_extent_id": "araripe-implementation-rectangle-v1",
            "algorithm_version": "1.1.0", "expected_acquisitions": [acq, low],
            "terminal_rows": [
                {"acquisition_id": acq["acquisition_id"], "observed_on": "2026-06-06",
                 "status": "complete_zero_alerts", "output": {"artifact_sha256": sealed}},
                {"acquisition_id": low["acquisition_id"], "observed_on": "2026-06-06",
                 "status": "rejected_low_coverage", "output": None}]}


class _FakeReplay:
    def __init__(self, source: Path):
        self.source, self.pulled = source, []

    def pull_composite(self, ee, export, item, out_path, *, start, end, max_cloud, workers):
        assert (start, end, max_cloud) == ("2026-06-06", "2026-06-07", 60)
        self.pulled.append(item["datatake_id"])
        shutil.copyfile(self.source, out_path)


def test_the_rebuild_pulls_only_what_a_row_needs_and_binds_it(tmp_path):
    script = _load("rebuild_green_series")
    source = tmp_path / "source.tif"
    body = _tif(source, 0.25)
    sealed = __import__("hashlib").sha256(body).hexdigest()
    replay = _FakeReplay(source)
    document = script.rebuild_run(replay, None, None, _rebuild_ledger(sealed), tmp_path / "w",
                                  baseline_version="2.1.0", workers=1)
    assert replay.pulled == ["GS2B_X"]          # the low-coverage one pulled nothing
    (row,) = document["acquisitions"]
    assert row["composite_sha256"] == sealed and row["qa_status"] == "accepted"
    assert abs(row["indices"]["ndmi"]["mean"] - 0.25) < 1e-6
    assert not (tmp_path / "w" / "composites").exists()


def test_the_rebuild_stops_when_earth_engine_returns_other_bytes(tmp_path):
    script = _load("rebuild_green_series")
    source = tmp_path / "source.tif"
    _tif(source, 0.25)
    with pytest.raises(gr.RowsRejected, match="the ledger sealed"):
        script.rebuild_run(_FakeReplay(source), None, None, _rebuild_ledger("0" * 64),
                           tmp_path / "w", baseline_version="2.1.0", workers=1)
    assert not (tmp_path / "w" / "composites").exists()
