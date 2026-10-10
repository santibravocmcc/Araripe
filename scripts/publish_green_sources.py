#!/usr/bin/env python3
"""Build and publish the sources document of the live green release.

Contract: ``docs/contracts/phase2b/GREEN_SOURCES_CONTRACT_V1.md``.

    # 1. read the live release, its ledgers and its live context (store; lane only)
    python scripts/publish_green_sources.py fetch --out .cache/sources-input

    # 2. check the records against the repository, build, check (no store)
    python scripts/publish_green_sources.py plan \
        --input .cache/sources-input --out .cache/sources-output [--expect src-g1-…]

    # 3. write it, then point sources/current.json at it (store; lane only)
    python scripts/publish_green_sources.py apply --sources .cache/sources-output

``plan`` contacts no store, and it is ``plan_green_sources.py``'s own check and
build — the same ``repository_findings`` before, the same ``build_sources`` and
``check_sources`` after — on inputs whose sha256 ``fetch`` verified.

What "live" means here is what the delivery boundary will serve
(``delivery/3``): the release the green pointer names, and the context
``contexts/current.json`` names **only if** it describes that release.  A
context left over from an earlier release is no context at all — the document
then seals no 2025 context record, exactly as the route would serve no
context.

``apply`` decides again, from the store, right before it writes: the live
release and the live context must still be the ones the document names, and
the document must still check against them.  A promotion or a context move
that lands after that check leaves ``sources/current.json`` naming a pair
that is no longer live, which the route refuses (``sources_not_live``) — the
page keeps its own credits — until the next run moves it.  The failure is
toward "not served", never toward "served for the wrong release".

``fetch`` and ``apply`` build the store the way ``publish_green_context.py``
does — from environment variables a lane provides, never from a local
profile.  ``config.settings`` is never imported: it loads the production
``.env``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from plan_green_sources import SPEC_PATH, repository_findings  # noqa: E402
from src.publication import conditional_store as cs  # noqa: E402
from src.publication import green_context as gc  # noqa: E402
from src.publication import green_sources as gs  # noqa: E402
from src.publication import sources_pointer  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402

POINTER_KEY = "pointers/green/current.json"
RELEASE_V1 = "araripe.green.release/1"
RELEASE_V3 = "araripe.green.release/3"
LEDGER_INDEX_SCHEMA = "araripe.green.ledger-index/1"
LEDGER_NAME = "ledger.json"

#: The same names ``publish_green_context.py`` reads, from the same Environment
#: (``v2-promotion``): publishing the sources is a publication act.
ACCESS_KEY_VAR = "R2_PROMOTION_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_PROMOTION_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"

#: What ``fetch`` writes, under ``--out``.
RELEASE_FILE = "release.json"
CONTEXT_FILE = "context.json"
LEDGERS_DIR = "ledgers"
FETCHED_FILE = "fetched.json"


def _say(message: str) -> None:
    print(message, flush=True)


def _error(message: str) -> str:
    return f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}"


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class SourcesInputError(RuntimeError):
    """What the store holds does not add up to a live release we can describe."""


# ── what is live (store) ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Live:
    release_body: bytes
    release: dict
    ledger_bodies: tuple[bytes, ...]
    #: ``None`` when no context describes the live release.
    context_body: bytes | None
    context: dict | None
    #: Why there is no context, for the log; empty when there is one.
    context_note: str = ""

    @property
    def context_id(self) -> str | None:
        return None if self.context is None else self.context["context_id"]


def _checked(store, key: str, sha256: str, what: str, size: int | None = None) -> bytes:
    body = store.require(key).body
    if _sha256(body) != sha256 or (size is not None and len(body) != size):
        raise SourcesInputError(f"{what} at {key} does not have the bytes and sha256 its parent declares")
    return body


def _ledger_bodies(store, release: dict) -> tuple[bytes, ...]:
    """Every ledger the release was built from, in order, each verified by sha256.

    A version-1 release keeps its ledger beside it; a version-3 release keeps an
    index (``ledger.json``) of where each member's ledger is.  Version 2 is not
    read: no release has been promoted in it since the chain moved to version
    3 (PHASE_6J), and guessing its layout would be worse than refusing.
    """

    prefix = release["release_prefix"]
    if release["schema"] == RELEASE_V1:
        block = release["ledger"]
        return (_checked(store, prefix + LEDGER_NAME, block["file_sha256"], "the ledger", block["bytes"]),)
    if release["schema"] != RELEASE_V3:
        raise SourcesInputError(f"no reader for the ledgers of a {release['schema']!r} release")
    block = release["ledgers"]
    index = json.loads(_checked(store, prefix + LEDGER_NAME, block["file_sha256"], "the ledger index", block["bytes"]))
    if index.get("schema") != LEDGER_INDEX_SCHEMA:
        raise SourcesInputError(f"{prefix + LEDGER_NAME} is not a {LEDGER_INDEX_SCHEMA} document")
    members = [m["release_id"] for m in release["members"]]
    if [entry["release_id"] for entry in index["ledgers"]] != members:
        raise SourcesInputError("the ledger index does not list the release's members, in order")
    return tuple(
        _checked(store, entry["key"], entry["file_sha256"], f"the ledger of {entry['release_id']}", entry["bytes"])
        for entry in index["ledgers"]
    )


def read_live(store) -> Live:
    """The live release, its ledgers, and the context that describes it (if any)."""

    pointer = json.loads(store.require(POINTER_KEY).body)
    release_body = _checked(store, pointer["release_path"], pointer["release_document_sha256"], "the live release")
    release = json.loads(release_body)
    if release["release_id"] != pointer["release_id"]:
        raise SourcesInputError(f"the pointer names {pointer['release_id']} and its document is {release['release_id']}")
    ledgers = _ledger_bodies(store, release)

    stored = store.get(gc.CONTEXT_CURRENT_KEY)
    if stored is None:
        return Live(release_body, release, ledgers, None, None, "no context has been published")
    context_pointer = json.loads(stored.body)
    if context_pointer.get("release_id") != release["release_id"]:
        return Live(release_body, release, ledgers, None, None,
                    f"the context pointer describes {context_pointer.get('release_id')}, not the live release")
    context_body = _checked(store, context_pointer["context_path"], context_pointer["context_document_sha256"],
                            "the live context")
    context = json.loads(context_body)
    if (context.get("context_id"), context.get("release_id")) != (context_pointer["context_id"], release["release_id"]):
        raise SourcesInputError("the context document is not the one the context pointer names")
    return Live(release_body, release, ledgers, context_body, context)


def build_store() -> cs.ConditionalStore:
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


# ── fetch (store; lane only) ─────────────────────────────────────────────────

def cmd_fetch(args, store=None) -> int:
    live = read_live(store or build_store())
    out = Path(args.out)
    (out / LEDGERS_DIR).mkdir(parents=True, exist_ok=True)
    (out / RELEASE_FILE).write_bytes(live.release_body)
    for index, body in enumerate(live.ledger_bodies):
        (out / LEDGERS_DIR / f"{index:04d}.json").write_bytes(body)
    if live.context_body is not None:
        (out / CONTEXT_FILE).write_bytes(live.context_body)
    (out / FETCHED_FILE).write_text(json.dumps({
        "release_id": live.release["release_id"],
        "release_document_sha256": _sha256(live.release_body),
        "context_id": live.context_id,
        "context_document_sha256": None if live.context_body is None else _sha256(live.context_body),
        "ledgers": len(live.ledger_bodies),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _say(f"release  {live.release['release_id']}")
    _say(f"ledgers  {len(live.ledger_bodies)}")
    _say(f"context  {live.context_id or '(none) — ' + live.context_note}")
    return 0


# ── plan (no store) ──────────────────────────────────────────────────────────

def load_input(source: Path) -> tuple[dict, dict | None, list[dict]]:
    """``(release, context, ledgers)`` as ``fetch`` wrote them, re-verified."""

    fetched = json.loads((source / FETCHED_FILE).read_text(encoding="utf-8"))
    release_body = (source / RELEASE_FILE).read_bytes()
    if _sha256(release_body) != fetched["release_document_sha256"]:
        raise SourcesInputError("release.json on disk is not the one fetch read; run fetch again")
    context = None
    if fetched["context_id"] is not None:
        context_body = (source / CONTEXT_FILE).read_bytes()
        if _sha256(context_body) != fetched["context_document_sha256"]:
            raise SourcesInputError("context.json on disk is not the one fetch read; run fetch again")
        context = json.loads(context_body)
    elif (source / CONTEXT_FILE).exists():
        raise SourcesInputError("fetch found no live context, yet a context.json is on disk")
    ledgers = [json.loads(path.read_bytes()) for path in sorted((source / LEDGERS_DIR).glob("*.json"))]
    if len(ledgers) != fetched["ledgers"]:
        raise SourcesInputError(f"fetch read {fetched['ledgers']} ledger(s) and {len(ledgers)} are on disk")
    return json.loads(release_body), context, ledgers


def cmd_plan(args) -> int:
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    problems = repository_findings(spec)
    if problems:
        for line in problems:
            print(_error(line), file=sys.stderr)
        return 2
    release, context, ledgers = load_input(Path(args.input))
    document = gs.build_sources(release, context, spec, ledgers)
    body = gs.serialise(document)
    gs.check_sources(json.loads(body), release, context, ledgers)
    if args.expect and document["sources_id"] != args.expect:
        raise SystemExit(_error(
            f"the inputs build {document['sources_id']}, not the expected {args.expect}: "
            "something changed between the two readings — stop and find out what"))
    target = Path(args.out) / document["sources_prefix"] / gs.SOURCES_DOCUMENT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    _say(f"sources  {document['sources_id']}")
    _say(f"release  {document['release_id']}")
    _say(f"context  {document['context_id']}")
    _say(f"bytes    {len(body)}  sha256 {_sha256(body)}")
    for line in document["attribution"]:
        _say(f"  [{line['applies_to']}] {line['text']}")
    _say(f"wrote    {target}")
    return 0


# ── apply (store; lane only) ─────────────────────────────────────────────────

def cmd_apply(args, store=None) -> int:
    root = Path(args.sources)
    found = sorted(root.glob(f"{gs.SOURCES_ROOT}*/{gs.SOURCES_DOCUMENT_NAME}"))
    if len(found) != 1:
        raise SystemExit(_error(f"expected exactly one sources document under {root}, found {len(found)}"))
    body = found[0].read_bytes()
    document = json.loads(body)

    store = store or build_store()
    live = read_live(store)
    if document["release_id"] != live.release["release_id"]:
        raise SystemExit(_error(
            f"the live release is {live.release['release_id']} but this document describes "
            f"{document['release_id']}; sources are only published for the live release"))
    if document["context_id"] != live.context_id:
        raise SystemExit(_error(
            f"the live context is {live.context_id} but this document covers {document['context_id']}; "
            "run the lane again"))
    gs.check_sources(document, live.release, live.context, [json.loads(b) for b in live.ledger_bodies])

    key = document["sources_prefix"] + gs.SOURCES_DOCUMENT_NAME
    outcome = store.put_if_absent(key, body, "application/json")
    _say(f"{outcome.result:9}  {key}")
    env = os.environ
    result = sources_pointer.move(store, document, body, {
        "workflow": env.get("GITHUB_WORKFLOW"),
        "run_id": env.get("GITHUB_RUN_ID"),
        "actor": env.get("GITHUB_ACTOR"),
    })
    _say(f"pointer  {gs.SOURCES_CURRENT_KEY} {result} → {document['sources_id']}")
    return 0


def main(argv=None, store=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="read the live release, its ledgers and its context (store)")
    fetch.add_argument("--out", required=True)
    plan = sub.add_parser("plan", help="check the records, build and check the document locally (no store)")
    plan.add_argument("--input", required=True)
    plan.add_argument("--out", required=True)
    plan.add_argument("--spec", default=str(SPEC_PATH))
    plan.add_argument("--expect", default="", help="refuse unless the document built has this id")
    apply = sub.add_parser("apply", help="publish a planned document and move its pointer (store)")
    apply.add_argument("--sources", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            return cmd_fetch(args, store)
        if args.command == "plan":
            return cmd_plan(args)
        return cmd_apply(args, store)
    except (Rejected, cs.ObjectStoreError, SourcesInputError) as exc:
        print(_error(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
