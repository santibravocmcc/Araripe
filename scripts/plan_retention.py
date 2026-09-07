#!/usr/bin/env python3
"""Print the green retention dry-run — read-only, and it cannot delete.

    python scripts/plan_retention.py
    python scripts/plan_retention.py --json > plan.json

Package 2B.3: *define conservative lifecycle and rollback retention; run
deletion policies in reviewed dry-run form first.*  This is the reviewed
dry-run.  It lists ``araripe-v2-staging``, reads the green pointer, recomputes
which release each run prefix would produce, and classifies every object.

**It has no delete path, and neither does anything it imports.**
``ConditionalStore`` exposes one read and two conditional writes and nothing
else; this script is handed a ``ReadOnlyStore`` whose write methods raise.
Removing an object is a separate, approved change that does not exist yet —
see ``docs/operations/GREEN_RETENTION_AND_MIGRATION.md``.

It uses the **candidate** identity (``R2_STAGING_*``), which is the smaller of
the two, because planning is a read.  The promotion identity is deliberately
not readable from this file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication import delivery_boundary as db  # noqa: E402
from src.publication import retention  # noqa: E402
from src.publication import run_inputs as ri  # noqa: E402

#: The candidate identity of lane 2.  The promotion identity is deliberately
#: not named in this file: a plan is a read, and reading needs the smaller key.
ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"


def build_read_only_store():
    bucket = os.environ.get(BUCKET_VAR, cs.STAGING_BUCKET)
    endpoint = os.environ.get(ENDPOINT_VAR, cs.STAGING_ENDPOINT)
    client = cs.build_client(
        bucket,
        endpoint,
        {
            "access_key_id": os.environ.get(ACCESS_KEY_VAR, ""),
            "secret_access_key": os.environ.get(SECRET_KEY_VAR, ""),
            "region": os.environ.get("AWS_REGION", "auto"),
        },
    )
    return client, ri.ReadOnlyStore(client, bucket)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true",
                        help="print the machine-readable plan instead")
    parser.add_argument("--as-of", default=None,
                        help="evaluate horizons at this UTC instant "
                        "(YYYY-MM-DDTHH:MM:SSZ); defaults to now")
    parser.add_argument("--run-horizon-days", type=int,
                        default=retention.DEFAULT_RUN_HORIZON_DAYS)
    parser.add_argument("--verification-horizon-days", type=int,
                        default=retention.DEFAULT_VERIFICATION_HORIZON_DAYS)
    parser.add_argument("--phase-closed", action="store_true",
                        help="Phases 2B-5 are over, so probe objects are no "
                        "longer live evidence")
    parser.add_argument(
        "--accept-run-manifest-loss", action="store_true",
        help="accept that removing a run prefix loses run.json, which no "
        "release republishes; without this a ripe run prefix stays in review",
    )
    args = parser.parse_args(argv)

    as_of = (
        datetime.strptime(args.as_of, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if args.as_of
        else datetime.now(timezone.utc)
    )

    try:
        client, store = build_read_only_store()
        inventory = retention.list_inventory(client, store.bucket)
        stored_pointer = store.get(db.POINTER_KEY)
        pointer = json.loads(stored_pointer.body) if stored_pointer else None
        runs = retention.resolve_run_links(store, inventory)
    except cs.ObjectStoreError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    plan = retention.build_plan(
        inventory,
        pointer=pointer,
        runs=runs,
        as_of=as_of,
        run_horizon_days=args.run_horizon_days,
        verification_horizon_days=args.verification_horizon_days,
        phase_open=not args.phase_closed,
        accept_run_manifest_loss=args.accept_run_manifest_loss,
    )

    if args.json:
        print(json.dumps(retention.plan_document(plan), indent=2, sort_keys=True))
    else:
        print(f"bucket: {store.bucket}")
        print(retention.describe(plan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
