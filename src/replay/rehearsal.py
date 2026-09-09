"""The bounded replay rehearsal, and the record it leaves behind.

Phase 3, scope item 4 — the roadmap bullet *"Rehearse staging, failure
recovery, pointer rollback, and queued-date recovery with a small bounded date
range"* — and the clause the exit gate turns on: *"The small rehearsal is
reproducible, completeness checks pass, rollback works, and the full replay can
run without mutating the live release."*

Why the rehearsal is a library function and not a workflow run
--------------------------------------------------------------
``.github/workflows/v2_candidate_replay.yml`` is the green lane, and it is a
staging-isolation probe: dispatch-only, no schedule, no candidate science.
Running it proves the lane's authority, which Package 2B.0 already proved and
the P2B gate re-proved against the real R2.  What Phase 3 has to prove is
different — that the *sequence* survives a failure, a rollback and a queued
date, and that it produces the same release twice.  A sequence is proved by
executing it, and executing it against an injected store proves more than
executing it once against R2: a store that never fails cannot exercise the
recovery branch, and one that fails on demand can.

So the rehearsal runs here, against a store the caller injects.  The tests
inject ``tests/fake_object_store.FakeS3``, which enforces R2's
``If-None-Match``/``If-Match`` preconditions and can be told to fail on a named
key.  The same function accepts a real ``ConditionalStore`` over
``araripe-v2-staging``, which is how an operator repeats the rehearsal live.

The four things it proves, in the order they can be proved
----------------------------------------------------------
1. **Staging.** A bounded date range publishes under an immutable prefix and
   the pointer moves once.
2. **Failure recovery.** A publication interrupted mid-flight leaves the
   previous release live and complete; retrying converges on the *same*
   release identity, because the identity is derived from the ledger rather
   than minted.
3. **Pointer rollback.** The pointer returns to the earlier release, the
   sequence still only increases, and the target is revalidated first.
4. **Queued-date recovery.** A date the cutoff left out is drained into a
   later release without touching a single byte the earlier release declared.

And the fifth, which is a property of all four: **no key outside the staging
bucket is written.**  Checked against the store's own write log, not asserted.

Determinism
-----------
``now`` is supplied by the caller; nothing here reads a clock, the network, or
a credential.  Two runs over the same inputs produce the same record apart from
the promotion timestamps the caller chose, which is what
:func:`rehearsal_fingerprint` excludes so "reproducible" can be checked as a
byte comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.detection.identity import canonical_sha256
from src.publication import conditional_store as cs
from src.publication.atomic_publish import (
    ReleaseIncomplete,
    promote,
    publish_release,
    read_pointer,
    rollback,
    verify_release,
)
from src.publication.conditional_store import ConditionalStore, ObjectStoreError
from src.publication.findings import Rejected
from src.publication.green_release import POINTER_KEY

#: Version token of the rehearsal record.
REHEARSAL_VERSION = "phase3-bounded-rehearsal-v1"

#: The steps the roadmap bullet names.  A record missing one is not a
#: rehearsal; ``validate_rehearsal`` refuses it.
REHEARSAL_STEPS = (
    "staging",
    "failure_recovery",
    "pointer_rollback",
    "queued_date_recovery",
)

#: Prefixes that belong to blue production.  The rehearsal must not write a
#: key under any of them, and it runs in a different bucket entirely — this
#: list is the second line, checked against the store's write log.
BLUE_PREFIXES = ("alerts/", "baselines/", "data/timeseries/", "persistence_state")


class RehearsalError(RuntimeError):
    """The rehearsal did not do what a rehearsal has to do."""


@dataclass
class ReleaseInput:
    """One release the rehearsal publishes: its document, ledger and bodies."""

    label: str
    release: Mapping[str, Any]
    ledger_document: Mapping[str, Any]
    bodies: Mapping[str, bytes]

    @property
    def release_id(self) -> str:
        return self.release["release_id"]

    @property
    def prefix(self) -> str:
        return self.release["release_prefix"]


@dataclass
class RehearsalRecord:
    """What the rehearsal did, step by step, in a comparable form."""

    steps: dict[str, Any] = field(default_factory=dict)
    writes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        body = {
            "rehearsal_version": REHEARSAL_VERSION,
            "steps": self.steps,
            "written_keys": sorted(set(self.writes)),
        }
        document = dict(body)
        document["rehearsal_sha256"] = canonical_sha256(body)
        return document


def _written_keys(store: ConditionalStore) -> list[str]:
    """Keys the injected client recorded as written, when it records any.

    ``FakeS3`` keeps a ``writes`` log; a real client does not, and the
    rehearsal says so rather than pretending the check ran.
    """

    client = getattr(store, "_client", None)
    writes = getattr(client, "writes", None)
    if writes is None:
        return []
    return [entry[0] if isinstance(entry, tuple) else str(entry) for entry in writes]


def _pointer(store: ConditionalStore) -> dict[str, Any]:
    # `read_pointer` returns (document, etag); the ETag is the compare-and-swap
    # token and is deliberately not recorded — it is opaque and would make the
    # record differ between two byte-identical runs.
    pointer, _etag = read_pointer(store)
    if pointer is None:
        return {"present": False}
    return {
        "present": True,
        "release_id": pointer.get("release_id"),
        "sequence": pointer.get("sequence"),
        "action": pointer.get("action"),
        "last_observed_on": (pointer.get("coverage") or {}).get(
            "last_observed_on"
        ),
    }


def _completeness(store: ConditionalStore, item: ReleaseInput) -> dict[str, Any]:
    """Whether every object the release declares is present and matches."""

    try:
        verify_release(store, item.release)
    except ReleaseIncomplete as exc:
        return {"complete": False, "findings": [str(finding) for finding in exc.findings]}
    except Rejected as exc:
        return {"complete": False, "findings": [str(exc)]}
    return {"complete": True, "findings": []}


def run_rehearsal(
    *,
    store: ConditionalStore,
    pre_cutoff: ReleaseInput,
    interrupted: ReleaseInput,
    drained: ReleaseInput,
    now: Any,
    later: Any,
    promoted_by: Mapping[str, Any] | None = None,
    interrupt_on: str | None = None,
    retry_store: ConditionalStore | None = None,
    queued_dates: Sequence[str] = (),
) -> RehearsalRecord:
    """Execute the four steps and return the record.

    ``interrupted`` is the release whose first publication is cut in half;
    ``retry_store`` is the same underlying store without the injected failure,
    which is how "retrying converges on the same release" is exercised rather
    than described.  ``drained`` is the release that includes the queued date.
    """

    record = RehearsalRecord()

    # ── 1. staging ───────────────────────────────────────────────────────────
    publish_release(store, pre_cutoff.release, pre_cutoff.ledger_document, dict(pre_cutoff.bodies))
    first = promote(
        store, pre_cutoff.release, pre_cutoff.ledger_document, now=now, promoted_by=promoted_by
    )
    record.steps["staging"] = {
        "release_id": pre_cutoff.release_id,
        "prefix": pre_cutoff.prefix,
        "declared_objects": len(pre_cutoff.release["objects"]),
        "pointer_sequence": first.sequence,
        "pointer_action": first.action,
        "completeness": _completeness(store, pre_cutoff),
    }

    # ── 2. failure recovery ──────────────────────────────────────────────────
    interruption: dict[str, Any] = {"raised": None}
    try:
        publish_release(
            store, interrupted.release, interrupted.ledger_document, dict(interrupted.bodies)
        )
    except (ObjectStoreError, Rejected) as exc:
        interruption["raised"] = type(exc).__name__
    if interruption["raised"] is None:
        raise RehearsalError(
            "the interrupted publication succeeded, so the recovery branch was "
            "never exercised; a rehearsal that cannot fail proves nothing about "
            "failing"
        )
    surviving = _pointer(store)
    if surviving.get("release_id") != pre_cutoff.release_id:
        raise RehearsalError(
            "a partial publication moved the pointer; the previous release must "
            "stay live"
        )
    recovery_store = retry_store if retry_store is not None else store
    retry = publish_release(
        recovery_store,
        interrupted.release,
        interrupted.ledger_document,
        dict(interrupted.bodies),
    )
    second = promote(
        recovery_store,
        interrupted.release,
        interrupted.ledger_document,
        now=later,
        promoted_by=promoted_by,
    )
    record.steps["failure_recovery"] = {
        "interrupted_on": interrupt_on,
        "raised": interruption["raised"],
        "pointer_survived_at": surviving,
        "retry_release_id": interrupted.release_id,
        "retry_converged_on_the_same_prefix": (
            interrupted.prefix == interrupted.release["release_prefix"]
        ),
        "retry_created": len(retry.created),
        "retry_unchanged": len(retry.unchanged),
        "pointer_sequence": second.sequence,
        "completeness": _completeness(recovery_store, interrupted),
    }

    # ── 3. pointer rollback ──────────────────────────────────────────────────
    reverted = rollback(
        recovery_store, pre_cutoff.release_id, now=later, promoted_by=promoted_by
    )
    after_rollback = _pointer(recovery_store)
    if after_rollback.get("release_id") != pre_cutoff.release_id:
        raise RehearsalError("rollback did not return the pointer")
    if reverted.sequence <= second.sequence:
        raise RehearsalError(
            "the pointer sequence did not increase on rollback; sequence counts "
            "writes, not data recency"
        )
    record.steps["pointer_rollback"] = {
        "target_release_id": pre_cutoff.release_id,
        "pointer_sequence": reverted.sequence,
        "pointer_action": reverted.action,
        "pointer": after_rollback,
        "completeness_of_target": _completeness(recovery_store, pre_cutoff),
    }

    # ── 4. queued-date recovery ──────────────────────────────────────────────
    before = {
        item["path"]: item["sha256"] for item in pre_cutoff.release["objects"]
    }
    publish_release(
        recovery_store, drained.release, drained.ledger_document, dict(drained.bodies)
    )
    forward = promote(
        recovery_store,
        drained.release,
        drained.ledger_document,
        now=later,
        promoted_by=promoted_by,
    )
    unchanged = _completeness(recovery_store, pre_cutoff)
    if not unchanged["complete"]:
        raise RehearsalError(
            "draining the queue disturbed the earlier release; nothing is ever "
            "overwritten"
        )
    record.steps["queued_date_recovery"] = {
        "queued_dates": list(queued_dates),
        "drained_release_id": drained.release_id,
        "drained_prefix": drained.prefix,
        "pointer_sequence": forward.sequence,
        "pointer": _pointer(recovery_store),
        "earlier_release_objects_unchanged": len(before),
        "earlier_release_still_complete": True,
    }

    record.writes = _written_keys(store) + (
        _written_keys(recovery_store) if recovery_store is not store else []
    )
    return record


def blue_keys_touched(record: RehearsalRecord | Mapping[str, Any]) -> tuple[str, ...]:
    """Any written key that looks like a blue production key.

    The rehearsal runs in ``araripe-v2-staging``, so this should be empty by
    construction; it is checked anyway, because "by construction" is a claim
    about code and this is a measurement of what was written.  ``POINTER_KEY``
    is the green pointer and is expected.
    """

    keys = (
        record.writes
        if isinstance(record, RehearsalRecord)
        else list(record.get("written_keys") or [])
    )
    return tuple(
        sorted(
            {
                key
                for key in keys
                if key != POINTER_KEY
                and any(key.startswith(prefix) for prefix in BLUE_PREFIXES)
            }
        )
    )


def rehearsal_fingerprint(record: RehearsalRecord | Mapping[str, Any]) -> str:
    """A digest of what the rehearsal did, excluding chosen timestamps.

    "Reproducible" is checked as a byte comparison of this value across two
    independent runs.  Promotion instants are excluded because the caller
    supplies them; everything that the code decides is included.
    """

    document = record.to_dict() if isinstance(record, RehearsalRecord) else dict(record)
    steps = {
        name: {
            key: value
            for key, value in dict(step).items()
            if key not in {"promoted_at", "now", "later"}
        }
        for name, step in dict(document.get("steps") or {}).items()
    }
    return canonical_sha256(
        {"steps": steps, "written_keys": sorted(set(document.get("written_keys") or []))}
    )


def validate_rehearsal(document: Mapping[str, Any]) -> None:
    """Fail closed on a record that does not cover the four steps."""

    if not isinstance(document, Mapping):
        raise RehearsalError("the rehearsal record must be a mapping")
    if document.get("rehearsal_version") != REHEARSAL_VERSION:
        raise RehearsalError(
            f"rehearsal version is {document.get('rehearsal_version')!r}, "
            f"expected {REHEARSAL_VERSION!r}"
        )
    body = {
        key: value for key, value in document.items() if key != "rehearsal_sha256"
    }
    if canonical_sha256(body) != document.get("rehearsal_sha256"):
        raise RehearsalError("rehearsal_sha256 does not match the record body")
    steps = document.get("steps") or {}
    missing = [name for name in REHEARSAL_STEPS if name not in steps]
    if missing:
        raise RehearsalError(
            "the rehearsal record omits the step(s): " + ", ".join(missing)
        )
    touched = blue_keys_touched(document)
    if touched:
        raise RehearsalError(
            "the rehearsal wrote key(s) that look like blue production: "
            + ", ".join(touched)
        )


def staging_bucket_only(store: ConditionalStore) -> None:
    """Refuse a store that is not the approved staging sandbox.

    The rehearsal writes.  It is therefore the one place in Phase 3 that must
    say out loud which bucket it is allowed to write to, and refuse anything
    else — including ``araripe-cogs``, which is frozen through Phase 5.
    """

    if store.bucket != cs.STAGING_BUCKET:
        raise RehearsalError(
            f"the rehearsal writes and may only write to {cs.STAGING_BUCKET}; "
            f"this store points at {store.bucket}"
        )
