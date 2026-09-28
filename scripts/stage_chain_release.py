#!/usr/bin/env python3
"""Check that the chain's public release is publishable — read-only, lane 2.

    python scripts/stage_chain_release.py [--json]

The chain-release half of ``stage_green_run.py``
(``docs/implementation/PHASE_6I_2026-09-28.md``).  It derives the chain from
the bucket exactly as the deposit lane does — ``state_chain.resolve_head``,
the one leaf the ``predecessor`` fields draw from ``CHAIN_ROOT`` — reads every
run of it with ``run_inputs.load_run``, composes the version-2 release and runs
``check_chain_release`` on it.  A chain that forks, a run that could not be
published alone, or members whose dates touch, all fail here, under the
smaller authority, before the promotion job starts.

It emits ``release_id``: the promotion job publishes the chain only if it
composes to **that** release, so a run deposited between the two jobs cannot
slip an unchecked member in.

The identity, and what it can do from here
------------------------------------------
``R2_STAGING_*`` through a ``ReadOnlyStore`` — no write is expressible — and
**without** the local profile fallback: a lane step, not a new local caller of
the key (``tests/test_profile_credential_fallback.py``).  It never imports
``config``.  It reads every object body of the chain, ~1.8 GB on 2026-09-28,
because checking each body against its run is what the gate is for.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import chain_release as cr  # noqa: E402
from src.publication import conditional_store as cs  # noqa: E402
from src.publication import state_chain as sc  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402
from src.publication.green_release import ReleaseBuildError  # noqa: E402
from src.publication.ledger_binding import ContractBindingError  # noqa: E402
from src.publication.run_inputs import ReadOnlyStore  # noqa: E402

ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"


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


def emit_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def stage(store) -> cr.StagedChain:
    head = sc.resolve_head(store)
    return cr.load_chain(store, head.path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json", action="store_true", help="print the release manifest instead"
    )
    args = parser.parse_args(argv)

    try:
        staged = stage(build_reader())
    except (
        Rejected, ReleaseBuildError, ContractBindingError, cs.ObjectStoreError,
        RuntimeError, ValueError,
    ) as exc:
        print(_annotate(f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        for finding in getattr(exc, "findings", ()):
            print(f"  {finding}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(staged.release, indent=2, sort_keys=True))
    else:
        print(cr.describe(staged))
        print("\nread-only — nothing was written and no pointer was read")
    emit_output("release_id", staged.release_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
