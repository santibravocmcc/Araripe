"""The chained promotion's gate: promote exactly what a scheduled deposit deposited.

Decision D1 of ``docs/operations/PHASE_6_CUTOVER_RUNSHEET.md`` (PHASE_6ZB).
The plausible error is a promotion that runs when the round deposited
nothing — and ``workflow_run`` makes it easy, because such a round concludes
``success``. The fixtures under ``tests/fixtures/deposit_lane_jobs/`` are the
real lane's answers from ``/actions/runs/<id>/attempts/1/jobs``, trimmed to the
fields the gate reads; the run id is the file name.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "chained_promotion_gate.py"
FIXTURES = ROOT / "tests" / "fixtures" / "deposit_lane_jobs"
REPOSITORY = "santibravocmcc/Araripe"


def _load():
    spec = importlib.util.spec_from_file_location("chained_promotion_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def jobs_of(run_id: str) -> dict:
    return json.loads((FIXTURES / f"{run_id}.json").read_text(encoding="utf-8"))


def trigger(run_id: str, **changes) -> "gate.Trigger":
    values = dict(run_id=run_id, run_attempt="1", event="schedule", branch="main",
                  repository=REPOSITORY, path=gate.DEPOSIT_LANE)
    values.update(changes)
    return gate.Trigger(**values)


def decide(run_id: str, document=None, **changes):
    return gate.decide(trigger(run_id, **changes), document or jobs_of(run_id), REPOSITORY)


# ── the measured runs ────────────────────────────────────────────────────────


@pytest.mark.parametrize("run_id, conclusion, promote", [
    ("37020588408", "success", True),
    ("37686447368", "success", True),
    ("37021850688", "skipped", False),  # no acquisition
    ("37688510058", "skipped", False),
    ("37659861235", "skipped", False),  # the detection failed
])
def test_the_deposit_jobs_conclusion_decides(run_id, conclusion, promote):
    (deposit,) = [j for j in jobs_of(run_id)["jobs"] if j["name"] == "deposit"]
    assert deposit["conclusion"] == conclusion
    assert decide(run_id).promote is promote


def test_runs_that_deposited_nothing_still_concluded_success():
    """Why the workflow_run conclusion cannot be the signal: measured, not
    argued. Every job of these two runs that ran, succeeded."""

    for run_id in ("37021850688", "37688510058"):
        conclusions = {j["name"]: j["conclusion"] for j in jobs_of(run_id)["jobs"]}
        assert conclusions == {"detect": "success", "deposit": "skipped", "heartbeat": "success"}


def test_a_failed_deposit_is_not_promoted():
    document = copy.deepcopy(jobs_of("37020588408"))
    for job in document["jobs"]:
        if job["name"] == "deposit":
            job["conclusion"] = "failure"
    decision = decide("37020588408", document)
    assert not decision.promote and "'failure'" in decision.reason


def test_a_deposited_run_whose_heartbeat_failed_is_still_promoted():
    """The run concludes failure, and its prefix is complete: the deposit job
    succeeded only after stage_green_run.py re-read it."""

    document = copy.deepcopy(jobs_of("37020588408"))
    for job in document["jobs"]:
        if job["name"] == "heartbeat":
            job["conclusion"] = "failure"
    assert decide("37020588408", document).promote


# ── who may be chained ───────────────────────────────────────────────────────


def test_a_dispatched_deposit_is_promoted_by_hand():
    decision = decide("37020588408", event="workflow_dispatch")
    assert not decision.promote and "by hand" in decision.reason


@pytest.mark.parametrize("changes", [
    {"branch": "claude/x"}, {"repository": "someone/Araripe"},
])
def test_only_mains_runs_of_this_repository_are_chained(changes):
    assert not decide("37020588408", **changes).promote


def test_another_workflow_of_the_same_name_is_refused():
    with pytest.raises(gate.GateError, match="not .github/workflows/v2_green_deposit_lane.yml"):
        decide("37020588408", path=".github/workflows/other.yml")


# ── an answer the gate cannot read fails closed ──────────────────────────────


def test_the_lane_before_the_heartbeat_is_not_recognized():
    """Run 36465153281 had two jobs; a gate that guessed would be guessing."""

    with pytest.raises(gate.GateError, match="lane changed under this gate"):
        decide("36465153281")


def test_a_job_of_another_attempt_is_refused():
    with pytest.raises(gate.GateError, match="attempt"):
        decide("37020588408", run_attempt="2")


def test_a_job_of_another_run_is_refused():
    document = copy.deepcopy(jobs_of("37020588408"))
    document["jobs"][0]["run_id"] = 1
    with pytest.raises(gate.GateError, match="belongs to run 1"):
        decide("37020588408", document)


def test_an_unfinished_job_is_refused():
    document = copy.deepcopy(jobs_of("37020588408"))
    document["jobs"][2]["status"] = "in_progress"
    with pytest.raises(gate.GateError, match="not completed"):
        decide("37020588408", document)


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(total_count=4),
    lambda d: d.pop("jobs"),
    lambda d: d["jobs"].append(dict(d["jobs"][0], name="deposit")),
])
def test_an_incomplete_or_malformed_list_is_refused(mutate):
    document = copy.deepcopy(jobs_of("37020588408"))
    mutate(document)
    with pytest.raises(gate.GateError):
        decide("37020588408", document)


# ── the command line ─────────────────────────────────────────────────────────


def _environment(monkeypatch, tmp_path, run_id="37020588408", **changes):
    values = {
        "TRIGGER_RUN_ID": run_id, "TRIGGER_RUN_ATTEMPT": "1", "TRIGGER_EVENT": "schedule",
        "TRIGGER_BRANCH": "main", "TRIGGER_REPOSITORY": REPOSITORY,
        "TRIGGER_PATH": gate.DEPOSIT_LANE, "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    values.update(changes)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _outputs(tmp_path):
    path = tmp_path / "output"
    return dict(line.split("=", 1) for line in path.read_text().splitlines()) if path.exists() else {}


@pytest.mark.parametrize("run_id, promote", [("37020588408", "true"), ("37021850688", "false")])
def test_the_command_writes_the_decision_and_the_summary(monkeypatch, tmp_path, run_id, promote):
    _environment(monkeypatch, tmp_path, run_id)
    assert gate.main(["--jobs", str(FIXTURES / f"{run_id}.json")]) == 0
    assert _outputs(tmp_path) == {"promote": promote, "source": "chain", "run_id": ""}
    assert "Chained promotion" in (tmp_path / "summary").read_text()


def test_a_missing_trigger_field_fails_and_writes_no_decision(monkeypatch, tmp_path):
    _environment(monkeypatch, tmp_path)
    monkeypatch.delenv("TRIGGER_PATH")
    assert gate.main(["--jobs", str(FIXTURES / "37020588408.json")]) == 1
    assert _outputs(tmp_path) == {}


def test_an_unreadable_answer_fails_and_writes_no_decision(monkeypatch, tmp_path):
    _environment(monkeypatch, tmp_path)
    bad = tmp_path / "jobs.json"
    bad.write_text("<html>rate limited</html>")
    assert gate.main(["--jobs", str(bad)]) == 1
    assert _outputs(tmp_path) == {}


def test_the_gate_imports_only_the_standard_library_and_calls_no_network():
    """The workflow fetches; the script decides. No client, no credential."""

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "argparse", "json", "os", "sys", "dataclasses",
                        "pathlib", "typing"}
