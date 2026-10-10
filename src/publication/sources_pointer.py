"""The one writer of the sources pointer (GREEN_SOURCES_CONTRACT_V1.md).

``sources/current.json`` lives in the sources family, for the reason the
context pointer lives in its own: the release pointer's namespace has one
writer, which keeps the promotion history (``tests/test_promotion_history.py``,
H2).  This module swaps only its own key and never names the release
pointer's.

Compare-and-swap, as everywhere a mutable key is replaced: a lost race raises
``PreconditionFailed`` rather than retrying a decision made about a stale
version.  Its one caller is ``scripts/publish_green_sources.py`` ``apply``
(PHASE_6X), after it has re-read the live release and live context.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from . import green_sources as gs


def move(store: Any, document: Mapping[str, Any], document_body: bytes, written_by: Mapping[str, Any]) -> str:
    """Point ``sources/current.json`` at ``document``; returns what happened."""

    current = store.get(gs.SOURCES_CURRENT_KEY)
    previous = None if current is None else json.loads(current.body)
    if previous is not None and previous["sources_id"] == document["sources_id"]:
        return "unchanged"
    body = gs.serialise(gs.pointer_document(
        document=document,
        document_sha256=hashlib.sha256(document_body).hexdigest(),
        sequence=1 if previous is None else previous["sequence"] + 1,
        written_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        written_by=written_by,
    ))
    if current is None:
        store.put_if_pointer_absent(gs.SOURCES_CURRENT_KEY, body, "application/json")
    else:
        store.put_if_match(gs.SOURCES_CURRENT_KEY, body, "application/json", current.etag)
    return "moved"
