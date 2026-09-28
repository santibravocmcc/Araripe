"""The green deposit lane, read from its workflow file.

``.github/workflows/v2_green_deposit_lane.yml`` is the first workflow that runs
``assemble_green_run.py apply``. Its safety is almost entirely *which step
holds which credential*, and a workflow file is where that is decided, so these
tests read the file per job and per step rather than trusting its comments
(PHASE_6E_2026-09-28.md §3, PHASE_6F_2026-09-28.md §3).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.test_assemble_green_run import GREEN_SCRIPTS

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v2_green_deposit_lane.yml"
REQUIREMENTS = ROOT / "requirements-green-detect.txt"

SECRET = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")
SCRIPT = re.compile(r"python3?\s+(scripts/[A-Za-z0-9_./-]+\.py)")
R2_STAGING = {"R2_STAGING_ACCESS_KEY_ID", "R2_STAGING_SECRET_ACCESS_KEY"}
GREEN_EE = {"GEE_GREEN_SA_KEY"}
BLUE = ("GEE_SA_KEY", "R2_ACCESS_KEY", "R2_SECRET_KEY", "EE_PROJECT",
        "R2_PROMOTION_ACCESS_KEY_ID", "R2_PROMOTION_SECRET_ACCESS_KEY")


def doc():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def executable_lines(text: str) -> list[str]:
    """Lines with YAML comments removed — a comment naming a secret is not a use."""

    return [line.split("#", 1)[0] for line in text.splitlines()
            if not line.lstrip().startswith("#")]


def steps(job: str):
    return doc()["jobs"][job]["steps"]


def step_secrets(step) -> set[str]:
    return set(SECRET.findall(str(step.get("env") or {})))


def step_scripts(step) -> set[str]:
    return set(SCRIPT.findall(step.get("run") or ""))


# ─── trigger and shape ───────────────────────────────────────────────────────


def test_manual_only_read_only_and_unscheduled():
    d = doc()
    assert set(d[True]) == {"workflow_dispatch"}, "scheduling is Phase 6 §4.5"
    assert d["permissions"] == {"contents": "read"}


def test_two_jobs_the_deposit_after_the_detection():
    jobs = doc()["jobs"]
    assert list(jobs) == ["detect", "deposit"]
    assert jobs["deposit"]["needs"] == "detect"


def test_both_jobs_use_the_existing_environment_only():
    """Never name an Environment that does not exist: GitHub creates it unprotected."""

    for name, job in doc()["jobs"].items():
        assert job["environment"] == "v2-staging", name


def test_the_writing_job_holds_the_candidate_lane_and_nothing_cancels():
    d = doc()
    assert "concurrency" not in d, (
        "araripe-green-candidate is already v2_candidate_replay.yml's "
        "workflow-level group; this lane holds it per job, as the publish lane does"
    )
    assert d["jobs"]["deposit"]["concurrency"] == {
        "group": "araripe-green-candidate", "cancel-in-progress": False,
    }


# ─── who holds what ──────────────────────────────────────────────────────────


def test_no_step_holds_both_identities():
    for job in ("detect", "deposit"):
        for step in steps(job):
            held = step_secrets(step)
            assert not (held & GREEN_EE and held & R2_STAGING), step["name"]


def test_the_deposit_job_never_holds_earth_engine():
    for step in steps("deposit"):
        assert not step_secrets(step) & GREEN_EE, step["name"]
        assert step_secrets(step) <= R2_STAGING, step["name"]


def test_in_the_detect_job_r2_is_held_only_to_fetch():
    """PHASE_6F §3 and PHASE_6G: the R2 steps download, and run no config importer.

    Two of them now — the predecessor's state and the baseline — each running
    exactly one read-only script, the state first so a refused window costs
    nothing.
    """

    holders = [s for s in steps("detect") if step_secrets(s) & R2_STAGING]
    assert [s["name"] for s in holders] == [
        "Fetch and verify the predecessor's persistence state",
        "Fetch and verify the baseline months the window needs",
    ]
    state, baseline = holders
    assert step_scripts(state) == {"scripts/fetch_green_state.py"}
    assert step_scripts(baseline) == {"scripts/baseline_v2_staging.py"}
    assert " fetch " in baseline["run"] and " upload" not in baseline["run"]
    assert state["if"] == "steps.window.outputs.from_run != ''"


def test_the_state_fetch_opens_the_store_read_only_and_without_the_profile():
    """A lane step: no local key (the revocation condition), no write path."""

    import ast

    source = (ROOT / "scripts" / "fetch_green_state.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    names = {getattr(c.func, "attr", getattr(c.func, "id", "")) for c in calls}
    assert "ReadOnlyStore" in names and "ConditionalStore" not in names
    assert "put_if_absent" not in names and "seed_state" not in names
    for call in calls:
        if getattr(call.func, "attr", "") == "build_client":
            assert not any(k.arg == "profile_fallback" for k in call.keywords)


def test_every_step_holding_r2_runs_only_scripts_clear_of_the_dotenv():
    """``config/settings.py`` loads the production ``.env`` at import.

    The detection imports it and holds no R2 identity; every script that runs
    WITH one is in the guarded list of ``tests/test_assemble_green_run.py``.
    """

    for job in ("detect", "deposit"):
        for step in steps(job):
            if step_secrets(step) & R2_STAGING:
                names = {Path(s).name for s in step_scripts(step)}
                assert names and names <= set(GREEN_SCRIPTS), (step["name"], names)


def test_earth_engine_is_used_only_as_the_green_account():
    runs = [s for s in steps("detect") if "replay_2026.py" in (s.get("run") or "")]
    assert len(runs) == 2
    for step in runs:
        assert "--service-account" in step["run"], step["name"]
        assert step_secrets(step) == GREEN_EE, step["name"]


def test_no_blue_or_promotion_secret_appears():
    text = "\n".join(executable_lines(WORKFLOW.read_text(encoding="utf-8")))
    used = set(SECRET.findall(text))
    assert used == R2_STAGING | GREEN_EE
    for name in BLUE:
        assert not re.search(rf"\b{name}\b", text), name


def test_no_step_can_move_a_pointer():
    text = "\n".join(executable_lines(WORKFLOW.read_text(encoding="utf-8")))
    assert "publish_green_release" not in text
    assert "pointers/" not in text


# ─── the run and its inputs ──────────────────────────────────────────────────


def test_the_run_id_names_one_execution_and_not_one_attempt():
    """PHASE_6E §4: a whole-workflow re-run must conflict, not duplicate."""

    text = "\n".join(executable_lines(WORKFLOW.read_text(encoding="utf-8")))
    assert '"run_id=ci-%s\\n" % os.environ["GITHUB_RUN_ID"]' in text
    assert "run_attempt" not in text and "RUN_ATTEMPT" not in text


def test_the_detection_starts_from_the_fetched_state_or_from_nothing():
    """Without from_run the state must be absent; with it, fetched and linked."""

    (run,) = [s for s in steps("detect") if "replay_2026.py run" in (s.get("run") or "")]
    body = run["run"]
    chained, empty = body.split("else", 1)
    assert 'if [ -n "$FROM_RUN" ]' in chained
    assert 'test -s "$REPLAY_DIR/persistence_state.geojson"' in chained
    assert 'test -s "$REPLAY_DIR/predecessor.json"' in chained
    assert 'test ! -e "$REPLAY_DIR/persistence_state.geojson"' in empty
    assert 'test ! -e "$REPLAY_DIR/predecessor.json"' in empty
    assert '--state-path "$REPLAY_DIR/persistence_state.geojson"' in body


def test_from_run_is_one_path_segment_checked_before_anything_is_spent():
    window = steps("detect")[1]
    assert window["name"] == "Accept only a bounded window of real dates, and name the run"
    assert "[A-Za-z0-9][A-Za-z0-9._-]{0,127}" in window["run"]
    assert 'out.write("from_run=%s\\n" % from_run)' in window["run"]
    assert doc()["jobs"]["detect"]["outputs"]["from_run"] == "${{ steps.window.outputs.from_run }}"
    assert doc()["jobs"]["deposit"]["env"]["FROM_RUN"] == "${{ needs.detect.outputs.from_run }}"
    assert doc()[True]["workflow_dispatch"]["inputs"]["from_run"]["required"] is False


def test_the_link_travels_to_the_deposit_and_is_used_only_with_from_run():
    upload = [s for s in steps("detect") if s["name"] == "Hand the detection's outputs to the deposit job"]
    assert "replay/predecessor.json" in upload[0]["with"]["path"]
    for job, name in (("detect", "Assemble the run prefix locally, with no credential"),
                      ("deposit", "Deposit runs/<run-id>/ with the candidate identity")):
        (step,) = [s for s in steps(job) if s["name"] == name]
        assert 'if [ -n "$FROM_RUN" ]; then LINK=(--predecessor' in step["run"]
        assert '${LINK[@]+"${LINK[@]}"}' in step["run"]


def test_the_window_is_bounded_before_anything_is_spent():
    names = [s["name"] for s in steps("detect")]
    window = names.index("Accept only a bounded window of real dates, and name the run")
    assert window < names.index("Fetch and verify the baseline months the window needs")
    assert "(b - a).days <= 16" in steps("detect")[window]["run"]


def test_the_deposit_is_validated_read_only_after_it_is_written():
    names = [s["name"] for s in steps("deposit")]
    deposit = names.index("Deposit runs/<run-id>/ with the candidate identity")
    check = names.index("Re-read the prefix and validate it, writing nothing")
    assert deposit < check
    assert "assemble_green_run.py apply" in steps("deposit")[deposit]["run"]
    assert "stage_green_run.py" in steps("deposit")[check]["run"]


def test_the_detection_environment_is_pinned_exactly():
    lines = [l.strip() for l in REQUIREMENTS.read_text().splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    assert lines
    for line in lines:
        assert re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][A-Za-z0-9.]*", line), line
    pins = dict(line.split("==") for line in lines)
    major, minor, *_ = pins["botocore"].split(".")
    assert (int(major), int(minor)) >= (1, 36), "botocore <1.36 cannot express If-Match"
    assert "earthengine-api" in pins


@pytest.mark.parametrize("job", ["detect", "deposit"])
def test_both_jobs_refuse_any_bucket_but_staging_first(job):
    first = steps(job)[0]
    assert first["name"] == "Fail closed unless the target is exactly the approved staging bucket"
    assert "araripe-v2-staging" in first["run"]
    assert not step_secrets(first)
