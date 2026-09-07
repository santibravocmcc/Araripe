#!/usr/bin/env python3
"""Check that one green run prefix is publishable — read-only, lane 2.

    python scripts/stage_green_run.py --run <run-id>

Package 2B.2C splits the operational publication path across the two green
lanes that ``docs/operations/GREEN_CONCURRENCY_LANES.md`` has kept apart since
Package 2B.0, and this script is the lane-2 half.

Why a separate script rather than a mode of ``publish_green_release.py``
-----------------------------------------------------------------------
Because the two halves hold **different identities**, and that separation is
the whole reason the lanes exist:

    "if the two lanes used the same key, any candidate run could move the
    pointer.  Separating them is what makes 'publish' and 'promote' two
    different authorities."   — docs/operations/PROMOTION_IDENTITY_SETUP.md

``publish_green_release.py`` reads ``R2_PROMOTION_*`` and may write; it is
forbidden from even *naming* the candidate identity, which
``tests/test_promotion_lane.py::test_the_candidate_identity_is_not_read_by_the_cli``
pins from the file.  This script is the mirror image: it reads
``R2_STAGING_*``, never names the promotion identity, and is handed a
``ReadOnlyStore`` so no write is expressible from it at all.

What it buys
------------
The lane-2 identity answers "is this run publishable?" — schema, ledger gate,
checksums, expected dates, product completeness, the whole
``check_green_release`` chain — **before** the lane-3 identity is exercised on
it.  A malformed or half-uploaded run prefix fails here, with the smaller
authority, and the promotion job never starts.

It writes nothing, moves no pointer, and contacts no bucket but
``araripe-v2-staging``; ``assert_staging_target`` refuses ``araripe-cogs`` by
name before a credential is read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication import run_inputs as ri  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402
from src.publication.green_release import ReleaseBuildError  # noqa: E402
from src.publication.ledger_binding import ContractBindingError  # noqa: E402

#: The candidate identity of lane 2.  The promotion identity is deliberately
#: not readable from this file.
ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"


def _annotate(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


def build_read_only_store() -> ri.ReadOnlyStore:
    """A candidate-identity store with no expressible write."""

    bucket = os.environ.get(BUCKET_VAR, cs.STAGING_BUCKET)
    endpoint = os.environ.get(ENDPOINT_VAR)
    client = cs.build_client(
        bucket,
        endpoint,
        {
            "access_key_id": os.environ.get(ACCESS_KEY_VAR, ""),
            "secret_access_key": os.environ.get(SECRET_KEY_VAR, ""),
            "region": os.environ.get("AWS_REGION", "auto"),
        },
    )
    return ri.ReadOnlyStore(client, bucket)


def emit_output(name: str, value: str) -> None:
    """Hand one value to the next job, when running inside Actions."""

    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run",
        required=True,
        help="the run id whose prefix runs/<run-id>/ holds run.json, "
        "ledger.json and the object bodies",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the release manifest instead"
    )
    args = parser.parse_args(argv)

    try:
        store = build_read_only_store()
        staged = ri.load_run(store, args.run)
    except (Rejected, ReleaseBuildError, ContractBindingError, cs.ObjectStoreError) as exc:
        print(_annotate(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        for finding in getattr(exc, "findings", ()):
            print(f"  {finding}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(staged.release, indent=2, sort_keys=True))
    else:
        print(ri.describe(staged))
        print("\nread-only — nothing was written and no pointer was read")
    emit_output("release_id", staged.release_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
