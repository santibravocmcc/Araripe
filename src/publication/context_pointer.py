"""The one writer of the land-cover context pointer (GREEN_CONTEXT_CONTRACT_V1.md).

The context pointer lives in the context's own family, ``contexts/current.json``,
and **not** beside the release pointer: that namespace belongs to the release
pointer alone, whose single writer keeps the promotion history
(``tests/test_promotion_history.py``, H2).  This module swaps only its own key
and never names the release pointer's — that guard reads this file's text and
would refuse it otherwise.

Compare-and-swap, as everywhere a mutable key is replaced: a lost race raises
``PreconditionFailed`` rather than retrying a decision made about a stale
version.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from . import green_context as gc


def move(store: Any, document: Mapping[str, Any], document_body: bytes, written_by: Mapping[str, Any]) -> str:
    """Point ``contexts/current.json`` at ``document``; returns what happened."""

    current = store.get(gc.CONTEXT_CURRENT_KEY)
    previous = None if current is None else json.loads(current.body)
    if previous is not None and previous["context_id"] == document["context_id"]:
        return "unchanged"
    body = gc.serialise(gc.pointer_document(
        context=document,
        context_document_sha256=hashlib.sha256(document_body).hexdigest(),
        sequence=1 if previous is None else previous["sequence"] + 1,
        written_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        written_by=written_by,
    ))
    if current is None:
        store.put_if_pointer_absent(gc.CONTEXT_CURRENT_KEY, body, "application/json")
    else:
        store.put_if_match(gc.CONTEXT_CURRENT_KEY, body, "application/json", current.etag)
    return "moved"
