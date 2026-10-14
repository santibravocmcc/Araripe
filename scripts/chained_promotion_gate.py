#!/usr/bin/env python3
"""Decide whether a finished deposit-lane run is promoted now — Phase 6, D1.

    gh api "repos/<repo>/actions/runs/<id>/attempts/<n>/jobs?per_page=100" > jobs.json
    python3 scripts/chained_promotion_gate.py --jobs jobs.json

``v2_operational_publish.yml`` runs on ``workflow_run`` when
``v2_green_deposit_lane.yml`` completes (the owner's decision D1 of
``PHASE_6_CUTOVER_RUNSHEET.md``, 2026-10-13). ``workflow_run`` hands over the
run's **conclusion**, and the conclusion is not the answer: a run whose window
held no acquisition, or whose head already covered every date, concludes
``success`` and deposits nothing. Measured on the real lane, from
``/actions/runs/<id>/attempts/1/jobs``:

    37021850688  success  detect success, deposit skipped, heartbeat success  (no acquisition)
    37688510058  success  detect success, deposit skipped, heartbeat success
    37020588408  success  detect success, deposit success, heartbeat success  (deposited)
    37659861235  failure  detect failure, deposit skipped, heartbeat success
    36465153281  failure  detect success, deposit failure

The **deposit job's** conclusion is the answer. That job runs only when the
detection found something to deposit (``needs.detect.outputs.deposit``), and it
succeeds only after ``stage_green_run.py`` re-read the prefix it wrote — so
``success`` there means "this attempt deposited a complete run", and nothing
else does. The workflow conclusion is not even consulted: a deposited run whose
heartbeat failed concludes ``failure`` and still has a run to promote.

Promote only when all of these hold:

* the run is the deposit lane's (by path, not only by the name the trigger
  matched), of this repository, on ``main``;
* it was started by the **schedule**. A dispatched deposit is promoted by hand,
  as the runsheet's A9 does: an operator who chose ``from_run`` or ``empty``
  made a decision the routine must not extend;
* its jobs are exactly ``detect``, ``deposit``, ``heartbeat``, all completed,
  of the run and attempt that triggered — anything else means the lane changed
  under this gate, and the gate fails closed (red) instead of guessing;
* ``deposit`` concluded ``success``.

Writes ``promote``, ``source`` (``chain``) and ``run_id`` (empty: a chain is
derived, never named) to ``GITHUB_OUTPUT``, and the reason to the job summary.
Exit 1 only when the answer cannot be read. No network, no store, no
credential: the workflow fetches, this decides.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DEPOSIT_LANE = ".github/workflows/v2_green_deposit_lane.yml"
JOBS = ("detect", "deposit", "heartbeat")
BRANCH = "main"


class GateError(Exception):
    """The jobs list or the trigger cannot be read as the deposit lane's."""


@dataclass(frozen=True)
class Trigger:
    """The ``github.event.workflow_run`` fields the decision reads."""

    run_id: str
    run_attempt: str
    event: str
    branch: str
    repository: str
    path: str


@dataclass(frozen=True)
class Decision:
    promote: bool
    reason: str


def decide(trigger: Trigger, jobs_document: Mapping[str, Any], repository: str) -> Decision:
    if trigger.path != DEPOSIT_LANE:
        raise GateError(f"the triggering run is {trigger.path!r}, not {DEPOSIT_LANE}")
    if trigger.repository != repository or trigger.branch != BRANCH:
        return Decision(False, f"the deposit ran on {trigger.repository}@{trigger.branch}, "
                               f"not {repository}@{BRANCH}; nothing is promoted from it")
    if trigger.event != "schedule":
        return Decision(False, f"the deposit was started by {trigger.event!r}, not the schedule; "
                               "a dispatched deposit is promoted by hand (runsheet A9)")

    jobs = jobs_document.get("jobs")
    if not isinstance(jobs, list) or jobs_document.get("total_count") != len(jobs):
        raise GateError("the jobs list is not one complete page "
                        f"(total_count {jobs_document.get('total_count')!r})")
    names = sorted(str(job.get("name")) for job in jobs)
    if names != sorted(JOBS):
        raise GateError(f"the run's jobs are {names}, not {sorted(JOBS)}: the lane "
                        "changed under this gate")
    for job in jobs:
        if (str(job.get("run_id")), str(job.get("run_attempt"))) != (trigger.run_id, trigger.run_attempt):
            raise GateError(f"job {job.get('name')} belongs to run {job.get('run_id')} attempt "
                            f"{job.get('run_attempt')}, not {trigger.run_id} attempt {trigger.run_attempt}")
        if job.get("status") != "completed":
            raise GateError(f"job {job.get('name')} is {job.get('status')!r}, not completed")

    (deposit,) = [job for job in jobs if job["name"] == "deposit"]
    conclusion = deposit.get("conclusion")
    if conclusion == "success":
        return Decision(True, f"run {trigger.run_id} attempt {trigger.run_attempt} deposited "
                              "and re-read its prefix; the chain is promoted")
    if conclusion == "skipped":
        return Decision(False, f"run {trigger.run_id} deposited nothing (deposit skipped: no "
                               "acquisition, nothing to do, or a failed detection); the pointer stays")
    return Decision(False, f"run {trigger.run_id}'s deposit concluded {conclusion!r}; the deposit "
                           "lane is red on its own, and nothing is promoted from it")


def trigger_from_environment() -> Trigger:
    names = {
        "run_id": "TRIGGER_RUN_ID",
        "run_attempt": "TRIGGER_RUN_ATTEMPT",
        "event": "TRIGGER_EVENT",
        "branch": "TRIGGER_BRANCH",
        "repository": "TRIGGER_REPOSITORY",
        "path": "TRIGGER_PATH",
    }
    missing = [env for env in names.values() if not os.environ.get(env)]
    if missing:
        raise GateError(f"missing {', '.join(missing)}")
    return Trigger(**{field: os.environ[env] for field, env in names.items()})


def _say(message: str, error: bool = False) -> None:
    inside = bool(os.environ.get("GITHUB_ACTIONS"))
    if error:
        print(f"::error::{message}" if inside else f"erro: {message}", file=sys.stderr)
    else:
        print(message)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", type=Path, required=True,
                        help="the /actions/runs/<id>/attempts/<n>/jobs answer, as JSON")
    args = parser.parse_args(argv)
    try:
        trigger = trigger_from_environment()
        try:
            document = json.loads(args.jobs.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GateError(f"{args.jobs} cannot be read as JSON: {exc}") from exc
        decision = decide(trigger, document, os.environ.get("GITHUB_REPOSITORY", ""))
    except GateError as exc:
        _say(f"the chained promotion cannot decide: {exc}", error=True)
        return 1
    _say(decision.reason)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"promote={'true' if decision.promote else 'false'}\n")
            handle.write("source=chain\n")
            handle.write("run_id=\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            verdict = "promoting the chain" if decision.promote else "not promoting"
            handle.write(f"## Chained promotion: {verdict}\n\n{decision.reason}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
