"""The green automation heartbeat: when the lane last tried, and what happened.

Contract: ``docs/contracts/phase2b/GREEN_HEARTBEAT_CONTRACT_V1.md``.  Shape is
``schemas/green-heartbeat-v1.schema.json``; this module owns what shape cannot
say — which job results mean which outcome, the merge, the two relations the
merge guarantees, and the compare-and-swap that writes it.

Why a merge and not "write the latest attempt"
----------------------------------------------
The document carries ``last_success`` forward across failures, so every write
is a read-modify-write, and two lanes may finish together.  The merge is two
maxima — the latest attempt overall, the latest successful one — so it is
commutative: whichever writer wins the race, re-reading and re-merging
converges on the same document.  That is what makes retrying a lost
compare-and-swap correct here, where the pointer must refuse and re-decide
(``ConditionalStore.put_if_match``): the decision is re-evaluated against the
version that won, not resent.

What it never does
------------------
Names a release, a window, a covered date or a count
(``GREEN_HEARTBEAT_CONTRACT_V1.md`` §4).  Writes any key but
``HEARTBEAT_KEY``.  Deletes anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from src.publication import conditional_store as cs
from src.publication.delivery_boundary import HEARTBEAT_KEY
from src.publication.findings import Finding, Rejected
from src.publication.green_release import schema_validator

SCHEMA = "araripe.green.heartbeat/1"
SCHEMA_NAME = "green-heartbeat-v1"
LANE = "deposit"
CONTENT_TYPE = "application/json"

DEPOSITED = "deposited"
NOTHING_TO_DO = "nothing_to_do"
NO_ACQUISITION = "no_acquisition"
FAILED = "failed"
CANCELLED = "cancelled"

#: The automation ran and did what the situation allowed.
SUCCESSES = frozenset({DEPOSITED, NOTHING_TO_DO, NO_ACQUISITION})

DETECT = "detect"
DEPOSIT = "deposit"

STAMP = "%Y-%m-%dT%H:%M:%SZ"

#: How many times a lost compare-and-swap is re-read and re-merged before the
#: writer gives up.  Each retry is against a version another lane wrote, so
#: more than a handful means something is writing in a loop, not racing.
MAX_TRIES = 5

_RUN_ID = re.compile(r"^ci-([1-9][0-9]{0,19})$")


class HeartbeatRejected(Rejected):
    """A heartbeat document contradicts its contract."""

    subject = "heartbeat"


@dataclass(frozen=True)
class Recorded:
    """What one write did: ``created``, ``replaced`` or ``unchanged``."""

    result: str
    tries: int
    document: dict[str, Any]


# ── which job results mean which outcome ─────────────────────────────────────


def classify_outcome(
    *, detect: str, deposit: str, proceed: str, will_deposit: str
) -> tuple[str, str | None]:
    """``(outcome, stage)`` from the lane's two job results and two outputs.

    ``detect`` and ``deposit`` are ``needs.<job>.result``: ``success``,
    ``failure``, ``cancelled`` or ``skipped``.  ``proceed`` and
    ``will_deposit`` are the detection's ``proceed`` and ``deposit`` outputs.

    Total on purpose: any combination the table does not name is ``failed``.
    A heartbeat that refused to record an unforeseen combination would leave
    the previous beat standing, and that reads as "nothing happened" — the one
    answer this document exists to stop giving.
    """

    if detect == "cancelled":
        return CANCELLED, DETECT
    if detect != "success":
        return FAILED, DETECT
    if proceed == "false":
        return NOTHING_TO_DO, None
    if proceed != "true":
        return FAILED, DETECT
    if will_deposit == "false":
        return NO_ACQUISITION, None
    if will_deposit != "true":
        return FAILED, DETECT
    if deposit == "success":
        return DEPOSITED, None
    if deposit == "cancelled":
        return CANCELLED, DEPOSIT
    return FAILED, DEPOSIT


def attempt(
    outcome: str,
    stage: str | None,
    *,
    run_number: str,
    repository: str,
    server: str = "https://github.com",
    now: datetime | None = None,
) -> dict[str, Any]:
    """One attempt, stamped with this process's clock."""

    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {
        "outcome": outcome,
        "stage": stage,
        "finished_utc": moment.strftime(STAMP),
        "run_id": f"ci-{run_number}",
        "run_url": f"{server}/{repository}/actions/runs/{run_number}",
    }


# ── the merge ────────────────────────────────────────────────────────────────


def _order(item: Mapping[str, Any]) -> tuple[str, int]:
    """Finish time, then run number — numeric, so ``ci-10`` follows ``ci-9``."""

    match = _RUN_ID.match(item["run_id"])
    return item["finished_utc"], int(match.group(1)) if match else -1


def _latest(*items: Mapping[str, Any] | None) -> dict[str, Any] | None:
    present = [dict(item) for item in items if item is not None]
    return max(present, key=_order) if present else None


def merge(current: Mapping[str, Any] | None, new: Mapping[str, Any]) -> dict[str, Any]:
    """The document after ``new``, given the stored ``current`` (or none).

    Two maxima, so ``merge(merge(c, a), b) == merge(merge(c, b), a)``.
    """

    latest = current["latest"] if current else None
    success = current["last_success"] if current else None
    return {
        "schema": SCHEMA,
        "lane": LANE,
        "latest": _latest(latest, new),
        "last_success": _latest(success, new if new["outcome"] in SUCCESSES else None),
    }


# ── the contract, read back ──────────────────────────────────────────────────


def check_heartbeat(document: Any) -> None:
    """Refuse a document that breaks the schema or the merge's two promises."""

    errors = sorted(
        schema_validator(SCHEMA_NAME).iter_errors(document),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        raise HeartbeatRejected(
            Finding(
                "schema",
                error.message,
                "/" + "/".join(str(part) for part in error.absolute_path),
            )
            for error in errors
        )

    findings = []
    for name in ("latest", "last_success"):
        item = document[name]
        if item is None:
            continue
        number = _RUN_ID.match(item["run_id"]).group(1)
        if not item["run_url"].endswith(f"/actions/runs/{number}"):
            findings.append(Finding(
                "run_url_names_another_run",
                f"{item['run_url']} is not the run {item['run_id']}",
                f"/{name}/run_url",
            ))
    latest, success = document["latest"], document["last_success"]
    if success is not None and _order(success) > _order(latest):
        findings.append(Finding(
            "last_success_after_latest",
            "the latest attempt is the greatest of all of them, so no "
            "successful attempt can finish after it",
            "/last_success",
        ))
    if latest["outcome"] in SUCCESSES and success != latest:
        findings.append(Finding(
            "successful_latest_is_not_last_success",
            "a successful latest attempt is also the latest successful one",
            "/last_success",
        ))
    if findings:
        raise HeartbeatRejected(findings)


def serialise(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def parse(body: bytes) -> dict[str, Any]:
    try:
        document = json.loads(body)
    except ValueError as exc:
        raise HeartbeatRejected(
            [Finding("not_json", str(exc))]
        ) from exc
    check_heartbeat(document)
    return document


# ── the write ────────────────────────────────────────────────────────────────


def record(store: cs.ConditionalStore, new: Mapping[str, Any]) -> Recorded:
    """Merge ``new`` into the stored heartbeat, by compare-and-swap.

    A stored document that breaks the contract is **refused, not replaced**:
    replacing it would discard ``last_success``, and a heartbeat that silently
    resets is worse than one that stops — a stopped one ages, and its age is
    the signal (``GREEN_HEARTBEAT_CONTRACT_V1.md`` §6).
    """

    # The new attempt is checked once, alone; the stored document is checked
    # on every read.  The merge of two valid documents is valid by
    # construction (``test_the_merge_is_commutative_over_every_order`` checks
    # every result), so re-checking it here would be a branch nothing reaches.
    check_heartbeat(merge(None, new))
    for tries in range(1, MAX_TRIES + 1):
        stored = store.get(HEARTBEAT_KEY)
        current = parse(stored.body) if stored is not None else None
        document = merge(current, new)
        body = serialise(document)
        try:
            if stored is None:
                # The pointer's create: a 412 here is a lost race even when the
                # bytes match, because a mutable object's identical bytes are
                # not idempotence — the next read decides.
                store.put_if_pointer_absent(HEARTBEAT_KEY, body, CONTENT_TYPE)
                return Recorded("created", tries, document)
            if stored.body == body:
                return Recorded("unchanged", tries, document)
            store.put_if_match(HEARTBEAT_KEY, body, CONTENT_TYPE, stored.etag)
            return Recorded("replaced", tries, document)
        except cs.PreconditionFailed:
            continue
    raise cs.ObjectStoreError(
        f"{HEARTBEAT_KEY} changed under every one of {MAX_TRIES} compare-and-swap "
        "attempts; something is writing it in a loop. Nothing was overwritten."
    )
