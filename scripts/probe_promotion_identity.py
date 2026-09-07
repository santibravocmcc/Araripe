#!/usr/bin/env python3
"""Prove the green promotion identity works, and that R2 honours preconditions.

Package 2B.2B built publication on two R2 preconditions and proved them against
an in-memory store, because the ``v2-staging`` Environment admits only ``main``
and no feature branch could reach a credential.  This script is the other half:
the first measurement against real R2.

It answers four questions that only a real call can answer:

1. **Is the credential a working R2 S3 key pair?**  A very plausible mistake is
   copying an R2 token's *Bearer token value* instead of its **Access Key ID**
   and **Secret Access Key**, which the creation page shows together.
2. **Is it scoped to one bucket?**  The production bucket must be **denied**.
   An over-scoped token would otherwise work perfectly and quietly destroy the
   isolation the whole phase rests on.
3. **Does it have write permission**, not only read?
4. **Does R2 really enforce ``If-None-Match`` and ``If-Match``?**  Until now
   that was documentation
   (https://developers.cloudflare.com/r2/api/s3/extensions/), not a
   measurement.  If R2 ignored them, immutable releases and pointer
   compare-and-swap would both be silently unenforced in production.

It runs the **real** ``src/publication/conditional_store.py`` rather than a
reimplementation, so what passes here is the code the publication path uses.

Every object is written under one immutable per-run prefix and nothing is
deleted, matching the candidate lane's discipline.  No secret is printed: only
whether a call succeeded, and error *codes* rather than messages that could
echo a credential.

Usage (needs R2_PROMOTION_ACCESS_KEY_ID, R2_PROMOTION_SECRET_ACCESS_KEY,
R2_STAGING_BUCKET, R2_ENDPOINT_URL in the environment):

    python scripts/probe_promotion_identity.py --run-id local-$(date +%s)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication.conditional_store import (  # noqa: E402
    ConditionalStore,
    ImmutableObjectConflict,
    ObjectStoreError,
    PreconditionFailed,
)

CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def probe_production_is_denied(credentials: dict[str, str], endpoint: str) -> None:
    """Require AccessDenied on the production bucket.

    This is the one place that deliberately addresses ``araripe-cogs``, and it
    does so with a single read-only ``list_objects_v2(MaxKeys=1)`` whose *whole
    purpose* is to prove the call is refused.  ``v2_candidate_replay.yml``
    already does exactly this for the candidate identity, reviewed and merged
    in Package 2B.0.  ``conditional_store.build_client`` refuses that bucket by
    name, so a raw client is used here on purpose: the property under test is
    the **credential's** scope, not our own guard.
    """

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=credentials["access_key_id"],
        aws_secret_access_key=credentials["secret_access_key"],
        region_name=credentials.get("region") or "auto",
    )
    try:
        client.list_objects_v2(Bucket=cs.PRODUCTION_BUCKET, MaxKeys=1)
    except Exception as exc:  # noqa: BLE001 - the refusal is the pass condition
        code = cs.error_code(exc) or type(exc).__name__
        denied = code in {"AccessDenied", "403", "InvalidAccessKeyId", "NoSuchBucket"}
        record(
            f"{cs.PRODUCTION_BUCKET} is refused for this identity",
            denied,
            f"code {code}",
        )
        return
    record(
        f"{cs.PRODUCTION_BUCKET} is refused for this identity",
        False,
        "THE LIST SUCCEEDED — the token is over-scoped and isolation is broken. "
        "Revoke it and create one restricted to " + cs.STAGING_BUCKET,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True,
                        help="unique token for this run's immutable prefix")
    args = parser.parse_args(argv)

    bucket = os.environ.get("R2_STAGING_BUCKET", "")
    endpoint = os.environ.get("R2_ENDPOINT_URL", "")
    credentials = {
        "access_key_id": os.environ.get("R2_PROMOTION_ACCESS_KEY_ID", ""),
        "secret_access_key": os.environ.get("R2_PROMOTION_SECRET_ACCESS_KEY", ""),
        "region": os.environ.get("AWS_REGION", "auto"),
    }

    print("green promotion identity probe")
    print(f"  bucket   : {bucket}")
    print(f"  endpoint : {endpoint}")
    print(f"  key id   : {'set' if credentials['access_key_id'] else 'MISSING'}")
    print(f"  secret   : {'set' if credentials['secret_access_key'] else 'MISSING'}")
    print()

    try:
        client = cs.build_client(bucket, endpoint, credentials)
    except ObjectStoreError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    record("target guard and conditional-write support", True,
           "bucket, endpoint and botocore accepted")

    store = ConditionalStore(client, bucket)
    prefix = f"promotion-identity-probe/run-{args.run_id}"

    # 1. Read.
    try:
        client.list_objects_v2(Bucket=bucket, MaxKeys=1)
        record(f"list {bucket}", True)
    except Exception as exc:  # noqa: BLE001
        record(f"list {bucket}", False, f"code {cs.error_code(exc) or exc}")
        return report()

    # 2. Isolation.
    probe_production_is_denied(credentials, endpoint)

    # 3. Write-once, and the 412 path that makes republication idempotent.
    immutable = f"{prefix}/immutable.json"
    body = f'{{"probe":"{args.run_id}","kind":"immutable"}}'.encode()
    try:
        first = store.put_if_absent(immutable, body, "application/json")
        record("write a new object with If-None-Match: *", first.result == "created",
               f"result {first.result}")
    except ObjectStoreError as exc:
        record("write a new object with If-None-Match: *", False, str(exc)[:120])
        return report()

    try:
        again = store.put_if_absent(immutable, body, "application/json")
        record("same bytes again are an idempotent no-op",
               again.result == "unchanged", f"result {again.result}")
    except ObjectStoreError as exc:
        record("same bytes again are an idempotent no-op", False, str(exc)[:120])

    try:
        store.put_if_absent(immutable, body + b" ", "application/json")
        record("different bytes under the same key are refused", False,
               "THE WRITE SUCCEEDED — R2 did not enforce If-None-Match, so an "
               "immutable release key is not actually immutable")
    except ImmutableObjectConflict:
        record("different bytes under the same key are refused", True,
               "R2 returned a precondition failure")
    except ObjectStoreError as exc:
        record("different bytes under the same key are refused", False, str(exc)[:120])

    # 4. Compare-and-swap, the pointer's mechanism.
    pointer = f"{prefix}/pointer.json"
    try:
        created = store.put_if_absent(pointer, b'{"seq":1}', "application/json")
        stored = store.require(pointer)
        record("read an object back byte for byte", stored.body == b'{"seq":1}')
        swapped = store.put_if_match(
            pointer, b'{"seq":2}', "application/json", stored.etag
        )
        record("compare-and-swap with the current ETag", swapped.result == "created")
    except ObjectStoreError as exc:
        record("compare-and-swap with the current ETag", False, str(exc)[:120])
        return report()

    try:
        store.put_if_match(pointer, b'{"seq":3}', "application/json", created.etag)
        record("compare-and-swap with a stale ETag loses", False,
               "THE WRITE SUCCEEDED — R2 did not enforce If-Match, so a racing "
               "promotion could overwrite a newer one")
    except PreconditionFailed:
        record("compare-and-swap with a stale ETag loses", True,
               "R2 returned a precondition failure")
    except ObjectStoreError as exc:
        record("compare-and-swap with a stale ETag loses", False, str(exc)[:120])

    print(f"\nobjects written under {prefix}/ (immutable, not deleted)")
    return report()


def report() -> int:
    failed = [name for name, ok, _ in CHECKS if not ok]
    print()
    if failed:
        print(f"::error::{len(failed)} of {len(CHECKS)} checks failed: "
              + "; ".join(failed), file=sys.stderr)
        return 1
    print(f"all {len(CHECKS)} checks passed — the promotion identity works and "
          "R2 enforces both preconditions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
