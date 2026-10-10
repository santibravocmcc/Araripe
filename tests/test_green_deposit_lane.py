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


INPUTS = "Accept the dispatch inputs for the chosen chain mode"
HEAD = "Resolve the chain head and the automatic window"
WINDOW = "Accept only a bounded window of real dates, and name the run"
PLAN = "Enumerate and screen the window as the green account"
ENUMERATED = "Stop here when the window holds no acquisition"


def step_named(job: str, name: str):
    (step,) = [s for s in steps(job) if s["name"] == name]
    return step


def run_inline(step, tmp=None, **env):
    """Execute the step's embedded ``python3 - <<'PY'`` block as Actions would.

    The workflow's own code, not a copy of it: the text between the heredoc
    markers runs with the given environment and a fresh ``GITHUB_OUTPUT``,
    and the outputs it wrote come back as a dict.
    """

    import os
    import subprocess
    import sys
    import tempfile
    import textwrap

    body = step["run"]
    code = textwrap.dedent(body.split("<<'PY'\n", 1)[1].rsplit("PY", 1)[0])
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / "github_output"
        output.write_text("")
        environment = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(output),
                       "GITHUB_RUN_ID": "4242", "RUNNER_TEMP": str(tmp or scratch)}
        environment.update(env)
        done = subprocess.run([sys.executable, "-c", code], env=environment,
                              capture_output=True, text=True)
        values = dict(line.split("=", 1) for line in output.read_text().splitlines() if line)
    return done.returncode, values


# ─── trigger and shape ───────────────────────────────────────────────────────


def test_manual_only_read_only_and_unscheduled():
    d = doc()
    assert set(d[True]) == {"workflow_dispatch"}, "scheduling is Phase 6 §4.5"
    assert d["permissions"] == {"contents": "read"}


def test_three_jobs_the_deposit_after_the_detection_and_the_beat_after_both():
    jobs = doc()["jobs"]
    assert list(jobs) == ["detect", "deposit", "heartbeat"]
    assert jobs["deposit"]["needs"] == "detect"
    assert jobs["heartbeat"]["needs"] == ["detect", "deposit"]


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
    for job in doc()["jobs"]:
        for step in steps(job):
            held = step_secrets(step)
            assert not (held & GREEN_EE and held & R2_STAGING), step["name"]


def test_the_deposit_job_never_holds_earth_engine():
    for step in steps("deposit"):
        assert not step_secrets(step) & GREEN_EE, step["name"]
        assert step_secrets(step) <= R2_STAGING, step["name"]


def test_in_the_detect_job_r2_is_held_only_to_read():
    """PHASE_6F §3, PHASE_6G, PHASE_6H: the R2 steps read, and run no config importer.

    Three of them now — the head, the predecessor's state, the baseline — each
    running exactly one read-only script: the head only in head mode, the
    state first of the two downloads so a refused window costs nothing.
    """

    holders = [s for s in steps("detect") if step_secrets(s) & R2_STAGING]
    assert [s["name"] for s in holders] == [
        "Resolve the chain head and the automatic window",
        "Fetch and verify the predecessor's persistence state",
        "Fetch and verify the baseline months the window needs",
    ]
    head, state, baseline = holders
    assert step_scripts(head) == {"scripts/resolve_chain_head.py"}
    assert step_scripts(state) == {"scripts/fetch_green_state.py"}
    assert step_scripts(baseline) == {"scripts/baseline_v2_staging.py"}
    assert " fetch " in baseline["run"] and " upload" not in baseline["run"]
    assert head["if"] == "steps.inputs.outputs.chain == 'head'"
    assert state["if"] == (
        "steps.enumerated.outputs.deposit == 'true' && steps.window.outputs.from_run != ''"
    )


@pytest.mark.parametrize("script", ["fetch_green_state.py", "resolve_chain_head.py"])
def test_the_chain_steps_open_the_store_read_only_and_without_the_profile(script):
    """Lane steps: no local key (the revocation condition), no write path."""

    import ast

    source = (ROOT / "scripts" / script).read_text(encoding="utf-8")
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

    for job in doc()["jobs"]:
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
    assert 'emit(run_id="ci-%s" % os.environ["GITHUB_RUN_ID"])' in text
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
    inputs = steps("detect")[1]
    assert inputs["name"] == "Accept the dispatch inputs for the chosen chain mode"
    assert "uses" not in inputs and not step_secrets(inputs)
    for step in (inputs, step_named("detect", WINDOW)):
        assert "[A-Za-z0-9][A-Za-z0-9._-]{0,127}" in step["run"]
    code, _ = run_inline(inputs, CHAIN="from_run", FROM_RUN="../x",
                         START="2026-09-08", END="2026-09-10")
    assert code != 0
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
    window = names.index(WINDOW)
    assert window < names.index(PLAN) < names.index(
        "Fetch and verify the baseline months the window needs")
    assert "(b - a).days <= 16" in steps("detect")[window]["run"]
    assert '(b - a).days == 16' in steps("detect")[window]["run"]


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


@pytest.mark.parametrize("job", ["detect", "deposit", "heartbeat"])
def test_every_job_refuses_any_bucket_but_staging_first(job):
    first = steps(job)[0]
    assert first["name"] == "Fail closed unless the target is exactly the approved staging bucket"
    assert "araripe-v2-staging" in first["run"]
    assert not step_secrets(first)


# ─── the chain modes (PHASE_6H) ──────────────────────────────────────────────


def test_head_is_the_default_mode_and_no_date_is_required():
    inputs = doc()[True]["workflow_dispatch"]["inputs"]
    assert inputs["chain"]["type"] == "choice"
    assert inputs["chain"]["options"] == ["head", "from_run", "empty"]
    assert inputs["chain"]["default"] == "head"
    for name in ("from_run", "start", "end"):
        assert inputs[name]["required"] is False and inputs[name]["default"] == "", name


@pytest.mark.parametrize(
    "env, ok",
    [
        ({}, True),  # a scheduled event carries no inputs: head
        ({"CHAIN": "head"}, True),
        ({"CHAIN": "head", "START": "2026-09-08"}, False),
        ({"CHAIN": "head", "FROM_RUN": "ci-1"}, False),
        ({"CHAIN": "from_run", "FROM_RUN": "ci-1", "START": "2026-09-08", "END": "2026-09-10"}, True),
        ({"CHAIN": "from_run", "START": "2026-09-08", "END": "2026-09-10"}, False),
        ({"CHAIN": "from_run", "FROM_RUN": "ci-1", "START": "2026-09-08"}, False),
        ({"CHAIN": "empty", "START": "2026-09-08", "END": "2026-09-10"}, True),
        ({"CHAIN": "empty", "FROM_RUN": "ci-1", "START": "2026-09-08", "END": "2026-09-10"}, False),
        ({"CHAIN": "sideways"}, False),
    ],
)
def test_each_mode_accepts_exactly_its_own_inputs(env, ok):
    code, outputs = run_inline(step_named("detect", INPUTS), **env)
    assert (code == 0) is ok, (env, code)
    if ok:
        assert outputs["chain"] == (env.get("CHAIN") or "head")


def test_the_window_step_takes_the_head_or_the_inputs():
    window = step_named("detect", WINDOW)
    assert window["env"]["START"] == "${{ steps.head.outputs.start || steps.inputs.outputs.start }}"
    assert window["env"]["END"] == "${{ steps.head.outputs.end || steps.inputs.outputs.end }}"
    assert window["env"]["FROM_RUN"] == (
        "${{ steps.head.outputs.from_run || steps.inputs.outputs.from_run }}")
    assert window["env"]["NOTHING_TO_DO"] == "${{ steps.head.outputs.nothing_to_do }}"


@pytest.mark.parametrize(
    "start, end, full",
    [("2026-09-08", "2026-09-24", "true"), ("2026-09-23", "2026-09-27", "false")],
)
def test_the_window_step_marks_a_full_window(start, end, full):
    code, out = run_inline(step_named("detect", WINDOW), START=start, END=end,
                           FROM_RUN="ci-36456671793")
    assert code == 0
    assert out["proceed"] == "true" and out["full"] == full
    assert out["run_id"] == "ci-4242" and out["from_run"] == "ci-36456671793"
    assert out["start"] == start and out["end"] == end


def test_nothing_to_do_names_the_run_and_stops_before_earth_engine():
    code, out = run_inline(step_named("detect", WINDOW), NOTHING_TO_DO="true",
                           START="", END="", FROM_RUN="ci-36456671793")
    assert code == 0
    assert out == {"run_id": "ci-4242", "proceed": "false"}
    assert step_named("detect", PLAN)["if"] == "steps.window.outputs.proceed == 'true'"
    assert step_named("detect", ENUMERATED)["if"] == "steps.window.outputs.proceed == 'true'"


def test_a_window_of_seventeen_days_is_refused():
    code, _ = run_inline(step_named("detect", WINDOW), START="2026-09-08", END="2026-09-25")
    assert code != 0


def _screen(tmp_path, expected):
    (tmp_path / "replay").mkdir()
    (tmp_path / "replay" / "screen.json").write_text(
        '{"summary": {"expected_acquisitions": %d}, "acquisitions": []}' % expected)


@pytest.mark.parametrize(
    "expected, full, code, deposit",
    [(3, "false", 0, "true"), (3, "true", 0, "true"),
     (0, "false", 0, "false"), (0, "true", 1, None)],
)
def test_an_empty_window_deposits_nothing_unless_it_is_full(tmp_path, expected, full, code, deposit):
    _screen(tmp_path, expected)
    got, out = run_inline(step_named("detect", ENUMERATED), tmp=tmp_path, FULL=full)
    assert (got == 0) == (code == 0)
    assert out.get("deposit") == deposit
    # The count travels to the run summary (PHASE_6Y §2.4), zero included.
    assert out.get("expected") == (str(expected) if code == 0 else None)


def test_every_step_after_the_screen_needs_something_to_deposit():
    names = [s["name"] for s in steps("detect")]
    for step in steps("detect")[names.index(ENUMERATED) + 1:]:
        assert step["if"].startswith("steps.enumerated.outputs.deposit == 'true'"), step["name"]
    assert doc()["jobs"]["detect"]["outputs"]["deposit"] == "${{ steps.enumerated.outputs.deposit }}"
    assert doc()["jobs"]["deposit"]["if"].endswith("&& needs.detect.outputs.deposit == 'true'")


def test_the_head_is_resolved_with_the_runners_utc_date():
    run = step_named("detect", HEAD)["run"]
    assert 'python scripts/resolve_chain_head.py --today "$(date -u +%F)"' in run


def test_the_state_fetch_excludes_only_this_run_from_the_continuations():
    step = step_named("detect", "Fetch and verify the predecessor's persistence state")
    assert '--run "$RUN_ID"' in step["run"]
    assert step["env"]["RUN_ID"] == "${{ steps.window.outputs.run_id }}"


def test_the_lane_ceiling_is_the_chains():
    from src.publication import state_chain as sc

    assert sc.WINDOW_MAX_DAYS == 16
    assert "(b - a).days <= %d" % sc.WINDOW_MAX_DAYS in step_named("detect", WINDOW)["run"]


# ─── the heartbeat (GREEN_HEARTBEAT_CONTRACT_V1.md) ─────────────────────────

BEAT = "Record this attempt in the heartbeat"


def test_the_heartbeat_runs_after_every_outcome_and_only_where_the_lane_runs():
    """``always()``: a failed or cancelled detection skips ``deposit``, never the beat."""

    jobs = doc()["jobs"]
    condition = jobs["heartbeat"]["if"]
    assert condition.startswith("always() && ")
    assert condition[len("always() && "):] == jobs["detect"]["if"]


def test_the_heartbeat_holds_only_the_candidate_identity_in_one_step():
    holders = [s for s in steps("heartbeat") if step_secrets(s)]
    assert [s["name"] for s in holders] == [BEAT]
    assert step_secrets(holders[0]) == R2_STAGING
    assert step_scripts(holders[0]) == {"scripts/write_green_heartbeat.py"}


def test_the_heartbeat_reads_both_results_and_both_outputs():
    env = step_named("heartbeat", BEAT)["env"]
    assert env["DETECT_RESULT"] == "${{ needs.detect.result }}"
    assert env["DEPOSIT_RESULT"] == "${{ needs.deposit.result }}"
    assert env["PROCEED"] == "${{ needs.detect.outputs.proceed }}"
    assert env["WILL_DEPOSIT"] == "${{ needs.detect.outputs.deposit }}"
    outputs = doc()["jobs"]["detect"]["outputs"]
    assert outputs["proceed"] == "${{ steps.window.outputs.proceed }}"


def test_the_heartbeat_joins_no_queue():
    """A queued job can be cancelled by a newer one; a cancelled beat is lost.

    Two lanes finishing together are handled by the compare-and-swap and the
    commutative merge, not by serialising them.
    """

    assert "concurrency" not in doc()["jobs"]["heartbeat"]


def test_the_heartbeat_installs_the_conditional_write_floor():
    (install,) = [s for s in steps("heartbeat") if "pip install" in (s.get("run") or "")]
    assert "'botocore>=1.36.0'" in install["run"] and "'jsonschema>=4.23.0'" in install["run"]


# ─── the run summary (PHASE_6Y_2026-10-10.md §2.4) ───────────────────────────


def test_the_detection_hands_the_summary_what_the_run_tried():
    outputs = doc()["jobs"]["detect"]["outputs"]
    assert outputs["chain"] == "${{ steps.inputs.outputs.chain }}"
    assert outputs["start"] == "${{ steps.window.outputs.start }}"
    assert outputs["end"] == "${{ steps.window.outputs.end }}"
    assert outputs["expected"] == "${{ steps.enumerated.outputs.expected }}"
    env = step_named("heartbeat", BEAT)["env"]
    assert env["CHAIN"] == "${{ needs.detect.outputs.chain }}"
    assert env["WINDOW_START"] == "${{ needs.detect.outputs.start }}"
    assert env["WINDOW_END"] == "${{ needs.detect.outputs.end }}"
    assert env["FROM_RUN"] == "${{ needs.detect.outputs.from_run }}"
    assert env["EXPECTED"] == "${{ needs.detect.outputs.expected }}"


def test_the_status_of_every_product_stays_out_of_this_lane():
    """It reads three pointers, and this lane reads none (test above)."""

    text = "\n".join(executable_lines(WORKFLOW.read_text(encoding="utf-8")))
    assert "green_status" not in text
