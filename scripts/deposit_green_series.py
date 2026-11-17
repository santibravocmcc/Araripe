#!/usr/bin/env python3
"""Deposit one run's series rows beside it — ``series/<run-id>/`` (D4B).

    python scripts/deposit_green_series.py --run <run-id> \
        --rows <dir>/timeseries_rows.json --ledger <dir>/ledger.json

The deposit job runs it after ``stage_green_run.py`` has re-read and validated
``runs/<run-id>/``; the reconstruction runs it once per rebuilt run.  It checks
that the document names the run's own ``ledger_id`` and ``run_manifest_id``,
then writes the file's bytes with ``put_if_absent``: a re-run of the deposit
job with the same artifact is ``unchanged``, and different bytes at the same
key are an ``ImmutableObjectConflict``, never an overwrite.

The key is never under ``runs/`` (``src/timeseries/green_series.py`` says
why), and nothing else is written.  It holds the candidate identity, contacts
no bucket but ``araripe-v2-staging`` (``assert_staging_target``), and imports
no ``config`` module (``tests/test_assemble_green_run.py::GREEN_SCRIPTS``).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.timeseries import green_series as gs  # noqa: E402

ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"
CONTENT_TYPE = "application/json"


def _annotate(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


def build_writer() -> cs.ConditionalStore:
    """The candidate identity, as ``assemble_green_run.py apply`` holds it."""

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
    return cs.ConditionalStore(client, bucket)


def deposit(store: cs.ConditionalStore, run_id: str, rows: Path, ledger: Path):
    body = Path(rows).read_bytes()
    document = json.loads(body)
    gs.check_rows_document(document, ledger=json.loads(Path(ledger).read_text(encoding="utf-8")))
    key = gs.series_key(run_id)
    return key, store.put_if_absent(key, body, CONTENT_TYPE)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True)
    parser.add_argument("--rows", required=True)
    parser.add_argument("--ledger", required=True)
    args = parser.parse_args(argv)
    try:
        key, outcome = deposit(build_writer(), args.run, Path(args.rows), Path(args.ledger))
    except (gs.SeriesRejected, cs.ObjectStoreError, OSError, ValueError) as exc:
        print(_annotate(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1
    print(f"{outcome.result:<10} {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
