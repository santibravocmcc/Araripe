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

#: A version-3 chain release (PHASE_6J §2.4): an index whose objects live in
#: two member releases.  Every chain case resolves against this fixture.
_CHAIN_ID = "rel-g3-" + "d4" * 32
_CHAIN_PREFIX = f"releases/{_CHAIN_ID}/"
_MEMBER_A = "rel-g1-" + "e5" * 32
_MEMBER_B = "rel-g1-" + "f6" * 32

CHAIN_FIXTURE = {
    "pointer": {
        "schema": "araripe.green.pointer/2",
        "sequence": 15,
        "action": "promote",
        "release_id": _CHAIN_ID,
    },
    "manifest": {
        "schema": "araripe.green.release/3",
        "release_id": _CHAIN_ID,
        "release_prefix": _CHAIN_PREFIX,
        # The third entry is malformed on purpose: listing an id must not be
        # enough to turn it into a prefix, so the "listed-looking" case below
        # exercises the id pattern in every implementation, not only in Python.
        "members": [
            {"release_id": _MEMBER_A},
            {"release_id": _MEMBER_B},
            {"release_id": "../runs/ci-1"},
        ],
        "objects": [
            {
                "path": "alerts/run-2026-08-30.geojson",
                "bytes": 29539158,
                "sha256": "a7" * 32,
                "content_type": "application/geo+json",
                "release_id": _MEMBER_A,
            },
            {
                "path": "alerts/run-2026-09-24.geojson",
                "bytes": 19325375,
                "sha256": "b8" * 32,
                "content_type": "application/geo+json",
                "release_id": _MEMBER_B,
            },
        ],
    },
}

#: A heartbeat (GREEN_HEARTBEAT_CONTRACT_V1.md): a failed attempt after a
#: successful one, so both halves of the document are present.
HEARTBEAT = {
    "schema": "araripe.green.heartbeat/1",
    "lane": "deposit",
    "latest": {
        "outcome": "failed",
        "stage": "detect",
        "finished_utc": "2026-10-05T06:41:09Z",
        "run_id": "ci-36500000002",
        "run_url": "https://github.com/santibravocmcc/Araripe/actions/runs/36500000002",
    },
    "last_success": {
        "outcome": "deposited",
        "stage": None,
        "finished_utc": "2026-10-01T06:52:30Z",
        "run_id": "ci-36500000001",
        "run_url": "https://github.com/santibravocmcc/Araripe/actions/runs/36500000001",
    },
}

FIXTURE["heartbeat"] = HEARTBEAT
CHAIN_FIXTURE["heartbeat"] = HEARTBEAT

#: The land-cover context of the chain fixture (GREEN_CONTEXT_CONTRACT_V1.md):
#: labels and a recomputed strong subset for one date.
_CONTEXT_ID = "ctx-g1-" + "c9" * 32
CONTEXT_POINTER = {
    "schema": "araripe.green.context-pointer/1",
    "sequence": 1,
    "context_id": _CONTEXT_ID,
    "release_id": _CHAIN_ID,
}
CONTEXT_DOCUMENT = {
    "schema": "araripe.green.context/1",
    "context_id": _CONTEXT_ID,
    "release_id": _CHAIN_ID,
    "objects": [
        {
            "path": "alerts/run-2026-08-30.lc.json",
            "bytes": 4012345,
            "sha256": "d1" * 32,
            "content_type": "application/json",
            "observed_on": "2026-08-30",
        },
        {
            "path": "alerts/run-2026-08-30.strong.geojson",
            "bytes": 2512345,
            "sha256": "e2" * 32,
            "content_type": "application/geo+json",
            "observed_on": "2026-08-30",
        },
    ],
}
#: Which context each case sees, by name.
CONTEXTS = {
    "live": (CONTEXT_POINTER, CONTEXT_DOCUMENT),
    # The normal state right after a promotion: the pointer still describes
    # the previous release.
    "stale": ({**CONTEXT_POINTER, "release_id": "rel-g3-" + "00" * 32}, CONTEXT_DOCUMENT),
    "none": (None, None),
    # The document read is not the one the pointer names.
    "mismatch": (CONTEXT_POINTER, {**CONTEXT_DOCUMENT, "context_id": "ctx-g1-" + "0a" * 32}),
    "malformed": ({**CONTEXT_POINTER, "context_id": "../runs/ci-1"}, CONTEXT_DOCUMENT),
    # The key of a context object is its declared sha256: a declaration that is
    # not one must not become a key.
    "bad_sha": (CONTEXT_POINTER, {**CONTEXT_DOCUMENT, "objects": [
        {**CONTEXT_DOCUMENT["objects"][0], "sha256": "../../pointers/green/current.json"},
    ]}),
}

FIXTURES = {
    "release": FIXTURE,
    "chain": CHAIN_FIXTURE,
    # Nothing promoted yet, but the automation has run: the heartbeat must be
    # served without a pointer.
    "unpromoted": {"pointer": None, "manifest": None, "heartbeat": HEARTBEAT},
    # A fresh bucket.
    "nothing": {"pointer": None, "manifest": None, "heartbeat": None},
}

#: The declared path the content-type cases exercise; naming it keeps the
#: patch and the request pointing at the same object.
ALERT_PATH = "/data/green/alerts/2026-04-07/19741870aa21.geojson"

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
    {"name": "a content type carrying CRLF is refused, not placed in a header",
     "method": "GET", "path": ALERT_PATH,
     "object_patch": {"content_type": "application/json\r\nX-Injected: yes"}},
    {"name": "a content type carrying a bare LF is refused",
     "method": "GET", "path": ALERT_PATH,
     "object_patch": {"content_type": "text/plain\nSet-Cookie: a=b"}},
    {"name": "a content type that is not a media type at all is refused",
     "method": "GET", "path": ALERT_PATH,
     "object_patch": {"content_type": "notamediatype"}},
    {"name": "an empty content type is refused",
     "method": "GET", "path": ALERT_PATH, "object_patch": {"content_type": ""}},
    {"name": "a media type with a quoted parameter is accepted verbatim",
     "method": "GET", "path": ALERT_PATH,
     "object_patch": {"content_type": "text/plain; charset=\"utf-8\""}},
    {"name": "a write method is refused before anything is resolved",
     "method": "PUT", "path": "/data/green/series.json"},
    {"name": "DELETE is refused; this route reads",
     "method": "DELETE", "path": "/data/green/series.json"},
    # ── a version-3 chain release, served by reference (PHASE_6J §2.4) ──────
    {"name": "a chain release's manifest is its own, from its own prefix",
     "fixture": "chain", "method": "GET", "path": "/data/green/release.json"},
    {"name": "a chain release's ledger index is public from its own prefix",
     "fixture": "chain", "method": "GET", "path": "/data/green/ledger.json"},
    {"name": "a referenced object is served from the prefix of the member that holds it",
     "fixture": "chain", "method": "GET", "path": "/data/green/alerts/run-2026-08-30.geojson"},
    {"name": "each object resolves to its own member, not to the first one",
     "fixture": "chain", "method": "GET", "path": "/data/green/alerts/run-2026-09-24.geojson"},
    {"name": "a member prefix cannot be addressed directly",
     "fixture": "chain", "method": "GET",
     "path": f"/data/green/releases/{_MEMBER_A}/alerts/run-2026-08-30.geojson"},
    {"name": "an object naming a release the live manifest does not list is refused",
     "fixture": "chain", "method": "GET", "path": "/data/green/alerts/run-2026-08-30.geojson",
     "object_patch": {"release_id": "rel-g1-" + "00" * 32}},
    {"name": "an object naming anything but a version-1 id is refused, even a listed-looking one",
     "fixture": "chain", "method": "GET", "path": "/data/green/alerts/run-2026-08-30.geojson",
     "object_patch": {"release_id": "../runs/ci-1"}},
    {"name": "an object of a chain release that names no member is refused, not served from the index",
     "fixture": "chain", "method": "GET", "path": "/data/green/alerts/run-2026-08-30.geojson",
     "object_patch": {"release_id": None}},
    {"name": "an object naming the chain release itself is refused",
     "fixture": "chain", "method": "GET", "path": "/data/green/alerts/run-2026-08-30.geojson",
     "object_patch": {"release_id": _CHAIN_ID}},
    # ── the automation heartbeat (GREEN_HEARTBEAT_CONTRACT_V1.md §5) ────────
    {"name": "the heartbeat is public, from its one fixed key, and never cached",
     "method": "GET", "path": "/data/green/heartbeat.json"},
    {"name": "HEAD on the heartbeat resolves identically",
     "method": "HEAD", "path": "/data/green/heartbeat.json"},
    {"name": "the heartbeat is served when nothing has been promoted",
     "fixture": "unpromoted", "method": "GET", "path": "/data/green/heartbeat.json"},
    {"name": "with nothing promoted, the pointer is still absent",
     "fixture": "unpromoted", "method": "GET", "path": "/data/green/current.json"},
    {"name": "an absent heartbeat is its own refusal, not the pointer's",
     "fixture": "nothing", "method": "GET", "path": "/data/green/heartbeat.json"},
    {"name": "a document that is not a heartbeat is not served under its name",
     "method": "GET", "path": "/data/green/heartbeat.json",
     "heartbeat_patch": {"schema": "araripe.green.pointer/2"}},
    {"name": "the heartbeat's key cannot be addressed as a path",
     "method": "GET", "path": "/data/green/status/green/heartbeat.json"},
    {"name": "a write to the heartbeat is refused before anything is resolved",
     "method": "PUT", "path": "/data/green/heartbeat.json"},
    # ── the land-cover context (GREEN_CONTEXT_CONTRACT_V1.md) ───────────────
    {"name": "the live context's labels are served from their content key",
     "fixture": "chain", "context": "live", "method": "GET",
     "path": "/data/green/context/alerts/run-2026-08-30.lc.json"},
    {"name": "the live context's strong subset is served, not the release's",
     "fixture": "chain", "context": "live", "method": "GET",
     "path": "/data/green/context/alerts/run-2026-08-30.strong.geojson"},
    {"name": "the live context's own document is public",
     "fixture": "chain", "context": "live", "method": "GET",
     "path": "/data/green/context/context.json"},
    {"name": "a context path the live context does not declare is refused",
     "fixture": "chain", "context": "live", "method": "GET",
     "path": "/data/green/context/alerts/run-2026-09-24.lc.json"},
    {"name": "a release object is not reachable through the context directory",
     "fixture": "chain", "context": "live", "method": "GET",
     "path": "/data/green/context/alerts/run-2026-08-30.geojson"},
    {"name": "a context computed for another release is not served",
     "fixture": "chain", "context": "stale", "method": "GET",
     "path": "/data/green/context/alerts/run-2026-08-30.lc.json"},
    {"name": "with no context published, the context directory is refused as absent",
     "fixture": "chain", "context": "none", "method": "GET",
     "path": "/data/green/context/alerts/run-2026-08-30.lc.json"},
    {"name": "a context document that is not the pointer's is not served",
     "fixture": "chain", "context": "mismatch", "method": "GET",
     "path": "/data/green/context/alerts/run-2026-08-30.lc.json"},
    {"name": "a context pointer naming anything but a context id chooses no prefix",
     "fixture": "chain", "context": "malformed", "method": "GET",
     "path": "/data/green/context/alerts/run-2026-08-30.lc.json"},
    {"name": "a context object's key is its declared sha256, and a non-digest names nothing",
     "fixture": "chain", "context": "bad_sha", "method": "GET",
     "path": "/data/green/context/alerts/run-2026-08-30.lc.json"},
    {"name": "the context's prefix cannot be addressed directly",
     "fixture": "chain", "context": "live", "method": "GET",
     "path": f"/data/green/contexts/objects/{'d1' * 32}"},
    {"name": "the context pointer's key cannot be addressed as a path",
     "fixture": "chain", "context": "live", "method": "GET",
     "path": "/data/green/contexts/current.json"},
    {"name": "release objects are unaffected by a live context",
     "fixture": "chain", "context": "live", "method": "GET",
     "path": "/data/green/alerts/run-2026-08-30.geojson"},
    {"name": "a context download names the file from the declared path",
     "fixture": "chain", "context": "live", "method": "GET", "download": True,
     "path": "/data/green/context/alerts/run-2026-08-30.strong.geojson"},
    {"name": "a write under the context directory is refused before anything is resolved",
     "fixture": "chain", "context": "live", "method": "PUT",
     "path": "/data/green/context/alerts/run-2026-08-30.lc.json"},
]


def _manifest_for(case: dict) -> dict:
    """The fixture manifest, with one object field replaced when a case asks.

    Needed because the sharpest cases are about a manifest field the release
    schema barely constrains — ``content_type`` — and a vector suite that could
    not vary it would leave the one branch a header-injection depends on
    unchecked in every implementation but the Python one.
    """

    fixture = FIXTURES[case.get("fixture", "release")]
    patch = case.get("object_patch")
    if not patch:
        return fixture["manifest"]
    manifest = json.loads(json.dumps(fixture["manifest"]))
    manifest["objects"][0].update(patch)
    return manifest


def _heartbeat_for(case: dict) -> dict | None:
    """The fixture heartbeat, with top-level fields replaced when a case asks."""

    heartbeat = FIXTURES[case.get("fixture", "release")]["heartbeat"]
    patch = case.get("heartbeat_patch")
    if not patch:
        return heartbeat
    return {**heartbeat, **patch}


def _manifest_or_none(case: dict) -> dict | None:
    if FIXTURES[case.get("fixture", "release")]["manifest"] is None:
        return None
    return _manifest_for(case)


def _evaluate(case: dict) -> dict:
    try:
        served = db.resolve(
            case["method"],
            case["path"],
            pointer=FIXTURES[case.get("fixture", "release")]["pointer"],
            manifest=_manifest_or_none(case),
            heartbeat=_heartbeat_for(case),
            download=case.get("download", False),
            context_pointer=CONTEXTS[case.get("context", "none")][0],
            context=CONTEXTS[case.get("context", "none")][1],
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
        "schema": "araripe.green.delivery-vectors/4",
        "boundary_schema": db.BOUNDARY_SCHEMA,
        "mount": db.MOUNT,
        "note": (
            "Generated by scripts/check_delivery_boundary.py. Any implementation "
            "of the /data/... route — the Python authority here, the Worker "
            "Package 2B.4 writes — must reproduce every expectation exactly. "
            "Regenerate with `vectors --write` and review the diff; a silent "
            "change to this file is a change to what the project publishes."
        ),
        "fixtures": FIXTURES,
        "contexts": {
            name: {"pointer": pointer, "document": document}
            for name, (pointer, document) in CONTEXTS.items()
        },
        "cases": [
            {
                "name": case["name"],
                "fixture": case.get("fixture", "release"),
                "method": case["method"],
                "path": case["path"],
                "download": case.get("download", False),
                "object_patch": case.get("object_patch"),
                "heartbeat_patch": case.get("heartbeat_patch"),
                "context": case.get("context", "none"),
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
    members = db.live_member_ids(manifest)
    classified = [
        db.classify_key(item.key, live_release_id=live, live_members=members)
        for item in inventory
    ]
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
    reachable = set(db.public_keys(manifest)) if manifest else {db.HEARTBEAT_KEY}
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
