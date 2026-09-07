#!/usr/bin/env python3
"""The green delivery boundary: what is public, and the vectors that pin it.

    python scripts/check_delivery_boundary.py vectors --check
    python scripts/check_delivery_boundary.py vectors --write
    python scripts/check_delivery_boundary.py surface          # reads R2

Package 2B.3, bullets 1 and 4: *create a private processing boundary and a
public release-only boundary*, and *prepare and validate a same-origin
``/data/...`` route*.

Two subcommands, for two different questions.

``vectors`` — the conformance suite
-----------------------------------
``src/publication/delivery_boundary.py`` is the authority, and it is Python.
The thing that will actually answer a request is a Worker, and it is
JavaScript.  Two implementations of one policy drift, and the drift is silent
because both look right in isolation.

So the policy is pinned as **vectors**: a fixture pointer and manifest, a list
of requests, and the exact outcome each must produce.  The Python authority is
checked against them here and in ``tests/test_delivery_boundary.py``; the
Worker written in Package 2B.4 must pass the same file.  Neither implementation
is the reference — the vectors are, and a change to the policy that forgets one
of them fails the gate.

This is the same division Package 2B.2A reached: the schema owns shape, the
code owns the relations shape cannot express, and neither restates the other.

``surface`` — what is public right now
--------------------------------------
Lists the real staging bucket, reads the live pointer and manifest, and prints
every key classified.  Read-only, and the answer a reviewer actually wants:
not "what does the policy say" but "what would leave the bucket today".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import conditional_store as cs  # noqa: E402
from src.publication import delivery_boundary as db  # noqa: E402
from src.publication import retention  # noqa: E402
from src.publication import run_inputs as ri  # noqa: E402

VECTORS_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/contracts/phase2b/delivery_conformance_vectors.json"
)

#: A fixture release, small enough to read and wide enough to exercise every
#: branch: two products on two dates, one of them nested, plus a content type
#: with a parameter.
_RELEASE_ID = "rel-g1-" + "a1" * 32
_PREFIX = f"releases/{_RELEASE_ID}/"

FIXTURE = {
    "pointer": {
        "schema": "araripe.green.pointer/1",
        "sequence": 3,
        "action": "rollback",
        "release_id": _RELEASE_ID,
    },
    "manifest": {
        "schema": "araripe.green.release/1",
        "release_id": _RELEASE_ID,
        "release_prefix": _PREFIX,
        "objects": [
            {
                "path": "alerts/2026-04-07/19741870aa21.geojson",
                "bytes": 78,
                "sha256": "b1" * 32,
                "content_type": "application/geo+json",
            },
            {
                "path": "series.json",
                "bytes": 12,
                "sha256": "c2" * 32,
                "content_type": "application/json; charset=utf-8",
            },
        ],
    },
}

#: Every case is named for the property it defends, not for its input.
CASES: list[dict] = [
    {"name": "the pointer is public and never cached",
     "method": "GET", "path": "/data/green/current.json"},
    {"name": "the live manifest is public",
     "method": "GET", "path": "/data/green/release.json"},
    {"name": "the live ledger is public, so a consumer can verify the manifest",
     "method": "GET", "path": "/data/green/ledger.json"},
    {"name": "a declared product is served from the live release prefix",
     "method": "GET", "path": "/data/green/alerts/2026-04-07/19741870aa21.geojson"},
    {"name": "HEAD is allowed and resolves identically",
     "method": "HEAD", "path": "/data/green/series.json"},
    {"name": "a download names the file from the declared path",
     "method": "GET", "path": "/data/green/series.json", "download": True},
    {"name": "an undeclared path is refused, however ordinary it looks",
     "method": "GET", "path": "/data/green/alerts/2026-04-08/other.geojson"},
    {"name": "a processing input cannot be addressed",
     "method": "GET", "path": "/data/green/runs/proof-a-2026-09-07/run.json"},
    {"name": "a release prefix cannot be addressed, not even the live one",
     "method": "GET", "path": f"/data/green/{_PREFIX}release.json"},
    {"name": "traversal is refused as undeclared, not sanitised",
     "method": "GET", "path": "/data/green/../../pointers/green/current.json"},
    {"name": "an absolute-looking path is refused as undeclared",
     "method": "GET", "path": "/data/green//etc/passwd"},
    {"name": "the mount is not a prefix match on the site's static assets",
     "method": "GET", "path": "/data/alerts/manifest.json"},
    {"name": "a write method is refused before anything is resolved",
     "method": "PUT", "path": "/data/green/series.json"},
    {"name": "DELETE is refused; this route reads",
     "method": "DELETE", "path": "/data/green/series.json"},
]


def _evaluate(case: dict) -> dict:
    try:
        served = db.resolve(
            case["method"],
            case["path"],
            pointer=FIXTURE["pointer"],
            manifest=FIXTURE["manifest"],
            download=case.get("download", False),
        )
    except db.DeliveryRefused as exc:
        return {"outcome": "refused", "code": exc.codes[0]}
    return {
        "outcome": "served",
        "key": served.key,
        "status": served.status,
        "headers": dict(served.headers),
        "sha256": served.sha256,
        "bytes": served.bytes,
    }


def build_vectors() -> dict:
    return {
        "schema": "araripe.green.delivery-vectors/1",
        "boundary_schema": db.BOUNDARY_SCHEMA,
        "mount": db.MOUNT,
        "note": (
            "Generated by scripts/check_delivery_boundary.py. Any implementation "
            "of the /data/... route — the Python authority here, the Worker "
            "Package 2B.4 writes — must reproduce every expectation exactly. "
            "Regenerate with `vectors --write` and review the diff; a silent "
            "change to this file is a change to what the project publishes."
        ),
        "fixture": FIXTURE,
        "cases": [
            {
                "name": case["name"],
                "method": case["method"],
                "path": case["path"],
                "download": case.get("download", False),
                "expect": _evaluate(case),
            }
            for case in CASES
        ],
    }


def _serialise(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def cmd_vectors(args) -> int:
    built = build_vectors()
    if args.write:
        VECTORS_PATH.write_text(_serialise(built), encoding="utf-8")
        print(f"wrote {len(built['cases'])} case(s) to {VECTORS_PATH}")
        return 0
    if not VECTORS_PATH.exists():
        print(f"erro: {VECTORS_PATH} is absent; run with --write", file=sys.stderr)
        return 1
    stored = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    if stored != built:
        print(
            "erro: the committed vectors do not match what the authority "
            "produces. Either the policy changed and the vectors were not "
            "regenerated, or the vectors were edited by hand.",
            file=sys.stderr,
        )
        return 1
    print(f"{len(built['cases'])} case(s) match the authority")
    return 0


def cmd_surface(args) -> int:
    bucket = os.environ.get("R2_STAGING_BUCKET", cs.STAGING_BUCKET)
    endpoint = os.environ.get("R2_ENDPOINT_URL", cs.STAGING_ENDPOINT)
    try:
        client = cs.build_client(
            bucket,
            endpoint,
            {
                "access_key_id": os.environ.get("R2_STAGING_ACCESS_KEY_ID", ""),
                "secret_access_key": os.environ.get("R2_STAGING_SECRET_ACCESS_KEY", ""),
                "region": os.environ.get("AWS_REGION", "auto"),
            },
        )
        store = ri.ReadOnlyStore(client, bucket)
        inventory = retention.list_inventory(client, bucket)
        stored_pointer = store.get(db.POINTER_KEY)
        pointer = json.loads(stored_pointer.body) if stored_pointer else None
        manifest = None
        if pointer is not None:
            manifest = json.loads(store.require(pointer["release_path"]).body)
    except cs.ObjectStoreError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    live = pointer["release_id"] if pointer else None
    classified = [db.classify_key(item.key, live_release_id=live) for item in inventory]
    public = [entry for entry in classified if entry.is_public]

    print(f"bucket        : {bucket}")
    print(f"live release  : {live or '(none)'}")
    print(f"objects       : {len(classified)}")
    print(f"public        : {len(public)}")
    print(f"private       : {len(classified) - len(public)}")
    print()
    print("public surface, as the route would resolve it:")
    if manifest is not None:
        db.check_release_layout(manifest)
        for key in db.public_keys(manifest):
            print(f"  {key}")
    print()
    print("private, by reason:")
    for entry in classified:
        if not entry.is_public:
            print(f"  [{entry.reason}] {entry.key}")
    reachable = set(db.public_keys(manifest)) if manifest else set()
    unreachable = [e.key for e in public if e.key not in reachable]
    if unreachable:
        print()
        print(
            "::error::these keys classify as public but the route cannot reach "
            "them, so they are published without being served:"
        )
        for key in unreachable:
            print(f"  {key}")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    vectors = sub.add_parser("vectors", help="check or regenerate the conformance vectors")
    group = vectors.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", default=True)
    group.add_argument("--write", action="store_true")
    vectors.set_defaults(func=cmd_vectors)
    surface = sub.add_parser("surface", help="classify the real bucket (read-only)")
    surface.set_defaults(func=cmd_surface)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
