"""The lane that publishes the sources of the live green release (PHASE_6X).

``scripts/publish_green_sources.py`` against a fake bucket holding a version-3
release of three members, its ledger index, and a land-cover context: what
``fetch`` reads, what ``plan`` builds, and what ``apply`` refuses to write.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.publication import chain_release as cr
from src.publication import conditional_store as cs
from src.publication import green_context as gc
from src.publication import green_sources as gs
from src.publication.green_release import ledger_bytes, release_bytes
from tests.fake_object_store import FakeS3
from tests.test_chain_release import HEAD, MIDDLE, ROOT, chain
from tests.test_green_sources import SPEC, _context_for

REPO = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("publish_green_sources", REPO / "scripts/publish_green_sources.py")
    module = importlib.util.module_from_spec(spec)
    # Registered before running: a dataclass resolves its module by name.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pgs = _script()


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _put(fake: FakeS3, key: str, body: bytes) -> None:
    fake.objects[key] = (body, "application/json")


def _point_context(fake: FakeS3, context: dict) -> None:
    body = gc.serialise(context)
    _put(fake, context["context_prefix"] + gc.CONTEXT_DOCUMENT_NAME, body)
    _put(fake, gc.CONTEXT_CURRENT_KEY, gc.serialise(gc.pointer_document(
        context=context, context_document_sha256=_sha(body), sequence=1,
        written_utc="2026-10-10T00:00:00Z", written_by={})))


def _point_release(fake: FakeS3, release: dict) -> None:
    body = release_bytes(release)
    _put(fake, release["release_prefix"] + "release.json", body)
    _put(fake, pgs.POINTER_KEY, json.dumps({
        "schema": "araripe.green.pointer/1", "sequence": 18, "release_id": release["release_id"],
        "release_path": release["release_prefix"] + "release.json",
        "release_document_sha256": _sha(body)}).encode())


@pytest.fixture()
def bucket():
    """A live version-3 release, its members' ledgers and index, and its context."""

    members, _bodies = chain(ROOT, MIDDLE, HEAD)
    release, index = cr.build_reference_release(members)
    fake = FakeS3()
    for member in members:
        prefix = member.release["release_prefix"]
        _put(fake, prefix + "release.json", release_bytes(member.release))
        _put(fake, prefix + "ledger.json", ledger_bytes(member.ledger_document))
    _put(fake, release["release_prefix"] + "ledger.json", ledger_bytes(index))
    _point_release(fake, release)
    context = _context_for(release)
    _point_context(fake, context)
    store = cs.ConditionalStore(fake, cs.STAGING_BUCKET)
    ledgers = [m.ledger_document for m in members]
    return store, fake, release, context, ledgers


def _publish(tmp_path, store, *extra) -> tuple[int, Path]:
    source, out = tmp_path / "in", tmp_path / "out"
    assert pgs.main(["fetch", "--out", str(source)], store=store) == 0
    assert pgs.main(["plan", "--input", str(source), "--out", str(out), *extra]) == 0
    return pgs.main(["apply", "--sources", str(out)], store=store), out


# ── the happy path ───────────────────────────────────────────────────────────

def test_the_lane_publishes_the_document_the_inputs_determine_and_points_at_it(tmp_path, bucket):
    store, fake, release, context, ledgers = bucket
    code, _out = _publish(tmp_path, store)
    assert code == 0
    expected = gs.build_sources(release, context, SPEC, ledgers)
    body = fake.objects[expected["sources_prefix"] + "sources.json"][0]
    assert body == gs.serialise(expected)
    pointer = json.loads(fake.objects[gs.SOURCES_CURRENT_KEY][0])
    assert (pointer["sources_id"], pointer["release_id"], pointer["context_id"], pointer["sequence"]) == (
        expected["sources_id"], release["release_id"], context["context_id"], 1)
    assert pointer["sources_document_sha256"] == _sha(body)
    # it wrote the document and the pointer, and nothing else
    assert [key for key, _ in fake.writes] == [expected["sources_prefix"] + "sources.json", gs.SOURCES_CURRENT_KEY]


def test_a_second_run_writes_nothing(tmp_path, bucket):
    store, fake, *_ = bucket
    assert _publish(tmp_path / "a", store)[0] == 0
    writes = len(fake.writes)
    assert _publish(tmp_path / "b", store)[0] == 0
    assert len(fake.writes) == writes


def test_fetch_reads_every_member_ledger_in_order(tmp_path, bucket):
    store, _fake, release, context, ledgers = bucket
    assert pgs.main(["fetch", "--out", str(tmp_path)], store=store) == 0
    got_release, got_context, got_ledgers = pgs.load_input(tmp_path)
    assert got_release == release and got_context == context
    assert got_ledgers == ledgers and len(got_ledgers) == 3


def test_plan_refuses_an_unexpected_id(tmp_path, bucket, capsys):
    store, *_ = bucket
    assert pgs.main(["fetch", "--out", str(tmp_path / "in")], store=store) == 0
    with pytest.raises(SystemExit) as raised:
        pgs.main(["plan", "--input", str(tmp_path / "in"), "--out", str(tmp_path / "out"),
                  "--expect", "src-g1-" + "0" * 64])
    assert "something changed between the two readings" in str(raised.value)
    assert not (tmp_path / "out").exists()


def test_plan_accepts_the_expected_id(tmp_path, bucket):
    store, _fake, release, context, ledgers = bucket
    expected = gs.build_sources(release, context, SPEC, ledgers)["sources_id"]
    assert _publish(tmp_path, store, "--expect", expected)[0] == 0


# ── what "live" means: the context must describe the live release ────────────

def test_a_context_of_another_release_is_no_context(tmp_path, bucket):
    """delivery/3 serves no context for a pointer naming another release, so the
    document must not seal the 2025 context records either."""

    store, fake, release, _context, ledgers = bucket
    stale = _context_for({**release, "release_id": "rel-g3-" + "0" * 64})
    _point_context(fake, stale)
    assert _publish(tmp_path, store)[0] == 0
    pointer = json.loads(fake.objects[gs.SOURCES_CURRENT_KEY][0])
    assert pointer["context_id"] is None
    assert pointer["sources_id"] == gs.build_sources(release, None, SPEC, ledgers)["sources_id"]


def test_no_context_at_all_is_no_context(tmp_path, bucket):
    store, fake, release, _context, ledgers = bucket
    del fake.objects[gc.CONTEXT_CURRENT_KEY]
    assert _publish(tmp_path, store)[0] == 0
    assert json.loads(fake.objects[gs.SOURCES_CURRENT_KEY][0])["context_id"] is None


# ── apply decides again, from the store ──────────────────────────────────────

def _planned(tmp_path, store) -> Path:
    assert pgs.main(["fetch", "--out", str(tmp_path / "in")], store=store) == 0
    assert pgs.main(["plan", "--input", str(tmp_path / "in"), "--out", str(tmp_path / "out")]) == 0
    return tmp_path / "out"


def test_apply_refuses_when_a_promotion_landed_after_the_plan(tmp_path, bucket):
    store, fake, release, *_ = bucket
    out = _planned(tmp_path, store)
    members, _ = chain(ROOT, MIDDLE)
    newer, index = cr.build_reference_release(members)
    _put(fake, newer["release_prefix"] + "ledger.json", ledger_bytes(index))
    _point_release(fake, newer)
    with pytest.raises(SystemExit) as raised:
        pgs.main(["apply", "--sources", str(out)], store=store)
    assert "sources are only published for the live release" in str(raised.value)
    assert gs.SOURCES_CURRENT_KEY not in fake.objects and fake.writes == []


def test_apply_refuses_when_the_context_moved_after_the_plan(tmp_path, bucket):
    store, fake, release, *_ = bucket
    out = _planned(tmp_path, store)
    del fake.objects[gc.CONTEXT_CURRENT_KEY]
    with pytest.raises(SystemExit) as raised:
        pgs.main(["apply", "--sources", str(out)], store=store)
    assert "run the lane again" in str(raised.value)
    assert fake.writes == []


def test_apply_refuses_a_document_edited_after_the_plan(tmp_path, bucket, capsys):
    store, fake, *_ = bucket
    out = _planned(tmp_path, store)
    (path,) = out.glob("sources/*/sources.json")
    document = json.loads(path.read_bytes())
    document["attribution"][0]["text"] = "Contains modified Copernicus Sentinel data"
    path.write_bytes(gs.serialise(document))
    assert pgs.main(["apply", "--sources", str(out)], store=store) == 1
    assert "does_not_derive" in capsys.readouterr().err
    assert fake.writes == []


# ── fetch verifies every byte it reads against its parent ────────────────────

@pytest.mark.parametrize("which", ["release", "index", "member_ledger", "context"])
def test_a_corrupt_read_stops_the_lane(tmp_path, bucket, which, capsys):
    store, fake, release, context, _ledgers = bucket
    key = {
        "release": release["release_prefix"] + "release.json",
        "index": release["release_prefix"] + "ledger.json",
        "member_ledger": f"releases/{release['members'][1]['release_id']}/ledger.json",
        "context": context["context_prefix"] + gc.CONTEXT_DOCUMENT_NAME,
    }[which]
    fake.tamper[key] = fake.objects[key][0][:-1] + b" "
    assert pgs.main(["fetch", "--out", str(tmp_path)], store=store) == 1
    assert "does not have the bytes and sha256" in capsys.readouterr().err


def test_plan_refuses_inputs_changed_on_disk_after_fetch(tmp_path, bucket):
    store, *_ = bucket
    assert pgs.main(["fetch", "--out", str(tmp_path / "in")], store=store) == 0
    (tmp_path / "in" / "context.json").write_bytes(b"{}")
    assert pgs.main(["plan", "--input", str(tmp_path / "in"), "--out", str(tmp_path / "out")]) == 1


# ── what the script may touch ────────────────────────────────────────────────

def test_the_script_names_no_release_pointer_writer_and_never_imports_config():
    """It reads the release pointer and writes only through ``sources_pointer``;
    ``config.settings`` loads the production ``.env``."""

    tree = ast.parse((REPO / "scripts/publish_green_sources.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {node.module or ""} | {f"{node.module}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    assert not any(name.startswith("config") for name in imported)
    assert "src.publication.context_pointer" not in imported
    calls = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "put_if_match" not in calls and "put_if_pointer_absent" not in calls
    assert "profile_fallback" not in (REPO / "scripts/publish_green_sources.py").read_text()


# ── the standalone lane ──────────────────────────────────────────────────────

def _lane() -> dict:
    import yaml

    return yaml.safe_load((REPO / ".github/workflows/v2_green_sources.yml").read_text())


def test_the_lane_is_dispatched_only_serialized_and_runs_only_from_main():
    lane = _lane()
    assert set(lane[True]) == {"workflow_dispatch"}
    assert lane[True]["workflow_dispatch"]["inputs"]["mode"]["default"] == "plan"
    assert lane["permissions"] == {"contents": "read"}
    assert lane["concurrency"] == {"group": "araripe-green-sources", "cancel-in-progress": False}
    job = lane["jobs"]["sources"]
    assert job["environment"] == "v2-promotion"
    assert "github.ref == 'refs/heads/main'" in job["if"]


def test_the_bucket_is_checked_before_any_step_holds_the_key_and_only_publish_writes():
    steps = _lane()["jobs"]["sources"]["steps"]
    names = [step["name"] for step in steps]
    first_secret = next(i for i, s in enumerate(steps) if "secrets." in json.dumps(s))
    assert names.index("Fail closed unless the target is exactly the approved staging bucket") < first_secret
    (apply,) = [s for s in steps if "publish_green_sources.py apply" in s.get("run", "")]
    assert apply["if"] == "inputs.mode == 'publish'"
    assert all("if" not in s for s in steps if s is not apply)


def test_the_expected_id_is_checked_before_it_reaches_a_command():
    check = _lane()["jobs"]["sources"]["steps"][0]
    assert check["env"] == {"MODE": "${{ inputs.mode }}", "EXPECT": "${{ inputs.expect }}"}
    assert "^src-g1-[0-9a-f]{64}$" in check["run"]
    # inputs are passed through env, never interpolated into a script
    for step in _lane()["jobs"]["sources"]["steps"]:
        assert "${{ inputs." not in step.get("run", "")
