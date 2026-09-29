"""What green storage may eventually be removed — decided, never executed.

Roadmap Package 2B.3: *define conservative lifecycle and rollback retention;
run deletion policies in reviewed dry-run form first.*

This is the first place in the project that reasons about removing anything.
Until now nothing could be deleted **by construction**: ``ConditionalStore``
has no delete and no unconditional put, and staleness is recorded as a
tombstone on the pointer rather than acted on
(``GREEN_RELEASE_CONTRACT_V1.md`` §8).  That property is not weakened here.
This module produces a *plan*; no code path in this repository can carry one
out, and adding that capability is a separate, approved change.

Three dispositions, and the middle one is the point
---------------------------------------------------
``retain``   — a positive rule keeps the object.
``review``   — the store does not contain what a decision would need.  The
               object is kept, and the plan says exactly what is missing.
``eligible`` — a positive rule permits removal, and its horizon has passed.

A two-way policy would have to answer every question, so it would answer some
of them by assumption.  ``review`` is what makes "we cannot tell" a first-class
outcome instead of a silent ``eligible``.

The finding that shapes the whole policy
-----------------------------------------
**The store records no promotion history.**  ``pointers/green/current.json`` is
one mutable object, overwritten on every move; it carries the live release plus
*one* step of context (``supersedes``, ``rolled_back_from``).  Measured against
the real bucket on 2026-09-07: at ``sequence 3`` the pointer named
``rel-g1-ae3f6e1d…`` as live and ``rel-g1-5ffad23a…`` in both ``supersedes``
and ``rolled_back_from``, while ``rel-g1-9f1ed344…`` — the release whose
promotion was refused for coverage regression — appeared nowhere.

So today the two cases the briefing distinguishes are distinguishable.  **One
more pointer write and they are not:** ``rel-g1-5ffad23a…`` drops out of the
pointer and becomes indistinguishable from a release that was never promoted.
A release that was once live is the natural target of a future rollback, so
"delete every release the pointer does not reference" would delete exactly the
one an operator would want back.

Therefore no release is ever ``eligible`` here.  Making release retention
decidable needs a durable, write-once promotion history — specified in
``docs/operations/GREEN_RETENTION_AND_MIGRATION.md`` and deliberately not built
by this package, because it would change a publication path that was proven
end to end against real R2 five times on 2026-09-07.

Phase 6, decision D5 — the history exists, and the policy reads it
------------------------------------------------------------------
Built in ``promotion_history.py``, re-proven against real R2 from ``main`` on
2026-09-27 (``docs/implementation/PHASE_6D_2026-09-27.md``).  The planner now
takes a ``Lineage``: the store's records, plus a *reconstruction* of the
versions overwritten before the history began, kept in the repository
(``config/green_promotion_history_reconstruction_v1.json``) and never in the
store.  The two are joined at the one point where they speak — the
``supersedes`` of the first record — and only when that join holds, and the
history is consistent, is the account **continuous from sequence 1**.

What that makes decidable is *why* a release is kept, not whether it may go:
a release the account shows was live, and a release it shows was **never**
live, are both ``retain`` with different reasons.  Classifying is not
deleting, and no release is ``eligible`` — at any age, with any lineage.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from src.publication import delivery_boundary as db
from src.publication import promotion_history as ph
from src.publication.state_chain import STATE_GZIP_PATH, STATE_PATH

#: Contract version of a retention plan document.
PLAN_SCHEMA = "araripe.green.retention-plan/1"

RETAIN = "retain"
REVIEW = "review"
ELIGIBLE = "eligible"

#: How long a run prefix is kept after the release built from it is published
#: and complete.  A run prefix is the *input*; the release holds the ledger and
#: the objects it published.
DEFAULT_RUN_HORIZON_DAYS = 30

#: How long a verification artifact is kept after it is written.  Longer,
#: because a probe object is the evidence a proof ran at all.
DEFAULT_VERIFICATION_HORIZON_DAYS = 180


@dataclass(frozen=True)
class StoredKey:
    """One object as a listing reports it: key, size, last modification."""

    key: str
    size: int
    last_modified: datetime


@dataclass(frozen=True)
class RunLink:
    """What is known about the release a run prefix produced.

    Nothing in the store records this link: a release manifest carries the
    *ledger's* ``run_manifest_id``, not the ``runs/<run-id>/`` prefix it was
    read from.  It is recomputable — the release identity is a pure function of
    the ledger — so the caller resolves it by reading, and this module is told
    the answer rather than guessing one.
    """

    run_id: str
    release_id: str | None
    #: The release exists in the store and every object it declares is present.
    published_complete: bool


# ── the lineage: who was live, and whether the account reaches sequence 1 ────

#: Contract of the reconstruction of the versions the store lost.
RECONSTRUCTION_SCHEMA = "araripe.green.promotion-history-reconstruction/1"

#: Where the reconstruction lives: in the repository, reviewed by pull request.
RECONSTRUCTION_PATH = "config/green_promotion_history_reconstruction_v1.json"

_RELEASE_ID = re.compile(r"^rel-g1-[0-9a-f]{64}$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

#: Why a lineage cannot vouch for the whole account.  The first is the state
#: before this package; the other two are what the join can find wrong.
NOT_RECORDED = "promotion_history_not_recorded"
INCONSISTENT = "promotion_history_inconsistent"
NOT_CONTINUOUS = "promotion_history_not_continuous"


@dataclass(frozen=True)
class ReconstructedEntry:
    """One pointer version rebuilt from documents, with where each claim is."""

    sequence: int
    action: str
    release_id: str
    last_observed_on: str
    #: ``document §section`` for every source the entry cites.
    sources: tuple[str, ...]


def load_reconstruction(document: Mapping[str, Any]) -> tuple[ReconstructedEntry, ...]:
    """Parse the reconstruction, refusing anything that is not one.

    Only what makes the entries usable is checked here: that the document says
    it is a reconstruction, and that it is a contiguous run of versions from
    sequence 1 whose first write replaced nothing.  Whether it agrees with the
    store is ``build_lineage``'s question, and whether it agrees with the
    documents it cites is the test suite's.
    """

    if document.get("schema") != RECONSTRUCTION_SCHEMA:
        raise ValueError(f"the reconstruction must declare {RECONSTRUCTION_SCHEMA!r}")
    if document.get("reconstructed") is not True:
        raise ValueError(
            "the document must declare itself reconstructed: it is a claim "
            "derived from records, not a copy of a stored pointer"
        )
    raw = document.get("entries")
    if not isinstance(raw, list) or not raw:
        raise ValueError("the reconstruction has no entries")
    entries = []
    for position, item in enumerate(raw, start=1):
        where = f"entry {position}"
        if item.get("sequence") != position or isinstance(item.get("sequence"), bool):
            raise ValueError(
                f"{where}: sequences run from 1 without a gap, and this one is "
                f"{item.get('sequence')!r}"
            )
        if item.get("action") not in ("promote", "rollback"):
            raise ValueError(f"{where}: action {item.get('action')!r}")
        if position == 1 and item["action"] != "promote":
            raise ValueError(
                "sequence 1 is the first write into an empty pointer: a promotion"
            )
        if not isinstance(item.get("release_id"), str) or not _RELEASE_ID.match(
            item["release_id"]
        ):
            raise ValueError(f"{where}: release id {item.get('release_id')!r}")
        if not isinstance(item.get("last_observed_on"), str) or not _DATE.match(
            item["last_observed_on"]
        ):
            raise ValueError(f"{where}: last_observed_on {item.get('last_observed_on')!r}")
        sources = item.get("sources")
        if not isinstance(sources, list) or not sources or not all(
            isinstance(s, Mapping) and s.get("document") and s.get("section")
            for s in sources
        ):
            raise ValueError(f"{where}: every entry cites a document and a section")
        entries.append(
            ReconstructedEntry(
                sequence=position,
                action=item["action"],
                release_id=item["release_id"],
                last_observed_on=item["last_observed_on"],
                sources=tuple(f"{s['document']} §{s['section']}" for s in sources),
            )
        )
    return tuple(entries)


@dataclass(frozen=True)
class Lineage:
    """What the planner may say about which releases were ever live.

    ``recorded`` comes from the store's history — byte-exact copies of accepted
    writes — and is trusted on its own.  ``reconstructed`` is used only once it
    has been joined to the store.  ``continuous`` is the claim that every
    pointer version from sequence 1 to the live one is accounted for, and it is
    the only thing that lets the planner call a release *never* live.
    """

    recorded: Mapping[str, tuple[int, ...]]
    reconstructed: Mapping[str, tuple[ReconstructedEntry, ...]]
    continuous: bool
    #: When not continuous: one of the three codes above, and what is missing.
    reason: str | None = None
    detail: str = ""
    live_sequence: int | None = None
    #: The first sequence the store vouches for: its first record, or the live
    #: pointer when that is the only version and its record is pending.
    history_begins: int | None = None
    findings: tuple[str, ...] = field(default_factory=tuple)


def _broken(reason: str, detail: str, found: ph.History | None, recorded) -> Lineage:
    return Lineage(
        recorded=recorded,
        reconstructed={},
        continuous=False,
        reason=reason,
        detail=detail,
        live_sequence=found.live_sequence if found else None,
        history_begins=found.entries[0].sequence if found and found.entries else None,
        findings=tuple(str(f) for f in found.findings) if found else (),
    )


def build_lineage(
    found: ph.History | None,
    reconstruction: Iterable[ReconstructedEntry] | None,
) -> Lineage:
    """Join the store's history to the reconstruction, failing closed.

    The account is continuous only when all of these hold:

    * the history is consistent (``read_history`` found nothing);
    * it has an entry — a record, or the live pointer as its pending record;
    * the versions below its first entry are exactly the reconstruction's,
      sequences 1 to one below it;
    * the first entry's ``supersedes`` names the reconstruction's last version
      — release, sequence and coverage — which is the one fact about the
      pre-history the store still holds.
    """

    recorded: dict[str, tuple[int, ...]] = {}
    if found is not None:
        for entry in found.entries:
            recorded[entry.release_id] = recorded.get(entry.release_id, ()) + (
                entry.sequence,
            )

    if found is None or not found.entries:
        return _broken(
            NOT_RECORDED,
            "the store holds no promotion history and no live pointer to start "
            "one from, so it cannot say which releases were ever live",
            found,
            recorded,
        )
    if not found.consistent:
        return _broken(
            INCONSISTENT,
            f"the promotion history has {len(found.findings)} finding(s): "
            + "; ".join(sorted({f.code for f in found.findings}))
            + ". Nothing it cannot vouch for is called never-live",
            found,
            recorded,
        )

    first = found.entries[0].sequence
    rebuilt = tuple(reconstruction or ())
    if [e.sequence for e in rebuilt] != list(range(1, first)):
        return _broken(
            NOT_CONTINUOUS,
            f"the history begins at sequence {first}, so sequences 1 to "
            f"{first - 1} must come from the reconstruction, and it holds "
            f"{[e.sequence for e in rebuilt] or 'nothing'}",
            found,
            recorded,
        )
    if rebuilt:
        last = rebuilt[-1]
        claimed = dict(found.predecessor or {})
        expected = {
            "release_id": last.release_id,
            "sequence": last.sequence,
            "last_observed_on": last.last_observed_on,
        }
        if claimed != expected:
            return _broken(
                NOT_CONTINUOUS,
                f"sequence {first} says it replaced {claimed!r}, and the "
                f"reconstruction ends at {expected!r}. A reconstruction the "
                "store contradicts is not evidence",
                found,
                recorded,
            )

    reconstructed: dict[str, tuple[ReconstructedEntry, ...]] = {}
    for entry in rebuilt:
        reconstructed[entry.release_id] = reconstructed.get(entry.release_id, ()) + (
            entry,
        )
    return Lineage(
        recorded=recorded,
        reconstructed=reconstructed,
        continuous=True,
        live_sequence=found.live_sequence,
        history_begins=first,
    )


@dataclass(frozen=True)
class Disposition:
    key: str
    size: int
    category: str
    action: str
    reason: str
    detail: str


@dataclass(frozen=True)
class RetentionPlan:
    as_of: datetime
    dispositions: tuple[Disposition, ...]
    live_release_id: str | None
    referenced_release_ids: tuple[str, ...]
    lineage: Lineage | None = None

    @property
    def eligible(self) -> tuple[Disposition, ...]:
        return tuple(d for d in self.dispositions if d.action == ELIGIBLE)

    @property
    def review(self) -> tuple[Disposition, ...]:
        return tuple(d for d in self.dispositions if d.action == REVIEW)

    @property
    def eligible_bytes(self) -> int:
        return sum(d.size for d in self.eligible)

    def counts(self) -> dict[str, int]:
        return dict(Counter(d.action for d in self.dispositions))

    def by_reason(self) -> dict[str, int]:
        return dict(Counter(d.reason for d in self.dispositions))


def referenced_release_ids(pointer: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Every release id the live pointer still names, in a stable order.

    This is the *whole* of what the store remembers about promotion history,
    which is why it is one short function rather than a traversal.
    """

    if pointer is None:
        return ()
    found: list[str] = [pointer["release_id"]]
    for field in ("supersedes", "rolled_back_from"):
        entry = pointer.get(field)
        if isinstance(entry, Mapping) and entry.get("release_id"):
            found.append(entry["release_id"])
    ordered: list[str] = []
    for release_id in found:
        if release_id not in ordered:
            ordered.append(release_id)
    return tuple(ordered)


def _release_id_of(key: str) -> str | None:
    rest = key[len(db.RELEASES_ROOT) :]
    release_id, _, remainder = rest.partition("/")
    return release_id if remainder else None


def _run_id_of(key: str) -> str | None:
    rest = key[len(db.RUNS_ROOT) :]
    run_id, _, remainder = rest.partition("/")
    return run_id if remainder else None


def _older_than(item: StoredKey, as_of: datetime, days: int) -> bool:
    return as_of - item.last_modified >= timedelta(days=days)


def _age_detail(item: StoredKey, as_of: datetime, days: int) -> str:
    age = as_of - item.last_modified
    return f"{age.days} day(s) old; the horizon is {days}"


def classify(
    item: StoredKey,
    *,
    pointer: Mapping[str, Any] | None,
    runs: Mapping[str, RunLink],
    as_of: datetime,
    run_horizon_days: int = DEFAULT_RUN_HORIZON_DAYS,
    verification_horizon_days: int = DEFAULT_VERIFICATION_HORIZON_DAYS,
    phase_open: bool = True,
    accept_run_manifest_loss: bool = False,
    lineage: Lineage | None = None,
    chain_members: Mapping[str, tuple[str, ...]] | None = None,
) -> Disposition:
    """Decide one object, failing closed on anything unrecognised.

    ``chain_members`` maps every version-3 release in the store to the member
    releases it references (``resolve_chain_members``).  A member is retained
    whatever else is true of it: the version-3 release serves its objects
    from the member's prefix (PHASE_6J §2).
    """

    key = item.key
    live = pointer["release_id"] if pointer else None
    referenced = referenced_release_ids(pointer)

    if key == db.POINTER_KEY:
        return Disposition(
            key, item.size, "pointer", RETAIN, "pointer_is_the_layout",
            "the single mutable object; the layout has exactly one and it is "
            "what makes every release findable",
        )

    if key.startswith(db.RELEASES_ROOT):
        release_id = _release_id_of(key)
        if release_id is None:
            return Disposition(
                key, item.size, "release", REVIEW, "release_prefix_malformed",
                "this key is directly under releases/ and names no release",
            )
        if release_id == live:
            return Disposition(
                key, item.size, "release", RETAIN, "release_is_live",
                "the pointer names this release; it is what the delivery route "
                "serves",
            )
        holders = sorted(
            chain for chain, members in (chain_members or {}).items()
            if release_id in members
        )
        if holders:
            served = live in holders
            return Disposition(
                key, item.size, "release", RETAIN,
                "release_is_served_by_the_live_release" if served
                else "release_is_a_member_of_a_chain_release",
                "a version-3 release references this release's objects in place "
                f"({', '.join(holders)}); removing it would break "
                + ("the live release" if served else "that release")
                + " (PHASE_6J §2)",
            )
        if release_id in referenced:
            return Disposition(
                key, item.size, "release", RETAIN, "release_is_referenced",
                "the pointer still names this release in supersedes or "
                "rolled_back_from, so it is the immediate rollback context",
            )
        if lineage is None:
            return Disposition(
                key, item.size, "release", REVIEW, NOT_RECORDED,
                "the store cannot say whether this release was ever live. The "
                "pointer is overwritten on every move and keeps one step of "
                "context, so a release that was live three promotions ago looks "
                "exactly like one whose promotion was refused. Deleting it could "
                "destroy a rollback target; a durable promotion history is the "
                "prerequisite for ever deciding this.",
            )
        sequences = lineage.recorded.get(release_id)
        if sequences:
            return Disposition(
                key, item.size, "release", RETAIN, "release_was_live",
                "the store's promotion history records this release as live at "
                f"sequence(s) {', '.join(str(s) for s in sequences)}; a release "
                "that was served is a rollback target and may be cited",
            )
        rebuilt = lineage.reconstructed.get(release_id)
        if rebuilt:
            return Disposition(
                key, item.size, "release", RETAIN,
                "release_was_live_per_reconstruction",
                "live before the store kept a history, at "
                + "; ".join(
                    f"sequence {e.sequence} ({e.action}, per {', '.join(e.sources)})"
                    for e in rebuilt
                )
                + f". Reconstructed in {RECONSTRUCTION_PATH}, joined to the "
                "store at the supersedes of its first record",
            )
        if lineage.continuous:
            return Disposition(
                key, item.size, "release", RETAIN, "release_never_live",
                "no record and no reconstructed version names this release, and "
                f"the account is continuous from sequence 1 to {lineage.live_sequence}"
                + (
                    f" (reconstruction 1-{lineage.history_begins - 1}, records "
                    f"{lineage.history_begins}-{lineage.live_sequence})"
                    if lineage.history_begins and lineage.history_begins > 1
                    else ""
                )
                + ": it was published and never served. Classified, not "
                "removed — deleting anything is a separate, approved capability "
                "that does not exist",
            )
        return Disposition(
            key, item.size, "release", REVIEW, lineage.reason or NOT_RECORDED,
            "this release is named by no record and no reconstructed version, "
            "and the account cannot say it was never live: " + lineage.detail,
        )

    if key.startswith(db.RUNS_ROOT):
        run_id = _run_id_of(key)
        if run_id and key in (
            f"{db.RUNS_ROOT}{run_id}/{STATE_PATH}",
            f"{db.RUNS_ROOT}{run_id}/{STATE_GZIP_PATH}",
        ):
            # PHASE_6G §1: the run prefix is the state's only home. A release
            # carries its digest, never its bytes, so "the release is
            # published" says nothing about whether the state survives — and
            # the next chained run starts from it.
            return Disposition(
                key, item.size, "run_input", RETAIN, "persistence_state_is_the_chain",
                "the persistence state is in no release, only here; a chained "
                "run continues from it",
            )
        link = runs.get(run_id) if run_id else None
        if link is None or link.release_id is None:
            return Disposition(
                key, item.size, "run_input", REVIEW, "run_release_link_unresolved",
                "no release could be resolved from this run's ledger, so it is "
                "not known whether anything here survives elsewhere",
            )
        if not link.published_complete:
            return Disposition(
                key, item.size, "run_input", RETAIN, "run_is_the_only_copy",
                f"the release {link.release_id} this run would produce is not "
                "published and complete in the store, so this prefix is the "
                "only copy of its inputs",
            )
        if not _older_than(item, as_of, run_horizon_days):
            return Disposition(
                key, item.size, "run_input", RETAIN, "within_run_horizon",
                _age_detail(item, as_of, run_horizon_days),
            )
        if not accept_run_manifest_loss:
            return Disposition(
                key, item.size, "run_input", REVIEW, "run_manifest_not_recoverable",
                "the published release holds the ledger and the objects it "
                "published, but never run.json — and a release is not required "
                "to publish every sealed artifact (GREEN_RELEASE_CONTRACT_V1.md "
                "§4, non-requirement 2). Removing this prefix loses the "
                "operator's declared inputs, which is a decision to take by "
                "name rather than by default.",
            )
        return Disposition(
            key, item.size, "run_input", ELIGIBLE, "run_superseded_by_release",
            f"release {link.release_id} is published and complete, the horizon "
            f"has passed ({_age_detail(item, as_of, run_horizon_days)}), and "
            "the loss of run.json was accepted explicitly",
        )

    if key.startswith(ph.HISTORY_ROOT):
        if ph.sequence_of(key) is None:
            return Disposition(
                key, item.size, "promotion_history", REVIEW, "history_key_malformed",
                f"this key is under {ph.HISTORY_ROOT} and names no sequence; the "
                "history's records live only at zero-padded sequence keys",
            )
        return Disposition(
            key, item.size, "promotion_history", RETAIN,
            "promotion_history_is_the_record",
            "a byte-exact copy of an accepted pointer write: the only evidence "
            "the store keeps that a release was live",
        )

    for root in db.VERIFICATION_ROOTS:
        if key.startswith(root):
            if phase_open:
                return Disposition(
                    key, item.size, "verification_artifact", RETAIN,
                    "phase_evidence_retained",
                    "Phases 2B-5 are open and this object is the evidence a "
                    "proof ran; it is cited by run id in docs/operations/",
                )
            if not _older_than(item, as_of, verification_horizon_days):
                return Disposition(
                    key, item.size, "verification_artifact", RETAIN,
                    "within_verification_horizon",
                    _age_detail(item, as_of, verification_horizon_days),
                )
            return Disposition(
                key, item.size, "verification_artifact", ELIGIBLE,
                "verification_artifact_expired",
                "its phase is closed and the horizon has passed; the run URL in "
                "the operations record remains the citation",
            )

    return Disposition(
        key, item.size, "unclassified", REVIEW, "unclassified_prefix",
        "no rule classifies this prefix. The policy fails closed: a prefix "
        "nobody has classified is kept and reported, never removed.",
    )


def build_plan(
    inventory: Iterable[StoredKey],
    *,
    pointer: Mapping[str, Any] | None,
    runs: Mapping[str, RunLink] | None = None,
    as_of: datetime | None = None,
    lineage: Lineage | None = None,
    **options: Any,
) -> RetentionPlan:
    """Classify a whole inventory.  Reads nothing and deletes nothing."""

    moment = as_of or datetime.now(timezone.utc)
    dispositions = tuple(
        classify(
            item, pointer=pointer, runs=runs or {}, as_of=moment, lineage=lineage,
            **options,
        )
        for item in sorted(inventory, key=lambda item: item.key)
    )
    return RetentionPlan(
        as_of=moment,
        dispositions=dispositions,
        live_release_id=pointer["release_id"] if pointer else None,
        referenced_release_ids=referenced_release_ids(pointer),
        lineage=lineage,
    )


def _lineage_document(lineage: Lineage | None) -> dict[str, Any] | None:
    if lineage is None:
        return None
    return {
        "continuous": lineage.continuous,
        "reason": lineage.reason,
        "detail": lineage.detail,
        "live_sequence": lineage.live_sequence,
        "history_begins": lineage.history_begins,
        "recorded": {k: list(v) for k, v in sorted(lineage.recorded.items())},
        "reconstructed": {
            k: [e.sequence for e in v] for k, v in sorted(lineage.reconstructed.items())
        },
        "findings": list(lineage.findings),
    }


def plan_document(plan: RetentionPlan) -> dict[str, Any]:
    """The machine-readable plan, for review and for a later approved run."""

    return {
        "schema": PLAN_SCHEMA,
        "as_of": plan.as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "live_release_id": plan.live_release_id,
        "referenced_release_ids": list(plan.referenced_release_ids),
        "lineage": _lineage_document(plan.lineage),
        "counts": plan.counts(),
        "reasons": plan.by_reason(),
        "eligible_bytes": plan.eligible_bytes,
        "objects": [
            {
                "key": d.key,
                "bytes": d.size,
                "category": d.category,
                "action": d.action,
                "reason": d.reason,
            }
            for d in plan.dispositions
        ],
    }


def _lineage_line(lineage: Lineage | None) -> str:
    if lineage is None:
        return "not read — no release can be called never-live"
    if lineage.continuous:
        start = (
            f"reconstruction 1-{lineage.history_begins - 1} + records "
            f"{lineage.history_begins}-{lineage.live_sequence}"
            if lineage.history_begins and lineage.history_begins > 1
            else f"records 1-{lineage.live_sequence}"
        )
        return f"continuous from sequence 1 ({start})"
    return f"NOT continuous — {lineage.reason}: {lineage.detail}"


def describe(plan: RetentionPlan) -> str:
    """The operator-readable dry-run, leading with the number that matters."""

    counts = plan.counts()
    lines = [
        f"retention dry-run — {len(plan.dispositions)} object(s), "
        f"as of {plan.as_of.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"  live release   : {plan.live_release_id or '(none)'}",
        f"  referenced     : {', '.join(plan.referenced_release_ids) or '(none)'}",
        f"  lineage        : {_lineage_line(plan.lineage)}",
        "",
        f"  retain   {counts.get(RETAIN, 0):>4}",
        f"  review   {counts.get(REVIEW, 0):>4}   (kept; the store cannot decide)",
        f"  eligible {counts.get(ELIGIBLE, 0):>4}   "
        f"({plan.eligible_bytes} byte(s))",
        "",
        "by reason:",
    ]
    for reason, count in sorted(plan.by_reason().items()):
        lines.append(f"  {count:>4}  {reason}")
    lines += ["", "objects:"]
    for d in plan.dispositions:
        lines.append(f"  [{d.action:<8}] {d.key}")
        lines.append(f"             {d.reason}: {d.detail}")
    lines += [
        "",
        "NOTHING WAS DELETED. This is a plan, and no code path in this "
        "repository can carry one out: ConditionalStore has no delete "
        "operation. Executing a plan is a separate change requiring explicit, "
        "named human approval.",
    ]
    return "\n".join(lines)


# ── the reads a plan needs, kept apart from the decisions it makes ───────────
#
# Everything above is a pure function of an inventory, a pointer and a set of
# resolved run links, so the policy is reviewable and testable without a store.
# Everything below reads, and only reads: a listing, a few JSON documents, and
# a presence check.  No write is expressible from here — the store handed in is
# a ``ReadOnlyStore`` whose three write methods raise.


def list_inventory(client: Any, bucket: str) -> list[StoredKey]:
    """Every object in the bucket, following the continuation token.

    ``ConditionalStore`` deliberately has no listing: it exists to make an
    unconditional write unavailable, and a list is neither a read of one object
    nor a write.  Listing therefore goes through the raw client here, exactly
    as ``scripts/probe_promotion_identity.py`` does, rather than by widening a
    class the publication path depends on.
    """

    items: list[StoredKey] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        for entry in page.get("Contents") or ():
            items.append(
                StoredKey(
                    key=entry["Key"],
                    size=int(entry.get("Size") or 0),
                    last_modified=entry["LastModified"],
                )
            )
        if not page.get("IsTruncated"):
            return items
        token = page.get("NextContinuationToken")
        if not token:
            # Truncated with no cursor: the listing is incomplete and a plan
            # built from a partial inventory would classify absent objects as
            # absent. Fail closed rather than plan over half a bucket.
            raise RuntimeError(
                f"listing {bucket} reported more results and returned no "
                "continuation token; refusing to plan over a partial inventory"
            )


def resolve_chain_members(store: Any, inventory: Iterable[StoredKey]) -> dict[str, tuple[str, ...]]:
    """Every version-3 release in the store, and the member releases it references.

    Read from each ``releases/rel-g3-…/release.json``.  A manifest that cannot
    be read or parsed fails the whole plan: a member list the planner could not
    see is a member it might classify as removable.
    """

    import json

    out: dict[str, tuple[str, ...]] = {}
    for item in inventory:
        if not item.key.startswith(db.RELEASES_ROOT + "rel-g3-"):
            continue
        release_id = _release_id_of(item.key)
        if release_id is None or item.key != f"{db.RELEASES_ROOT}{release_id}/release.json":
            continue
        stored = store.get(item.key)
        if stored is None:
            raise RuntimeError(f"{item.key} was listed and is absent")
        manifest = json.loads(stored.body)
        out[release_id] = tuple(block["release_id"] for block in manifest["members"])
    return out


def resolve_run_links(store: Any, inventory: Iterable[StoredKey]) -> dict[str, RunLink]:
    """For each run prefix, which release it would produce and whether it is whole.

    The link is *recomputed*, never read: a release manifest records the
    ledger's ``run_manifest_id``, not the ``runs/<run-id>/`` prefix it came
    from, so the store does not contain this edge.  It is derivable because the
    release identity is a pure function of the ledger
    (``GREEN_RELEASE_CONTRACT_V1.md`` §2), and running the same Package 2B.2A
    gate the publication runs is what makes the derivation trustworthy: a
    ledger that would be rejected produces no link at all.
    """

    import json

    from src.publication.green_release import (
        LEDGER_PATH,
        MANIFEST_PATH,
        object_key,
        release_identity,
    )
    from src.publication.ledger_gate import check_processing_ledger

    run_ids = sorted(
        {
            run_id
            for item in inventory
            if item.key.startswith(db.RUNS_ROOT)
            for run_id in (_run_id_of(item.key),)
            if run_id
        }
    )
    present = {item.key for item in inventory}
    links: dict[str, RunLink] = {}
    for run_id in run_ids:
        try:
            stored = store.get(f"{db.RUNS_ROOT}{run_id}/{LEDGER_PATH}")
            if stored is None:
                links[run_id] = RunLink(run_id, None, False)
                continue
            acceptance = check_processing_ledger(json.loads(stored.body))
            release_id, _ = release_identity(acceptance)
        except Exception:  # noqa: BLE001 - any failure means "not resolved"
            links[run_id] = RunLink(run_id, None, False)
            continue

        manifest_key = object_key(release_id, MANIFEST_PATH)
        complete = False
        if manifest_key in present:
            try:
                manifest = json.loads(store.require(manifest_key).body)
                declared = {
                    object_key(release_id, item["path"]) for item in manifest["objects"]
                }
                declared.add(object_key(release_id, LEDGER_PATH))
                declared.add(manifest_key)
                complete = declared <= present
            except Exception:  # noqa: BLE001
                complete = False
        links[run_id] = RunLink(run_id, release_id, complete)
    return links
