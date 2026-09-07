"""The operational publication lane, and the two authorities it splits across.

Package 2B.2C closes the last Package 2B.2 bullet — *keep operational data
publication automatic without PRs or manual merges*.  The properties worth
pinning are the ones that make that true **structurally** rather than by
policy, because a policy is a sentence and this has to be a fact about the
file:

* the lane cannot open a pull request, because it holds no permission that
  would let it commit, push or call ``gh pr create``;
* the two jobs hold different identities — candidate for "is this
  publishable?", promotion for "publish and move the pointer" — and neither
  script can even name the other's credential;
* the promotion job is inert, because the Environment it would need does not
  exist and *naming* a missing environment would create one with no
  protection rules at all;
* the blue lane is byte-identical.

The blue publish step is the thing being replaced, so it is also the thing
this file reads to prove the replacement is not a copy of it.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

from src.publication import conditional_store as cs
from src.publication import run_inputs as ri
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import build_ledger
from tests.test_promotion_lane import executed
from tests.test_run_inputs import RUN_ID, SPEC, run_layout

REPO = Path(__file__).parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
LANE = WORKFLOWS / "v2_operational_publish.yml"
PROMOTION_LANE = WORKFLOWS / "v2_promotion_lane.yml"
CANDIDATE_LANE = WORKFLOWS / "v2_candidate_replay.yml"
BLUE = WORKFLOWS / "detect_gee.yml"

STAGE_SCRIPT = REPO / "scripts" / "stage_green_run.py"
PUBLISH_SCRIPT = REPO / "scripts" / "publish_green_release.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


stage_cli = load_module(STAGE_SCRIPT, "stage_green_run")


@pytest.fixture(scope="module")
def lane():
    return yaml.safe_load(LANE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lane_text():
    return LANE.read_text(encoding="utf-8")


def jobs(lane):
    return lane["jobs"]


def steps(job):
    return job["steps"]


def all_executed(lane) -> str:
    return "\n".join(
        executed(step.get("run", ""))
        for job in lane["jobs"].values()
        for step in job["steps"]
    )


# ── no pull request is expressible from this file ────────────────────────────

def test_the_lane_cannot_write_to_the_repository(lane):
    """The whole point of the package, as a property of the file.

    `detect_gee.yml` needs `contents: write` and `pull-requests: write` to
    publish its DB.  This lane has neither, so no commit, branch push or PR
    exists as a capability rather than as a promise.
    """

    assert lane["permissions"] == {"contents": "read"}
    for job in jobs(lane).values():
        assert "permissions" not in job, "a job must not widen the workflow's grant"


def test_no_git_or_pull_request_command_is_reachable(lane):
    scripts = all_executed(lane)
    for forbidden in (
        "gh pr create",
        "gh pr merge",
        "git commit",
        "git push",
        "git add",
        "GITHUB_TOKEN",
        "actions/create-pull-request",
    ):
        assert forbidden not in scripts, forbidden


def test_the_blue_lane_publishes_through_a_pull_request_and_this_one_does_not():
    """The contrast is the package, so read both files rather than assert one."""

    blue = yaml.safe_load(BLUE.read_text(encoding="utf-8"))
    blue_publish = next(
        step
        for job in blue["jobs"].values()
        for step in job["steps"]
        if step.get("name") == "Publish time-series DB through a pull request"
    )
    assert "gh pr create" in blue_publish["run"]
    assert blue["permissions"]["pull-requests"] == "write"

    green = yaml.safe_load(LANE.read_text(encoding="utf-8"))
    assert "pull-requests" not in green["permissions"]


def test_the_data_path_is_the_object_store_not_a_repository_path(lane):
    """Green data never reaches `data/`; it is read from and written to R2."""

    scripts = all_executed(lane)
    assert "runs/" in scripts or "run_prefix" in scripts or "--run" in scripts
    assert "data/timeseries" not in scripts
    assert "data/alerts" not in scripts


# ── inertness, and why the promotion job names no Environment ────────────────

def test_the_lane_is_dispatch_only(lane):
    """A green lane may not carry a cron before the Phase 6 cutover."""

    triggers = lane[True] if True in lane else lane["on"]
    assert list(triggers) == ["workflow_dispatch"]


def test_the_promotion_job_binds_the_protected_promotion_environment(lane):
    """Measured, not assumed: `v2-promotion` was created during this package.

    Read back on 2026-09-07 before binding it — rules ["branch_policy"] with
    no required reviewer, deployment branch policy ["branch: main"], the two
    R2_PROMOTION_* secrets and the three variables, exactly as
    docs/operations/PROMOTION_IDENTITY_SETUP.md specifies.

    An Environment name that does not exist must never be written here: GitHub
    creates one on first run with no protection rules and no branch policy,
    which is a repository configuration change producing the wrong thing.
    """

    promote = jobs(lane)["promote"]
    assert promote["environment"] == "v2-promotion"
    named = set(re.findall(r"secrets\.([A-Za-z_0-9]+)", yaml.dump(promote)))
    assert named == {"R2_PROMOTION_ACCESS_KEY_ID", "R2_PROMOTION_SECRET_ACCESS_KEY"}


def test_the_promotion_job_never_borrows_the_candidate_identity(lane):
    """Lane 3 must not hold lane 2's key; that split is why the lanes exist."""

    promote = yaml.dump(jobs(lane)["promote"])
    candidate_secrets = re.findall(
        r"secrets\.([A-Za-z_0-9]+)", CANDIDATE_LANE.read_text(encoding="utf-8")
    )
    assert candidate_secrets, "the candidate lane should hold the staging identity"
    for name in candidate_secrets:
        assert name not in promote


def test_the_promotion_job_publishes_without_touching_git(lane):
    scripts = "\n".join(
        executed(step.get("run", "")) for step in steps(jobs(lane)["promote"])
    )
    assert "publish_green_release.py publish --run" in scripts
    for forbidden in ("git ", "gh pr", "apply", "rollback"):
        assert forbidden not in scripts, forbidden


def test_the_promotion_job_keeps_the_bucket_and_endpoint_guards(lane):
    guard = steps(jobs(lane)["promote"])[0]["run"]
    assert "araripe-v2-staging" in guard
    assert "9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com" in guard


def test_both_jobs_allowlist_the_run_id_before_it_becomes_a_key(lane):
    """Each job builds object keys from it, so each has to check it."""

    for name, job in jobs(lane).items():
        step = next(step for step in steps(job) if "run id" in step["name"])
        assert "*[!A-Za-z0-9._-]*" in executed(step["run"]), name


def test_the_staging_job_runs_only_the_read_only_gate(lane):
    invocations = re.findall(
        r"scripts/(\w+)\.py", "\n".join(
            executed(step.get("run", "")) for step in steps(jobs(lane)["stage"])
        )
    )
    assert set(invocations) == {"stage_green_run"}


# ── two lanes, two identities ────────────────────────────────────────────────

def test_the_two_jobs_sit_in_the_two_green_lanes(lane):
    assert jobs(lane)["stage"]["concurrency"] == {
        "group": "araripe-green-candidate",
        "cancel-in-progress": False,
    }
    assert jobs(lane)["promote"]["concurrency"] == {
        "group": "araripe-green-promotion",
        "cancel-in-progress": False,
    }
    assert "concurrency" not in lane, (
        "a workflow-level group would put both jobs in one lane"
    )


def test_promotion_waits_for_the_smaller_authority_to_accept_the_run(lane):
    """A malformed run fails under the candidate identity; lane 3 never starts."""

    assert jobs(lane)["promote"]["needs"] == "stage"
    assert jobs(lane)["stage"]["outputs"]["release_id"]


def test_the_staging_job_binds_only_the_candidate_identity(lane, lane_text):
    stage = jobs(lane)["stage"]
    assert stage["environment"] == "v2-staging"
    named = set(re.findall(r"secrets\.([A-Za-z_0-9]+)", yaml.dump(stage)))
    assert named == {"R2_STAGING_ACCESS_KEY_ID", "R2_STAGING_SECRET_ACCESS_KEY"}
    assert "R2_PROMOTION" not in yaml.dump(stage)


def test_the_staging_job_keeps_the_bucket_and_endpoint_guards(lane):
    guard = steps(jobs(lane)["stage"])[0]["run"]
    assert "araripe-v2-staging" in guard
    assert "9416750169311ee4afc18a8ff3c771d4.r2.cloudflarestorage.com" in guard


def test_the_repository_guard_is_kept(lane):
    for job in jobs(lane).values():
        assert "github.repository == 'santibravocmcc/Araripe'" in job["if"]


def test_the_lane_does_not_install_the_blue_environment_file(lane):
    """Coupling a green lane to the file the blue workflows solve, and worse.

    Measured 2026-09-07: environment.yml pins botocore>=1.35.0,<1.36.0, and in
    that range PutObject has no `IfMatch` at all, so the pointer
    compare-and-swap could not be expressed.
    """

    scripts = all_executed(lane)
    assert "environment.yml" not in scripts
    assert "setup-miniconda" not in LANE.read_text(encoding="utf-8")
    assert "botocore>=1.36.0" in scripts


def test_actions_are_pinned_by_the_sha_the_green_lanes_already_use(lane_text):
    used = set(re.findall(r"uses:\s*(\S+)", lane_text))
    pinned = set(re.findall(r"uses:\s*(\S+)", PROMOTION_LANE.read_text(encoding="utf-8")))
    assert used, "the lane should check the code out"
    assert used <= pinned, f"unpinned or unfamiliar action: {used - pinned}"


# ── lane distinctness, counting job-level groups ─────────────────────────────
#
# `tests/test_workflow_lanes.py` reads `concurrency:` at the WORKFLOW level
# only, which was complete while every workflow declared one group for the
# whole file.  This is the first file whose jobs sit in two different lanes, so
# it would slip through that sweep entirely.  The property is re-established
# here over both levels rather than by rewriting that file, because the same
# assertions have to hold for workflows that do not exist yet.

def every_declared_group() -> dict[tuple[str, str | None], str]:
    """``{(workflow, job or None): group}`` across every workflow file."""

    found: dict[tuple[str, str | None], str] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if doc.get("concurrency"):
            found[(path.name, None)] = doc["concurrency"]["group"]
        for job_name, job in (doc.get("jobs") or {}).items():
            if job.get("concurrency"):
                found[(path.name, job_name)] = job["concurrency"]["group"]
    return found


def test_this_workflow_declares_its_groups_per_job_not_per_file():
    declared = every_declared_group()
    assert declared[(LANE.name, "stage")] == "araripe-green-candidate"
    assert declared[(LANE.name, "promote")] == "araripe-green-promotion"
    assert (LANE.name, None) not in declared


def test_no_group_is_shared_between_the_blue_lane_and_a_green_one():
    """The distinctness argument a long green run must never invalidate."""

    declared = every_declared_group()
    blue = {
        member for member, group in declared.items() if group == "araripe-legacy-state"
    }
    assert blue == {("detect_gee.yml", None), ("update_data.yml", None)}
    green_groups = {
        group for group in declared.values() if group != "araripe-legacy-state"
    }
    assert "araripe-legacy-state" not in green_groups


def test_the_promotion_group_is_shared_only_with_the_promotion_lane():
    """Serialization exists only if the two promoters share one group.

    Two groups would serialize each file against itself and still let a
    dispatch of `v2_promotion_lane.yml` interleave with this one — the same
    argument that puts both blue state writers in `araripe-legacy-state`.
    """

    declared = every_declared_group()
    members = {m for m, g in declared.items() if g == "araripe-green-promotion"}
    assert members == {(PROMOTION_LANE.name, None), (LANE.name, "promote")}


def test_no_declared_group_cancels_a_run_in_progress():
    """Cancelling mid-publication would leave objects without their pointer."""

    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        blocks = [doc.get("concurrency")] + [
            job.get("concurrency") for job in (doc.get("jobs") or {}).values()
        ]
        for block in blocks:
            if block is not None:
                assert block["cancel-in-progress"] is False, path.name


def test_no_green_lane_can_inherit_a_schedule():
    """Package 2B.0 inertness, over job-level lanes too."""

    declared = every_declared_group()
    green = {
        name
        for (name, _), group in declared.items()
        if group != "araripe-legacy-state"
    }
    assert LANE.name in green
    for name in green:
        doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        assert "schedule" not in doc[True], name


# ── the two scripts cannot see each other's credential ───────────────────────

def test_the_staging_script_never_names_the_promotion_identity():
    source = STAGE_SCRIPT.read_text(encoding="utf-8")
    assert "R2_PROMOTION_ACCESS_KEY_ID" not in source
    assert "R2_PROMOTION_SECRET_ACCESS_KEY" not in source
    assert stage_cli.ACCESS_KEY_VAR == "R2_STAGING_ACCESS_KEY_ID"


def test_the_publication_script_still_never_names_the_candidate_identity():
    """Re-run here because 2B.2C edits that file; the 2B.2B property must hold."""

    source = PUBLISH_SCRIPT.read_text(encoding="utf-8")
    assert "R2_STAGING_ACCESS_KEY_ID" not in source
    assert "R2_STAGING_SECRET_ACCESS_KEY" not in source


def test_no_write_call_is_reachable_from_the_staging_script():
    """Read from the syntax tree, not from a substring scan of prose."""

    tree = ast.parse(STAGE_SCRIPT.read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {name for name in called if name.startswith("put")}
    assert "ReadOnlyStore" in {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }


def test_the_staging_script_fails_closed_without_the_candidate_identity(
    monkeypatch, capsys
):
    monkeypatch.setenv("R2_STAGING_BUCKET", cs.STAGING_BUCKET)
    monkeypatch.setenv("R2_ENDPOINT_URL", cs.STAGING_ENDPOINT)
    monkeypatch.delenv("R2_STAGING_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_STAGING_SECRET_ACCESS_KEY", raising=False)
    assert stage_cli.main(["--run", RUN_ID]) == 1
    assert "missing R2 credentials" in capsys.readouterr().err


def test_the_staging_script_refuses_the_production_bucket_by_name(
    monkeypatch, capsys
):
    monkeypatch.setenv("R2_STAGING_BUCKET", cs.PRODUCTION_BUCKET)
    monkeypatch.setenv("R2_ENDPOINT_URL", cs.STAGING_ENDPOINT)
    monkeypatch.setenv("R2_STAGING_ACCESS_KEY_ID", "would-not-matter")
    monkeypatch.setenv("R2_STAGING_SECRET_ACCESS_KEY", "would-not-matter")
    assert stage_cli.main(["--run", RUN_ID]) == 1
    assert "production is frozen" in capsys.readouterr().err


# ── the staging script end to end, against the fake store ───────────────────

@pytest.fixture
def staged_store(monkeypatch):
    document, bodies = build_ledger(SPEC)
    _, stored = run_layout(document, bodies)
    fake = FakeS3(stored)
    monkeypatch.setattr(
        stage_cli, "build_read_only_store",
        lambda: ri.ReadOnlyStore(fake, cs.STAGING_BUCKET),
    )
    return fake


def test_the_staging_script_reports_the_release_and_writes_nothing(
    staged_store, capsys, tmp_path, monkeypatch
):
    output = tmp_path / "gh-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert stage_cli.main(["--run", RUN_ID]) == 0

    out = capsys.readouterr().out
    assert "2026-04-07  alerts" in out
    assert "2026-04-10  zero_alerts" in out
    assert "read-only — nothing was written" in out
    assert staged_store.writes == []

    handed_on = output.read_text(encoding="utf-8")
    assert handed_on.startswith("release_id=rel-g1-")


def test_the_staging_script_can_print_the_manifest(staged_store, capsys):
    assert stage_cli.main(["--run", RUN_ID, "--json"]) == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["schema"] == "araripe.green.release/1"


def test_a_broken_run_prefix_fails_before_the_promotion_job_would_start(
    staged_store, capsys
):
    """Every finding at once, under the smaller authority."""

    for key in [k for k in staged_store.objects if "/objects/" in k]:
        staged_store.objects.pop(key)
    assert stage_cli.main(["--run", RUN_ID]) == 1
    err = capsys.readouterr().err
    assert "run_object_absent" in err
    assert "2 finding(s)" in err


def test_the_staging_script_refuses_a_run_id_that_escapes_its_prefix(
    staged_store, capsys
):
    assert stage_cli.main(["--run", "../pointers"]) == 1
    assert "run_id_invalid" in capsys.readouterr().err


# ── the publication CLI's new mode ───────────────────────────────────────────

def test_the_publication_cli_exposes_publish_from_a_run(capsys):
    publish_cli = load_module(PUBLISH_SCRIPT, "publish_green_release_2b2c")
    with pytest.raises(SystemExit):
        publish_cli.main(["publish"])  # --run is required
    assert "--run" in capsys.readouterr().err
