#!/usr/bin/env python3
"""Record one attempt of the green deposit lane in the heartbeat — lane only.

    python3 scripts/write_green_heartbeat.py

Run by the ``heartbeat`` job of ``.github/workflows/v2_green_deposit_lane.yml``
after ``detect`` and ``deposit``, whatever they did
(``docs/contracts/phase2b/GREEN_HEARTBEAT_CONTRACT_V1.md`` §2). Everything it
needs comes from the environment the job sets:

    DETECT_RESULT, DEPOSIT_RESULT   needs.<job>.result
    PROCEED, WILL_DEPOSIT           the detection's proceed and deposit outputs
    GITHUB_RUN_ID, GITHUB_REPOSITORY, GITHUB_SERVER_URL
    R2_STAGING_*, R2_STAGING_BUCKET, R2_ENDPOINT_URL, AWS_REGION

It writes one key, ``status/green/heartbeat.json``, by compare-and-swap. It
imports no ``config`` module (that one loads the production ``.env``), and it
does **not** opt into the local AWS profile: a beat comes from the lane, never
from an operator's shell.
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
        return 1
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
