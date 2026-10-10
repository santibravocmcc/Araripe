#!/usr/bin/env python3
"""Print the status of every green product — read-only, derived, never stored.

    python3 scripts/green_status.py

One line per product (``src/publication/green_status.py``): the alerts the page
can show and the last date looked at, the deposits the pointer does not carry
yet, the automation's last attempt and last success, and whether the context
and the sources documents are the ones the route serves.  Inside Actions the
same table goes to the job summary.  ``docs/implementation/PHASE_6Y_2026-10-10.md``
is the design.

Exit 1 when something is **broken** — a document that cannot be read or
does not check, a chain the head resolution refuses, a route refusal that is
not "a lane has not caught up" — or **late**: the last attempt older than 5
days, or the last date looked at older than 21 (the owner's limits,
2026-10-10, PHASE_6Y §4). No other age fails it.

The identity, and what it can do from here
------------------------------------------
``R2_STAGING_*`` — the **candidate** identity, never the promotion one: reading
the state must not need the key that moves the pointer.  It is opened through
``ReadOnlyStore`` and **without** the local profile fallback, exactly as
``resolve_chain_head.py``: a lane step (``v2_green_status.yml``), not a new
local caller of the key.  ``main`` takes a ``store`` so a harness can hand it
one.  It never imports ``config``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import atomic_publish as ap  # noqa: E402
from src.publication import conditional_store as cs  # noqa: E402
from src.publication import delivery_boundary as db  # noqa: E402
from src.publication import green_context as gc  # noqa: E402
from src.publication import green_sources as gs  # noqa: E402
from src.publication import green_status as st  # noqa: E402
from src.publication import heartbeat as hb  # noqa: E402
from src.publication import state_chain as sc  # noqa: E402
from src.publication.findings import Rejected  # noqa: E402
from src.publication.run_inputs import ReadOnlyStore  # noqa: E402

ACCESS_KEY_VAR = "R2_STAGING_ACCESS_KEY_ID"
SECRET_KEY_VAR = "R2_STAGING_SECRET_ACCESS_KEY"
BUCKET_VAR = "R2_STAGING_BUCKET"
ENDPOINT_VAR = "R2_ENDPOINT_URL"


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


def _json(store, key: str):
    """The parsed document at ``key``, ``None`` when absent, or :class:`Unreadable`."""

    try:
        stored = store.get(key)
    except cs.ObjectStoreError as exc:
        return st.Unreadable(f"{key}: {exc}")
    if stored is None:
        return None
    try:
        return json.loads(stored.body)
    except (ValueError, UnicodeDecodeError) as exc:
        return st.Unreadable(f"{key} is not JSON: {exc}")


def _named(store, key: str, sha256: str, what: str):
    """A document a pointer names by key and digest — present, and those bytes."""

    try:
        stored = store.get(key)
    except cs.ObjectStoreError as exc:
        return st.Unreadable(f"{key}: {exc}")
    if stored is None:
        return st.Unreadable(f"{what} at {key} is absent")
    if hashlib.sha256(stored.body).hexdigest() != sha256:
        return st.Unreadable(f"{what} at {key} does not have the sha256 its pointer declares")
    try:
        return json.loads(stored.body)
    except (ValueError, UnicodeDecodeError) as exc:
        return st.Unreadable(f"{key} is not JSON: {exc}")


def _schema(document, schema: str, key: str):
    if isinstance(document, dict) and document.get("schema") != schema:
        return st.Unreadable(f"{key} declares {document.get('schema')!r}, not {schema}")
    return document


def read(store) -> st.Reading:
    """Every document the status needs; each failure stays in its own field."""

    try:
        pointer, _ = ap.read_live_pointer(store)
    except cs.ObjectStoreError as exc:
        pointer = st.Unreadable(str(exc))

    release = None
    if isinstance(pointer, dict):
        release = _named(store, pointer["release_path"], pointer["release_document_sha256"], "the live release")
        if isinstance(release, dict) and release.get("release_id") != pointer["release_id"]:
            release = st.Unreadable(f"the pointer names {pointer['release_id']} and its "
                                    f"release.json is {release.get('release_id')}")
    live = release["release_id"] if isinstance(release, dict) else None

    beat = _json(store, db.HEARTBEAT_KEY)
    if isinstance(beat, dict):
        try:
            hb.check_heartbeat(beat)
        except Rejected as exc:
            beat = st.Unreadable(str(exc))

    context_pointer = _schema(_json(store, gc.CONTEXT_CURRENT_KEY), gc.CONTEXT_POINTER_SCHEMA,
                              gc.CONTEXT_CURRENT_KEY)
    context = None
    if isinstance(context_pointer, dict) and live and context_pointer.get("release_id") == live:
        context = _named(store, context_pointer["context_path"],
                         context_pointer["context_document_sha256"], "the live context")

    sources_pointer = _schema(_json(store, gs.SOURCES_CURRENT_KEY), gs.SOURCES_POINTER_SCHEMA,
                              gs.SOURCES_CURRENT_KEY)
    sources = None
    if isinstance(sources_pointer, dict) and live and not isinstance(context_pointer, st.Unreadable):
        live_context = db.live_context_id(release, context_pointer)
        if (sources_pointer.get("release_id"), sources_pointer.get("context_id")) == (live, live_context):
            sources = _named(store, sources_pointer["sources_path"],
                             sources_pointer["sources_document_sha256"], "the live sources")

    try:
        chain = sc.resolve_head(store)
        predecessor = sc.read_predecessor(store, chain.run_id)
        head = st.Head(chain.run_id, predecessor.last_observed_on)
    except Rejected as exc:
        head = None if exc.codes == ("chain_root_absent",) else st.Unreadable(str(exc))
    except (cs.ObjectStoreError, RuntimeError, ValueError) as exc:
        head = st.Unreadable(f"{type(exc).__name__}: {exc}")

    return st.Reading(pointer, release, beat, context_pointer, context, sources_pointer, sources, head)


def main(argv=None, store=None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)

    now = now or datetime.now(timezone.utc)
    try:
        reading = read(store or build_reader())
    except cs.ObjectStoreError as exc:
        message = f"the store could not be opened: {exc}"
        print(f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}",
              file=sys.stderr)
        return 1
    rows = st.assess(reading, now)
    print(st.as_text(rows, now))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(st.as_markdown(rows, now))
    print("read-only — nothing was written to the bucket")
    if st.broken(rows) or st.late(rows):
        for row in rows:
            if row.state in (st.BROKEN, st.LATE):
                message = f"{row.product}: {row.detail}"
                print(f"::error::{message}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {message}",
                      file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
