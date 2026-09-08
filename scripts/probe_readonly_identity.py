#!/usr/bin/env python3
"""Measure what an R2 identity may actually do — by making it be refused.

    python scripts/probe_readonly_identity.py --run-id local-$(date +%s)
    python scripts/probe_readonly_identity.py --run-id … --expect read-write

Package 2B.3: *introduce least-privilege credentials and step-level secret
exposure.*  A credential's scope cannot be established by reading its
configuration.  On 2026-09-07 the first green promotion key had a **perfect**
GitHub Environment — right secret names, right branch policy, right variables —
and reached the **production** bucket, because the scope that mattered lived in
Cloudflare and is invisible from GitHub
(``docs/operations/GREEN_PROOFS_2026-09-07.md`` §2).

    Credential scope is only ever proven by a real call that must be refused.

``scripts/probe_promotion_identity.py`` established that for *isolation* — the
production bucket must be denied.  This script establishes it for *privilege*:
inside the approved bucket, a read-only identity must be refused a **write**
and a **delete**.  Both directions are inverted checks, and both are asserted
in ``tests/test_readonly_identity_probe.py`` so a future edit cannot quietly
turn a refusal into a pass.

Why delete is probed at all
---------------------------
R2 offers four permission levels — Admin Read & Write, Admin Read only, Object
Read & Write, Object Read only — and scoping is **per bucket**, never per
prefix (https://developers.cloudflare.com/r2/api/tokens/).  There is no level
that writes but cannot delete, so *any* identity able to publish a release is
also able to erase one.  That is the measurement behind this package's decision
to keep deletion out of the code entirely: the boundary cannot be the token, so
it has to be the code.

The delete probe targets a key that **does not exist**, and refuses to run if
it does.  S3 semantics make deleting an absent key a no-op, so an identity that
holds the permission destroys nothing and still answers the question.

No secret is printed — only whether a call succeeded, and error *codes*.
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
    ObjectStoreError,
)

#: Every object this probe could ever write lives here, so the retention policy
#: classifies it as verification scaffolding rather than as an unknown prefix
#: (``src/publication/delivery_boundary.VERIFICATION_ROOTS``).
PROBE_ROOT = "readonly-identity-probe"

#: Codes that mean "the identity was refused", as opposed to "something else
#: went wrong".  Deliberately narrow: a 404 is not a refusal, and reading one
#: as a refusal is how an over-scoped key would pass.
DENIED_CODES = frozenset(
    {"AccessDenied", "403", "InvalidAccessKeyId", "SignatureDoesNotMatch"}
)

CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def raw_client(credentials: dict[str, str], endpoint: str):
    """A client that has not been through the target guard.

    ``build_client`` refuses ``araripe-cogs`` by name, which is the *code's*
    boundary.  The property under test here is the **credential's**, so the
    production check needs a client the guard has not filtered — the same
    reason ``probe_promotion_identity.py`` builds one.
    """

    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=credentials["access_key_id"],
        aws_secret_access_key=credentials["secret_access_key"],
        region_name=credentials.get("region") or "auto",
    )


def probe_production_is_denied(client) -> None:
    """The isolation half: production must refuse this identity."""

    try:
        client.list_objects_v2(Bucket=cs.PRODUCTION_BUCKET, MaxKeys=1)
    except Exception as exc:  # noqa: BLE001 - the refusal is the pass condition
        code = cs.error_code(exc) or type(exc).__name__
        record(
            f"{cs.PRODUCTION_BUCKET} is refused for this identity",
            code in DENIED_CODES | {"NoSuchBucket"},
            f"code {code}",
        )
        return
    record(
        f"{cs.PRODUCTION_BUCKET} is refused for this identity",
        False,
        "THE LIST SUCCEEDED — the token is over-scoped and isolation is broken. "
        "Revoke it and create one restricted to " + cs.STAGING_BUCKET,
    )


def probe_write_is_denied(store: ConditionalStore, key: str, expect: str) -> None:
    """The privilege half: a read-only identity must be refused a write.

    Inverted for ``--expect read-write``, where a *successful* write is the
    pass — so the same probe measures the identity the lanes hold today and the
    narrower one this package proposes, and neither result is assumed.
    """

    name = "writing into the staging bucket is refused"
    body = b'{"probe":"readonly-identity","expect":"refused"}'
    try:
        outcome = store.put_if_absent(key, body, "application/json")
    except ObjectStoreError as exc:
        code = cs.error_code(exc.__cause__) if exc.__cause__ else None
        denied = (code or "") in DENIED_CODES
        if expect == "read-only":
            record(name, denied, f"code {code or 'unknown'}")
        else:
            record("writing into the staging bucket succeeds", False,
                   f"expected a write identity; the write failed with "
                   f"{code or str(exc)[:80]}")
        return
    if expect == "read-only":
        record(
            name,
            False,
            "THE WRITE SUCCEEDED — this identity is not read-only. It holds "
            "Object Read & Write, which in R2 also permits DELETE inside the "
            f"bucket. The object left behind is {key}",
        )
    else:
        record("writing into the staging bucket succeeds", outcome.result == "created",
               f"result {outcome.result}")


def probe_delete_is_denied(client, bucket: str, key: str, expect: str) -> None:
    """Does this identity hold DELETE?  Asked of a key that does not exist.

    R2's ``Object Read & Write`` bundles delete with write, so this is the
    check that turns "the token could erase a release" from an inference into a
    measurement.  Targeting an absent key means a permitted delete removes
    nothing.
    """

    name = "deleting from the staging bucket is refused"
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        if not cs.is_absent(exc):
            record(name, False,
                   f"could not confirm {key} is absent (code "
                   f"{cs.error_code(exc) or 'unknown'}); refusing to issue a "
                   "delete against a key whose state is unknown")
            return
    else:
        record(name, False,
               f"{key} EXISTS; refusing to issue a delete. This probe only ever "
               "deletes a key that is not there.")
        return

    try:
        client.delete_object(Bucket=bucket, Key=key)
    except Exception as exc:  # noqa: BLE001
        code = cs.error_code(exc) or type(exc).__name__
        denied = code in DENIED_CODES
        if expect == "read-only":
            record(name, denied, f"code {code}")
        else:
            record("this identity holds DELETE inside the bucket", False,
                   f"the delete was refused with code {code}")
        return
    if expect == "read-only":
        record(name, False,
               "THE DELETE WAS ACCEPTED — this identity can erase objects in "
               f"{bucket}. Nothing was destroyed (the key was absent), but the "
               "privilege is real.")
    else:
        record("this identity holds DELETE inside the bucket", True,
               "accepted on an absent key; nothing was destroyed")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True,
                        help="unique token for this run's immutable prefix")
    parser.add_argument(
        "--expect", choices=("read-only", "read-write"), default="read-only",
        help="what this identity is supposed to be. 'read-only' passes when "
        "write and delete are REFUSED; 'read-write' passes when they are "
        "granted, which is how the identity the lanes hold today is measured.",
    )
    parser.add_argument("--access-key-var", default="R2_READONLY_ACCESS_KEY_ID")
    parser.add_argument("--secret-key-var", default="R2_READONLY_SECRET_ACCESS_KEY")
    args = parser.parse_args(argv)

    bucket = os.environ.get("R2_STAGING_BUCKET", "")
    endpoint = os.environ.get("R2_ENDPOINT_URL", "")
    credentials = {
        "access_key_id": os.environ.get(args.access_key_var, ""),
        "secret_access_key": os.environ.get(args.secret_key_var, ""),
        "region": os.environ.get("AWS_REGION", "auto"),
    }

    print("green least-privilege identity probe")
    print(f"  bucket   : {bucket}")
    print(f"  endpoint : {endpoint}")
    print(f"  expecting: {args.expect}")
    print(f"  key id   : {'set' if credentials['access_key_id'] else 'MISSING'}")
    print(f"  secret   : {'set' if credentials['secret_access_key'] else 'MISSING'}")
    print()

    try:
        guarded = cs.build_client(bucket, endpoint, credentials)
    except ObjectStoreError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    record("target guard and conditional-write support", True,
           "bucket, endpoint and botocore accepted")

    try:
        guarded.list_objects_v2(Bucket=bucket, MaxKeys=1)
        record(f"list {bucket}", True)
    except Exception as exc:  # noqa: BLE001
        record(f"list {bucket}", False, f"code {cs.error_code(exc) or exc}")
        return report()

    probe_production_is_denied(raw_client(credentials, endpoint))

    prefix = f"{PROBE_ROOT}/run-{args.run_id}"
    store = ConditionalStore(guarded, bucket)
    probe_write_is_denied(store, f"{prefix}/write-attempt.json", args.expect)
    probe_delete_is_denied(
        guarded, bucket, f"{prefix}/never-created.json", args.expect
    )
    return report()


def report() -> int:
    failed = [name for name, ok, _ in CHECKS if not ok]
    print()
    if failed:
        print(f"::error::{len(failed)} of {len(CHECKS)} checks failed: "
              + "; ".join(failed), file=sys.stderr)
        return 1
    print(f"all {len(CHECKS)} checks passed — this identity's scope is measured, "
          "not assumed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
