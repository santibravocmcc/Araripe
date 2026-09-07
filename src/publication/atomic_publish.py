"""Atomic green publication: write immutably, verify, then move the pointer.

Roadmap Package 2B.2, and the clause the P2B exit gate turns on — *a
deliberately failed or racing green run cannot corrupt blue or expose a
partial release; a staged test release can move and roll back its green
pointer without a manual data PR or any production effect.*

The order is the whole mechanism
--------------------------------
Objects go out first, under an immutable prefix, each with
``If-None-Match: *``.  The release manifest is written **last**, so a prefix
without a manifest is visibly unfinished.  Then every declared object is
**re-read** and compared against its declared size and checksum.  Only after
all of that does the pointer move, in one compare-and-swap.

Nothing in that sequence can expose a partial release, because the pointer is
the only thing a consumer follows and it is written once, at the end, or not
at all.  A run that dies at any earlier step leaves the previous release live
and complete — that is bullet 4 ("keep the last complete release live when a
run is partial or fails") and bullet 3 ("conditional writes so older/racing
jobs cannot replace a newer release") turning out to be the same property seen
from two sides.

Two axes, deliberately not conflated
------------------------------------
``sequence`` counts pointer *writes* and only ever increases, rollback
included.  Which *data* is newer is a different question, answered by the
release's ``coverage.last_observed_on``.  Conflating them is the trap: a
replay of an old window is a *later write* of *older data*, so a
sequence-based "is this newer?" would happily let it overwrite a current
release.  ``promote`` therefore refuses to move to strictly older coverage,
and ``rollback`` is the explicit — and only — way to go backwards.

Why a compare-and-swap when the promotion lane is already serialized
--------------------------------------------------------------------
``docs/operations/GREEN_CONCURRENCY_LANES.md`` lane 3 gives at most one
running promotion.  The CAS sits *behind* that, not instead of it: the lane is
per repository, so a local operator run, a re-dispatch from another ref, or a
future second promoter is outside it.  A precondition failure is never
retried — the decision behind the write was made about a version that is no
longer live.

Nothing is ever deleted here.  A superseded object is recorded as a tombstone
on the pointer; retention and lifecycle are Package 2B.3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.publication.conditional_store import (
    ConditionalStore,
    ObjectStoreError,
    PutOutcome,
    StoredObject,
)
from src.publication.findings import Finding, Rejected
from src.publication.green_release import (
    LEDGER_CONTENT_TYPE,
    LEDGER_PATH,
    MANIFEST_PATH,
    POINTER_KEY,
    POINTER_SCHEMA,
    RELEASE_CONTENT_TYPE,
    check_green_release,
    ledger_bytes,
    object_key,
    release_bytes,
    schema_validator,
    sha256_bytes,
)

POINTER_CONTENT_TYPE = "application/json"


class ReleaseIncomplete(Rejected):
    """The store does not hold everything the release manifest declares."""

    subject = "published release"


class PromotionRefused(Rejected):
    """The pointer must not move to this release."""

    subject = "green pointer promotion"


@dataclass(frozen=True)
class PublishReport:
    release_id: str
    outcomes: tuple[PutOutcome, ...]

    @property
    def created(self) -> tuple[str, ...]:
        return tuple(o.key for o in self.outcomes if o.result == "created")

    @property
    def unchanged(self) -> tuple[str, ...]:
        return tuple(o.key for o in self.outcomes if o.result == "unchanged")


@dataclass(frozen=True)
class Promotion:
    action: str
    release_id: str
    sequence: int
    previous_release_id: str | None
    tombstone_count: int
    pointer: dict[str, Any]


# ── publish ──────────────────────────────────────────────────────────────────

def publish_release(
    store: ConditionalStore,
    document: Mapping[str, Any],
    ledger_document: Mapping[str, Any],
    bodies: Mapping[str, bytes],
) -> PublishReport:
    """Write a release's objects, its ledger and its manifest, write-once.

    ``bodies`` is keyed by logical path and must match the manifest's declared
    object set exactly — an offered body the manifest does not declare would
    be an unverifiable object under a release prefix, and a declared object
    with no body would be a manifest promising what was never written.
    """

    release_id = document["release_id"]
    declared = {item["path"]: item for item in document["objects"]}
    missing = sorted(set(declared) - set(bodies))
    extra = sorted(set(bodies) - set(declared))
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"declared but not offered: {', '.join(missing)}")
        if extra:
            detail.append(f"offered but not declared: {', '.join(extra)}")
        raise ObjectStoreError(
            "the bodies offered do not match the release manifest — "
            + "; ".join(detail)
        )

    for path, item in declared.items():
        body = bodies[path]
        if len(body) != item["bytes"] or sha256_bytes(body) != item["sha256"]:
            raise ObjectStoreError(
                f"{path!r} does not match what the manifest declares "
                f"({len(body)} bytes / {sha256_bytes(body)[:12]}… against "
                f"{item['bytes']} bytes / {item['sha256'][:12]}…)"
            )

    outcomes: list[PutOutcome] = []
    for path in sorted(declared):
        outcomes.append(
            store.put_if_absent(
                object_key(release_id, path),
                bodies[path],
                declared[path]["content_type"],
            )
        )
    outcomes.append(
        store.put_if_absent(
            object_key(release_id, LEDGER_PATH),
            ledger_bytes(dict(ledger_document)),
            LEDGER_CONTENT_TYPE,
        )
    )
    # The manifest last, so an interrupted publication leaves a prefix that is
    # visibly unfinished rather than one that looks complete.
    outcomes.append(
        store.put_if_absent(
            object_key(release_id, MANIFEST_PATH),
            release_bytes(dict(document)),
            RELEASE_CONTENT_TYPE,
        )
    )
    return PublishReport(release_id, tuple(outcomes))


# ── verify ───────────────────────────────────────────────────────────────────

def verify_release(
    store: ConditionalStore, document: Mapping[str, Any]
) -> tuple[StoredObject, ...]:
    """Re-read everything the manifest declares and check it byte for byte.

    Declared-and-absent, wrong size and wrong checksum are collected rather
    than raised one at a time: an operator needs to know whether one object is
    missing or the whole prefix is, and Package 2B.1's first-failure validator
    is the reason that is a rule here
    (``docs/implementation/PHASE_2B1_2026-09-06.md`` §1).

    Re-reading rather than trusting the write is the point.  A ``PutObject``
    that returned 200 is not proof the bytes a consumer will fetch are the
    bytes declared, and the pointer must not move on an unproven release.
    """

    release_id = document["release_id"]
    findings: list[Finding] = []
    stored: list[StoredObject] = []

    checks: list[tuple[str, int, str]] = [
        (item["path"], item["bytes"], item["sha256"]) for item in document["objects"]
    ]
    checks.append(
        (LEDGER_PATH, document["ledger"]["bytes"], document["ledger"]["file_sha256"])
    )
    manifest = release_bytes(dict(document))
    checks.append((MANIFEST_PATH, len(manifest), sha256_bytes(manifest)))

    for path, size, digest in checks:
        key = object_key(release_id, path)
        try:
            found = store.get(key)
        except ObjectStoreError as exc:
            findings.append(
                Finding("release_object_unreadable", str(exc), path)
            )
            continue
        if found is None:
            findings.append(
                Finding(
                    "release_object_absent",
                    f"{key} is declared by the manifest and is not in the store",
                    path,
                )
            )
            continue
        actual = sha256_bytes(found.body)
        if found.size != size or actual != digest:
            findings.append(
                Finding(
                    "release_object_mismatch",
                    f"{key} holds {found.size} bytes / {actual[:12]}… but the "
                    f"manifest declares {size} bytes / {digest[:12]}…",
                    path,
                )
            )
            continue
        stored.append(found)

    if findings:
        raise ReleaseIncomplete(findings)
    return tuple(stored)


# ── the pointer ──────────────────────────────────────────────────────────────

def read_pointer(store: ConditionalStore) -> tuple[dict[str, Any] | None, str | None]:
    """The live pointer and the ETag to compare against, or ``(None, None)``.

    An unparseable or non-conforming pointer raises instead of being treated
    as absent.  Reading a pointer this code cannot understand as "there is no
    pointer" would overwrite a live release — possibly one written by a newer
    version of this contract.
    """

    stored = store.get(POINTER_KEY)
    if stored is None:
        return None, None
    try:
        document = json.loads(stored.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ObjectStoreError(
            f"the live pointer {POINTER_KEY} is not valid JSON ({exc}); refusing "
            "to treat an unreadable pointer as an absent one"
        ) from exc
    if not isinstance(document, dict) or document.get("schema") != POINTER_SCHEMA:
        raise ObjectStoreError(
            f"the live pointer declares {document.get('schema')!r} rather than "
            f"{POINTER_SCHEMA!r}; refusing to overwrite a pointer this code does "
            "not understand"
        )
    errors = sorted(
        schema_validator("green-pointer-v1").iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ObjectStoreError(
            f"the live pointer does not satisfy {POINTER_SCHEMA}: "
            + "; ".join(
                f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
                for e in errors[:4]
            )
        )
    return document, stored.etag


def load_published_release(
    store: ConditionalStore, release_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read a published release and revalidate it from the stored bytes.

    Both documents come out of the store, not out of the caller's memory, and
    the manifest is required to be exactly its canonical encoding — the bytes
    a consumer would fetch are the bytes validated here.
    """

    manifest_key = object_key(release_id, MANIFEST_PATH)
    stored = store.require(manifest_key)
    try:
        document = json.loads(stored.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ObjectStoreError(f"{manifest_key} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ObjectStoreError(
            f"{manifest_key} is a {type(document).__name__}, expected an object"
        )
    if release_bytes(document) != stored.body:
        raise ObjectStoreError(
            f"{manifest_key} is not stored as the canonical encoding of its own "
            "content, so its declared digest describes bytes no consumer reads"
        )
    ledger_key = object_key(release_id, LEDGER_PATH)
    ledger_stored = store.require(ledger_key)
    try:
        ledger_document = json.loads(ledger_stored.body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ObjectStoreError(f"{ledger_key} is not valid JSON: {exc}") from exc

    check_green_release(document, ledger_document)
    if document["release_id"] != release_id:
        raise ObjectStoreError(
            f"{manifest_key} declares {document['release_id']}, which is not the "
            "release the key addresses"
        )
    return document, ledger_document


def tombstones(previous: Mapping[str, Any], successor: Mapping[str, Any]) -> list[dict]:
    """Objects of ``previous`` that ``successor`` retires.

    Staleness is a **relation between two releases**, which is why it is
    recorded on the pointer and not in either manifest: a release is immutable
    and is built before anything is known about what it will supersede, and
    what counts as stale depends on which release is live when it is promoted.

    Three reasons, kept distinct because a consumer must treat them
    differently:

    * ``absent_from_successor`` — the successor publishes nothing at that
      logical path.
    * ``superseded_content`` — same logical path, different bytes.
    * ``date_reclassified`` — the successor reports a different
      ``alert_state`` for that UTC date.  This is the one that matters
      scientifically: a replay that retracts a date's alerts, or that turns an
      observed quiet day into one nobody could observe, must never be silent.
    """

    old_id = previous["release_id"]
    old_objects = {item["path"]: item for item in previous["objects"]}
    new_objects = {item["path"]: item for item in successor["objects"]}
    old_states = {entry["observed_on"]: entry["alert_state"] for entry in previous["dates"]}
    new_states = {entry["observed_on"]: entry["alert_state"] for entry in successor["dates"]}

    out: list[dict] = []
    for path in sorted(old_objects):
        item = old_objects[path]
        observed_on = item["provenance"]["observed_on"]
        entry: dict[str, Any] = {
            "key": object_key(old_id, path),
            "superseded_release_id": old_id,
            "observed_on": observed_on,
        }
        replacement = new_objects.get(path)
        if replacement is None:
            out.append({**entry, "reason": "absent_from_successor"})
        elif replacement["sha256"] != item["sha256"]:
            out.append(
                {
                    **entry,
                    "reason": "superseded_content",
                    "detail": f"sha256 {item['sha256'][:12]}… replaced by "
                    f"{replacement['sha256'][:12]}…",
                }
            )
        elif new_states.get(observed_on) != old_states.get(observed_on):
            out.append(
                {
                    **entry,
                    "reason": "date_reclassified",
                    "detail": f"{old_states.get(observed_on)} → "
                    f"{new_states.get(observed_on)}",
                }
            )
    # A date whose classification changed but which published no object still
    # has to be visible: a zero-alert date that becomes unobservable retires a
    # claim even though it retires no bytes.
    published_dates = {
        item["provenance"]["observed_on"] for item in old_objects.values()
    }
    for observed_on in sorted(old_states):
        if observed_on in published_dates:
            continue
        if new_states.get(observed_on) != old_states[observed_on]:
            out.append(
                {
                    "key": object_key(old_id, MANIFEST_PATH),
                    "superseded_release_id": old_id,
                    "observed_on": observed_on,
                    "reason": "date_reclassified",
                    "detail": f"{old_states[observed_on]} → "
                    f"{new_states.get(observed_on)}",
                }
            )
    return out


def _pointer_document(
    document: Mapping[str, Any],
    *,
    action: str,
    sequence: int,
    now: Any,
    promoted_by: Mapping[str, Any] | None,
    supersedes: dict[str, Any] | None,
    stones: Iterable[Mapping[str, Any]],
    rolled_back_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = dict(promoted_by or {})
    pointer = {
        "schema": POINTER_SCHEMA,
        "sequence": sequence,
        "action": action,
        "release_id": document["release_id"],
        "release_path": object_key(document["release_id"], MANIFEST_PATH),
        "release_document_sha256": sha256_bytes(release_bytes(dict(document))),
        "ledger_id": document["ledger"]["ledger_id"],
        "run_manifest_id": document["ledger"]["run_manifest_id"],
        "coverage": dict(document["coverage"]),
        "state_watermark": {
            "finalized_through": document["state_watermark"]["finalized_through"]
        },
        "promoted_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "promoted_by": {
            "workflow": provenance.get("workflow"),
            "run_id": provenance.get("run_id"),
            "run_url": provenance.get("run_url"),
            "actor": provenance.get("actor"),
        },
        "supersedes": supersedes,
        "tombstones": [dict(stone) for stone in stones],
    }
    if action == "rollback":
        pointer["rolled_back_from"] = rolled_back_from
    return pointer


def _write_pointer(
    store: ConditionalStore, pointer: Mapping[str, Any], etag: str | None
) -> None:
    errors = list(schema_validator("green-pointer-v1").iter_errors(pointer))
    if errors:
        raise PromotionRefused(
            Finding(
                "pointer_schema_invalid",
                error.message,
                "/".join(str(part) for part in error.absolute_path) or "<root>",
            )
            for error in errors
        )
    body = release_bytes(dict(pointer))
    if etag is None:
        store.put_if_pointer_absent(POINTER_KEY, body, POINTER_CONTENT_TYPE)
    else:
        store.put_if_match(POINTER_KEY, body, POINTER_CONTENT_TYPE, etag)


def _supersedes(live: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if live is None:
        return None
    return {
        "release_id": live["release_id"],
        "sequence": live["sequence"],
        "last_observed_on": live["coverage"]["last_observed_on"],
    }


def promote(
    store: ConditionalStore,
    document: Mapping[str, Any],
    ledger_document: Mapping[str, Any],
    *,
    now: Any,
    promoted_by: Mapping[str, Any] | None = None,
) -> Promotion:
    """Validate, verify and then move the green pointer to ``document``.

    Refuses to move to strictly older data coverage.  That is the "an older or
    racing job cannot replace a newer release" bullet, and it is a *data*
    comparison rather than a clock or sequence comparison on purpose: a replay
    of an old window is a later write of older data, and any recency test
      based on write order would wave it through.

    Going backwards deliberately is ``rollback``.  There is no override flag
    here, so a regression is always a named, separate operation in the log
    rather than a parameter someone passed.
    """

    check_green_release(document, ledger_document)
    verify_release(store, document)

    live, etag = read_pointer(store)
    if live is not None and live["release_id"] == document["release_id"]:
        return Promotion(
            "unchanged",
            document["release_id"],
            live["sequence"],
            live.get("supersedes", {}).get("release_id")
            if isinstance(live.get("supersedes"), dict)
            else None,
            len(live["tombstones"]),
            live,
        )

    stones: list[dict[str, Any]] = []
    if live is not None:
        candidate_through = document["coverage"]["last_observed_on"]
        live_through = live["coverage"]["last_observed_on"]
        if candidate_through < live_through:
            raise PromotionRefused(
                [
                    Finding(
                        "coverage_regression",
                        f"the candidate covers through {candidate_through} while "
                        f"the live release {live['release_id']} covers through "
                        f"{live_through}. An older run may not replace a newer "
                        "release; use rollback to move the pointer backwards "
                        "deliberately.",
                        "coverage/last_observed_on",
                    )
                ]
            )
        previous, _ = load_published_release(store, live["release_id"])
        if sha256_bytes(release_bytes(previous)) != live["release_document_sha256"]:
            raise PromotionRefused(
                [
                    Finding(
                        "live_release_unverifiable",
                        f"the manifest stored for the live release "
                        f"{live['release_id']} does not match the digest the "
                        "pointer records, so which objects this promotion would "
                        "retire cannot be established",
                        "release_document_sha256",
                    )
                ]
            )
        stones = tombstones(previous, document)

    sequence = 1 if live is None else live["sequence"] + 1
    pointer = _pointer_document(
        document,
        action="promote",
        sequence=sequence,
        now=now,
        promoted_by=promoted_by,
        supersedes=_supersedes(live),
        stones=stones,
    )
    _write_pointer(store, pointer, etag)
    return Promotion(
        "promote",
        document["release_id"],
        sequence,
        None if live is None else live["release_id"],
        len(stones),
        pointer,
    )


def rollback(
    store: ConditionalStore,
    release_id: str,
    *,
    now: Any,
    promoted_by: Mapping[str, Any] | None = None,
) -> Promotion:
    """Point the green pointer at an already published release, deliberately.

    The target is loaded **from the store** and revalidated in full, including
    its ledger, and every object it declares is verified present: the pointer
    may only ever name a release that is still complete.  "Roll back" is the
    general name for a deliberate non-monotonic move, so it is also how an
    operator promotes a release with older coverage on purpose.
    """

    document, ledger_document = load_published_release(store, release_id)
    verify_release(store, document)

    live, etag = read_pointer(store)
    if live is None:
        raise PromotionRefused(
            [
                Finding(
                    "no_live_pointer",
                    "there is no live green pointer to roll back from; the first "
                    "move into an empty pointer is a promotion",
                    "pointers/green/current.json",
                )
            ]
        )
    if live["release_id"] == release_id:
        return Promotion(
            "unchanged",
            release_id,
            live["sequence"],
            None,
            len(live["tombstones"]),
            live,
        )

    previous, _ = load_published_release(store, live["release_id"])
    if sha256_bytes(release_bytes(previous)) != live["release_document_sha256"]:
        raise PromotionRefused(
            [
                Finding(
                    "live_release_unverifiable",
                    f"the manifest stored for the live release "
                    f"{live['release_id']} does not match the digest the pointer "
                    "records",
                    "release_document_sha256",
                )
            ]
        )
    stones = tombstones(previous, document)
    sequence = live["sequence"] + 1
    pointer = _pointer_document(
        document,
        action="rollback",
        sequence=sequence,
        now=now,
        promoted_by=promoted_by,
        supersedes=_supersedes(live),
        stones=stones,
        rolled_back_from={
            "release_id": live["release_id"],
            "sequence": live["sequence"],
        },
    )
    _write_pointer(store, pointer, etag)
    return Promotion(
        "rollback", release_id, sequence, live["release_id"], len(stones), pointer
    )
