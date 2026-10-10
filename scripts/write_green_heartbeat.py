#!/usr/bin/env python3
"""Record one attempt of the green deposit lane in the heartbeat — lane only.

    python3 scripts/write_green_heartbeat.py

Run by the ``heartbeat`` job of ``.github/workflows/v2_green_deposit_lane.yml``
after ``detect`` and ``deposit``, whatever they did
(``docs/contracts/phase2b/GREEN_HEARTBEAT_CONTRACT_V1.md`` §2). Everything it
needs comes from the environment the job sets:

    DETECT_RESULT, DEPOSIT_RESULT   needs.<job>.result
    PROCEED, WILL_DEPOSIT           the detection's proceed and deposit outputs
    CHAIN, WINDOW_START, WINDOW_END, FROM_RUN, EXPECTED
                                    what the run tried, for the run summary only
    GITHUB_RUN_ID, GITHUB_REPOSITORY, GITHUB_SERVER_URL
    R2_STAGING_*, R2_STAGING_BUCKET, R2_ENDPOINT_URL, AWS_REGION

It writes one key, ``status/green/heartbeat.json``, by compare-and-swap. It
imports no ``config`` module (that one loads the production ``.env``), and it
does **not** opt into the local AWS profile: a beat comes from the lane, never
from an operator's shell.

The run summary (``docs/implementation/PHASE_6Y_2026-10-10.md`` §2.4)
--------------------------------------------------------------------
Inside Actions it also appends to ``GITHUB_STEP_SUMMARY`` what the run tried
and what happened — mode, window, acquisitions expected, the run it continued,
the outcome and stage, and whether the beat was recorded — written whether or
not the beat is. The window lives here and **not** in the heartbeat: the beat
names none so it cannot be read as "data up to" (contract §4.2), and the
summary is the page its ``run_url`` opens.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication import heartbeat as hb  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402

ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"


def _annotate(kind: str, message: str) -> None:
    prefix = f"::{kind}::" if os.environ.get("GITHUB_ACTIONS") else f"{kind}: "
    print(prefix + message, file=sys.stderr if kind == "error" else sys.stdout)


#: How the run summary says each outcome — the contract's table (§3), in words.
SAID = {
    hb.DEPOSITED: "deposited a run prefix and re-validated it",
    hb.NOTHING_TO_DO: "nothing to do: the chain head already covers every date the settle rule allows",
    hb.NO_ACQUISITION: "the window held no acquisition; nothing deposited, the head is unchanged",
    hb.FAILED: "failed",
    hb.CANCELLED: "was cancelled",
}


def run_summary(env, outcome: str, stage: str | None, beat: str) -> str:
    """The run summary in Markdown — what the run tried, and what happened.

    Every value comes from the job's environment as the workflow set it; an
    empty one is shown as "—", because a run that stopped early never computed
    it (a nothing-to-do run has no window).
    """

    def value(name: str) -> str:
        return env.get(name) or "—"

    run_id = f"ci-{env.get('GITHUB_RUN_ID', '')}"
    start, end = env.get("WINDOW_START", ""), env.get("WINDOW_END", "")
    window = f"{start} .. {end} (end exclusive)" if start and end else "—"
    lines = [
        f"## Green deposit lane — {run_id}",
        "",
        "| | |",
        "| --- | --- |",
        f"| outcome | **{outcome}**{' at ' + stage if stage else ''} — {SAID[outcome]} |",
        f"| chain mode | {value('CHAIN')} |",
        f"| window | {window} |",
        f"| continues | {value('FROM_RUN') if start else '—'} |",
        f"| acquisitions expected | {value('EXPECTED')} |",
        f"| deposited | {'`runs/' + run_id + '/`' if outcome == hb.DEPOSITED else '—'} |",
        f"| heartbeat | {beat} |",
        "",
        "A deposit is not a publication: the page shows these dates after the "
        "operational publication promotes them. The status of every product is "
        "`v2_green_status.yml`.",
    ]
    return "\n".join(lines) + "\n"


def write_summary(env, text: str) -> None:
    path = env.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)


def main(env=None) -> int:
    env = os.environ if env is None else env
    outcome, stage = hb.classify_outcome(
        detect=env.get("DETECT_RESULT", ""),
        deposit=env.get("DEPOSIT_RESULT", ""),
        proceed=env.get("PROCEED", ""),
        will_deposit=env.get("WILL_DEPOSIT", ""),
    )
    run_number = env.get("GITHUB_RUN_ID", "")
    repository = env.get("GITHUB_REPOSITORY", "")
    try:
        new = hb.attempt(
            outcome, stage, run_number=run_number, repository=repository,
            server=env.get("GITHUB_SERVER_URL") or "https://github.com",
        )
        client = cs.build_client(
            env.get(BUCKET_VAR, ""),
            env.get(ENDPOINT_VAR),
            {
                "access_key_id": env.get(ACCESS_KEY_VAR, ""),
                "secret_access_key": env.get(SECRET_KEY_VAR, ""),
                "region": env.get("AWS_REGION", "auto"),
            },
        )
        recorded = hb.record(cs.ConditionalStore(client, env.get(BUCKET_VAR, "")), new)
    except (cs.ObjectStoreError, Rejected) as exc:
        _annotate("error", f"the heartbeat was not recorded: {exc}")
        write_summary(env, run_summary(env, outcome, stage, f"**not recorded**: {exc}"))
        return 1
    write_summary(env, run_summary(
        env, outcome, stage, f"recorded ({recorded.result} after {recorded.tries} read(s))"))
    latest = recorded.document["latest"]
    success = recorded.document["last_success"]
    print(
        f"heartbeat {recorded.result} after {recorded.tries} read(s): this attempt "
        f"{new['outcome']}{' at ' + new['stage'] if new['stage'] else ''}; latest "
        f"{latest['run_id']} {latest['outcome']} {latest['finished_utc']}; last "
        "success "
        + (f"{success['run_id']} {success['outcome']} {success['finished_utc']}"
           if success else "none yet")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
