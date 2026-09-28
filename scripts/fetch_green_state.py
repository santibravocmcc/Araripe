#!/usr/bin/env python3
"""Fetch the persistence state a chained green run starts from, verified.

    python scripts/fetch_green_state.py --from-run rep-2026-08-30-v3 \
        --start 2026-08-31 --out-dir "$RUNNER_TEMP/replay"

writes ``<out-dir>/persistence_state.geojson`` and ``<out-dir>/predecessor.json``
— or nothing, and exits 1.

``docs/implementation/PHASE_6G_2026-09-28.md`` is the decision.  In order:

1. read and validate ``runs/<from-run>/run.json`` and its ledger (two small
   documents; the ledger through the Package 2B.2A gate);
2. refuse any ``--start`` but the day after the last date that ledger covers
   (§4) — before a byte of the state is downloaded;
3. read ``runs/<from-run>/persistence_state.geojson`` and refuse it if it is
   absent, or its length or sha256 differ from what the ``run.json`` declares;
4. only then write both files, the state under a temporary name first.

The identity, and what it can do from here
------------------------------------------
``R2_STAGING_*`` — the candidate identity, which can write.  This script opens
it through ``ReadOnlyStore``, so a write here raises instead of reaching the
bucket, and it does **not** opt into the local profile fallback: it is a lane
step, and a new local caller would move the revocation condition
(``config/phase6_owner_decisions_v1.json``, ``revocation_ordering``).  It never
imports ``config`` — ``config.settings`` loads the production ``.env`` at
import — and ``tests/test_assemble_green_run.py`` keeps it that way.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication import state_chain as sc  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402
from src.publication.ledger_binding import ContractBindingError  # noqa: E402
from src.publication.run_inputs import ReadOnlyStore  # noqa: E402

ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"

PREDECESSOR_NAME = "predecessor.json"


def _annotate(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


def build_reader() -> ReadOnlyStore:
    """The candidate identity, unable to write through this object."""

    bucket = os.environ.get(BUCKET_VAR, cs.STAGING_BUCKET)
    client = cs.build_client(
        bucket,
        os.environ.get(ENDPOINT_VAR),
        {
            "access_key_id": os.environ.get(ACCESS_KEY_VAR, ""),
            "secret_access_key": os.environ.get(SECRET_KEY_VAR, ""),
            "region": os.environ.get("AWS_REGION", "auto"),
        },
    )
    return ReadOnlyStore(client, bucket)


def fetch(store, from_run: str, start: str, out_dir: Path) -> sc.Predecessor:
    predecessor = sc.read_predecessor(store, from_run)
    sc.check_window(predecessor, start)
    body = sc.fetch_state(store, predecessor)

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / sc.STATE_PATH
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(body)
    partial.replace(target)
    (out_dir / PREDECESSOR_NAME).write_text(
        json.dumps(predecessor.link(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return predecessor


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-run", required=True, help="the run this one continues")
    parser.add_argument("--start", required=True, help="first UTC date of the new window")
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    for name in (sc.STATE_PATH, PREDECESSOR_NAME):
        if (args.out_dir / name).exists():
            print(_annotate(f"{args.out_dir / name} already exists; a chained run "
                            "starts from exactly one fetched state"), file=sys.stderr)
            return 1

    try:
        predecessor = fetch(build_reader(), args.from_run, args.start, args.out_dir)
    except (Rejected, ContractBindingError, cs.ObjectStoreError, RuntimeError, ValueError) as exc:
        print(_annotate(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        for finding in getattr(exc, "findings", ()):
            print(f"  {finding}", file=sys.stderr)
        return 1

    print(f"predecessor : {predecessor.run_id}")
    print(f"covered to  : {predecessor.last_observed_on}; this window starts {args.start}")
    print(f"state       : {predecessor.persistence_state_bytes} bytes, sha256 "
          f"{predecessor.persistence_state_sha256} — verified against its run.json")
    print("read-only — nothing was written to the bucket and no pointer was read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
