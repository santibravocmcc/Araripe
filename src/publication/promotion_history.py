"""The durable promotion history: one immutable copy per accepted pointer write.

Phase 6, decision D5 (``config/phase6_owner_decisions_v1.json``), specified in
``docs/implementation/PHASE_2B3_2026-09-07.md`` and designed, before any code,
in ``docs/implementation/PHASE_6C_2026-09-27.md`` §2.

Why it exists
-------------
``pointers/green/current.json`` is the one mutable object in the green layout
and carries a single step of context (``supersedes``, ``rolled_back_from``).
One pointer write after a release stops being live, nothing in the store can
say it ever was: measured on 2026-09-16, when ``rel-g1-2ddb10c7…`` — live as
sequence 8 — dropped out of the pointer and survived only because a record
was copied into a document by hand.

What a record is
----------------
``pointers/green/history/<sequence>.json`` holds **the exact bytes** of the
pointer as it was accepted at that sequence — the same schema, no envelope.
Anything added (an instant of recording, say) would make the two writers of a
record disagree about its bytes, and they must not: see "the protocol".

The key is a function of the sequence **only**.  The sequence is unique per
accepted write — the compare-and-swap orders accepted writes totally, the
first one is 1 and each later one is its predecessor's plus one — so one key
per accepted write.  A key that also carried the release id would let two
different bodies claim one sequence without colliding; with the sequence
alone, the write-once precondition turns a write made outside the protocol
into a refusal instead of a second record.

The protocol, and the two properties it keeps
---------------------------------------------
``atomic_publish`` moves the pointer in three writes: (1) record the version
about to be replaced, from the bytes it read; (2) the compare-and-swap; (3)
record the new version, from the bytes the swap accepted.

* **H1 — no record of a write that did not happen.**  A record is only ever
  written from bytes the swap just accepted, or from bytes read as the live
  pointer — which is an accepted write by definition.
* **H2 — no version replaced without its record.**  Step 1 precedes step 2 in
  the same process, and step 2 is accepted only if the pointer is still exactly
  the version step 1 recorded.

So the only record a store written under the protocol can lack is the **live**
version's own — at most one, always the newest — and the live pointer holds
its bytes.  The reader below treats it as pending, not missing.

Nothing here deletes, and nothing here writes without a precondition: the one
write is ``ConditionalStore.put_if_absent``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from src.publication.conditional_store import ConditionalStore, PutOutcome
from src.publication.findings import Finding
from src.publication.green_release import POINTER_SCHEMA, schema_validator

HISTORY_ROOT = "pointers/green/history/"
HISTORY_CONTENT_TYPE = "application/json"

#: Zero-padded so that a lexicographic listing is the numeric order.  Ten
#: digits is some 10**10 pointer writes; a sequence beyond that is refused
#: rather than given a key that would sort in the wrong place.
SEQUENCE_DIGITS = 10

_KEY = re.compile(r"^pointers/green/history/([0-9]{%d})\.json$" % SEQUENCE_DIGITS)


def history_key(sequence: int) -> str:
    """The one key a record of ``sequence`` may live at."""

    if (
        not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 1
        or sequence >= 10**SEQUENCE_DIGITS
    ):
        raise ValueError(
            f"a pointer sequence is an integer from 1 to {10**SEQUENCE_DIGITS - 1}, "
            f"got {sequence!r}"
        )
    return f"{HISTORY_ROOT}{sequence:0{SEQUENCE_DIGITS}d}.json"


def sequence_of(key: str) -> int | None:
    """The sequence a history key records, or ``None`` if it is not one."""

    match = _KEY.match(key)
    if match is None:
        return None
    value = int(match.group(1))
    return value if value >= 1 else None


def record(store: ConditionalStore, sequence: int, body: bytes) -> PutOutcome:
    """Write the record of ``sequence`` once, or accept the identical bytes.

    ``put_if_absent`` is the whole mechanism: the same bytes a second time are
    ``unchanged`` (two writers of one record always offer the same bytes,
    because both copy the pointer that was accepted), and different bytes
    raise ``ImmutableObjectConflict`` — a record is never rewritten.
    """

    return store.put_if_absent(history_key(sequence), body, HISTORY_CONTENT_TYPE)


# ── reading ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Entry:
    """One version of the pointer the history can vouch for."""

    sequence: int
    action: str
    release_id: str
    promoted_utc: str
    #: ``False`` only for the live version whose record is still pending — the
    #: one record the protocol allows to be missing, whose bytes are the live
    #: pointer itself.
    recorded: bool


@dataclass(frozen=True)
class History:
    """What the store says about every pointer version since the history began."""

    live_sequence: int | None
    #: The lowest sequence with a record.  Below it is pre-history: versions
    #: replaced before this module existed, whose bytes are gone.
    first_recorded: int | None
    entries: tuple[Entry, ...]
    #: The first entry's own ``supersedes``: the version live just before the
    #: history begins, which is the one fact about pre-history the store keeps.
    predecessor: Mapping[str, Any] | None
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def consistent(self) -> bool:
        return not self.findings

    @property
    def live_record_pending(self) -> bool:
        return any(
            entry.sequence == self.live_sequence and not entry.recorded
            for entry in self.entries
        )

    def sequences_of(self, release_id: str) -> tuple[int, ...]:
        """Every sequence at which ``release_id`` was the live release."""

        return tuple(e.sequence for e in self.entries if e.release_id == release_id)

    def release_ids(self) -> frozenset[str]:
        return frozenset(entry.release_id for entry in self.entries)


def _parse(body: bytes) -> Any:
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


def _pointer_errors(document: Any) -> list[str]:
    if not isinstance(document, dict) or document.get("schema") != POINTER_SCHEMA:
        return [f"it does not declare {POINTER_SCHEMA!r}"]
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(
            schema_validator("green-pointer-v1").iter_errors(document),
            key=lambda error: list(error.absolute_path),
        )
    ]


def _own_findings(version: Mapping[str, Any], where: str) -> list[Finding]:
    """What one version must say about its predecessor, read on its own.

    Each rule is something ``atomic_publish`` itself guarantees when it builds
    a pointer, so a version breaking one was not written by it: the first
    write into an empty pointer is a promotion that replaced nothing, every
    later write names the sequence just below it, and a rollback names, in
    ``rolled_back_from``, the same release its ``supersedes`` names.
    """

    sequence = version["sequence"]
    supersedes = version.get("supersedes")
    if sequence == 1:
        if supersedes is not None or version["action"] != "promote":
            return [
                Finding(
                    "history_chain_broken",
                    "sequence 1 is the first write into an empty pointer: a "
                    "promotion that replaced nothing",
                    where,
                )
            ]
        return []
    if supersedes is None or supersedes["sequence"] != sequence - 1:
        return [
            Finding(
                "history_chain_broken",
                f"sequence {sequence} must name sequence {sequence - 1} as the "
                f"version it replaced, and its supersedes is {supersedes!r}",
                where,
            )
        ]
    if version["action"] == "rollback":
        back = version.get("rolled_back_from")
        if back != {"release_id": supersedes["release_id"], "sequence": sequence - 1}:
            return [
                Finding(
                    "history_chain_broken",
                    f"sequence {sequence} is a rollback, and rolled_back_from "
                    f"{back!r} does not name the version it replaced",
                    where,
                )
            ]
    return []


def _chain_findings(
    earlier: Mapping[str, Any], later: Mapping[str, Any], where: str
) -> list[Finding]:
    """``later`` must name ``earlier`` — its release and its coverage.

    Runs only on two consecutive versions that each passed ``_own_findings``,
    so the sequence arithmetic is already settled and this compares what only
    the pair can: which release was replaced, and what it covered.
    """

    named = later["supersedes"]
    actual = {
        "release_id": earlier["release_id"],
        "last_observed_on": earlier["coverage"]["last_observed_on"],
    }
    claimed = {
        "release_id": named["release_id"],
        "last_observed_on": named["last_observed_on"],
    }
    if claimed == actual:
        return []
    return [
        Finding(
            "history_chain_broken",
            f"sequence {later['sequence']} says it replaced {claimed!r}, but "
            f"sequence {earlier['sequence']} was {actual!r}",
            where,
        )
    ]


def read_history(
    store: ConditionalStore,
    live: Mapping[str, Any] | None,
    live_body: bytes | None,
    *,
    keys: Iterable[str] | None = None,
) -> History:
    """Read and check the history against the live pointer.  Writes nothing.

    ``live`` and ``live_body`` are the live pointer as ``read_live_pointer``
    returns it.  ``keys`` is what a listing found under ``HISTORY_ROOT``; with
    no listing, every sequence from 1 to the live one is read, which is
    bounded by the number of pointer writes ever made and needs nothing but
    ``get``.  Only a listing can see a record *above* the live sequence.

    Every finding is collected rather than raised: a reader deciding what the
    history proves needs to know whether one record is wrong or the whole
    chain is, and that is ``docs/implementation/PHASE_2B1_2026-09-06.md`` §1's
    rule, again.
    """

    findings: list[Finding] = []
    live_sequence = live["sequence"] if live is not None else None

    if keys is None:
        candidates = set(range(1, (live_sequence or 0) + 1))
    else:
        candidates = set()
        for key in keys:
            if not key.startswith(HISTORY_ROOT):
                continue
            sequence = sequence_of(key)
            if sequence is None:
                findings.append(
                    Finding(
                        "history_key_malformed",
                        f"{key} is under {HISTORY_ROOT} and names no sequence; "
                        f"a record lives only at {history_key(1)}-shaped keys",
                        key,
                    )
                )
                continue
            candidates.add(sequence)

    recorded: dict[int, dict[str, Any]] = {}
    for sequence in sorted(candidates):
        key = history_key(sequence)
        stored = store.get(key)
        if stored is None:
            continue
        document = _parse(stored.body)
        errors = _pointer_errors(document)
        if errors:
            findings.append(
                Finding(
                    "history_record_not_a_pointer",
                    f"{key} is not a {POINTER_SCHEMA} document: " + "; ".join(errors[:3]),
                    key,
                )
            )
            continue
        if document["sequence"] != sequence:
            findings.append(
                Finding(
                    "history_record_sequence_mismatch",
                    f"{key} holds the pointer of sequence {document['sequence']}",
                    key,
                )
            )
            continue
        if live_sequence is None or sequence > live_sequence:
            findings.append(
                Finding(
                    "history_record_above_the_live_pointer",
                    f"{key} records sequence {sequence}, and the live pointer is "
                    f"{'absent' if live_sequence is None else f'at {live_sequence}'}. "
                    "The protocol records a version only after the swap accepted "
                    "it, so this is a write made outside it",
                    key,
                )
            )
            continue
        if sequence == live_sequence and stored.body != live_body:
            findings.append(
                Finding(
                    "history_record_differs_from_the_live_pointer",
                    f"{key} is the record of the live sequence and does not hold "
                    "the live pointer's bytes",
                    key,
                )
            )
            continue
        recorded[sequence] = document

    first = min(recorded) if recorded else None

    # The live version always has an entry: from its record, or — while the
    # record is pending — from the live pointer, which holds the same bytes.
    versions = dict(recorded)
    if live is not None and live_sequence not in versions:
        versions[live_sequence] = dict(live)

    if first is not None and live_sequence is not None:
        for sequence in range(first + 1, live_sequence):
            if sequence not in recorded:
                findings.append(
                    Finding(
                        "history_gap",
                        f"sequence {sequence} has no record although sequences "
                        f"{first} and later are recorded. The protocol records a "
                        "version before replacing it, so it was replaced by a "
                        "write made outside the protocol",
                        history_key(sequence),
                    )
                )

    ordered = sorted(versions)
    sound: set[int] = set()
    for sequence in ordered:
        own = _own_findings(versions[sequence], history_key(sequence))
        findings += own
        if not own:
            sound.add(sequence)
    for earlier, later in zip(ordered, ordered[1:]):
        if later == earlier + 1 and earlier in sound and later in sound:
            findings += _chain_findings(
                versions[earlier], versions[later], history_key(later)
            )

    entries = tuple(
        Entry(
            sequence=sequence,
            action=versions[sequence]["action"],
            release_id=versions[sequence]["release_id"],
            promoted_utc=versions[sequence]["promoted_utc"],
            recorded=sequence in recorded,
        )
        for sequence in ordered
    )
    predecessor = versions[ordered[0]].get("supersedes") if ordered else None
    return History(
        live_sequence=live_sequence,
        first_recorded=first,
        entries=entries,
        predecessor=predecessor,
        findings=tuple(findings),
    )


def describe(history: History) -> str:
    """The operator-readable history, newest last, and the verdict."""

    lines = []
    if history.live_sequence is None:
        lines.append("pointer          : absent — nothing has ever been promoted")
    else:
        lines.append(f"live sequence    : {history.live_sequence}")
    if history.first_recorded is None:
        lines.append("history begins   : no record yet")
    else:
        lines.append(f"history begins   : sequence {history.first_recorded}")
    if history.predecessor:
        lines.append(
            "before that      : sequence "
            f"{history.predecessor['sequence']} was "
            f"{history.predecessor['release_id']} (from the first entry's "
            "supersedes; earlier bytes are not in the store)"
        )
    lines.append("")
    for entry in history.entries:
        state = "recorded" if entry.recorded else "PENDING — the live pointer holds it"
        lines.append(
            f"  {entry.sequence:>6}  {entry.action:<8}  {entry.release_id}  "
            f"{entry.promoted_utc}  {state}"
        )
    lines.append("")
    if history.consistent:
        lines.append("verdict          : consistent")
    else:
        lines.append(f"verdict          : INCONSISTENT — {len(history.findings)} finding(s)")
        for finding in history.findings:
            lines.append(f"  {finding}")
    return "\n".join(lines)
