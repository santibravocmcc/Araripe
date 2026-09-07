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
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from src.publication import delivery_boundary as db

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
) -> Disposition:
    """Decide one object, failing closed on anything unrecognised."""

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
        if release_id in referenced:
            return Disposition(
                key, item.size, "release", RETAIN, "release_is_referenced",
                "the pointer still names this release in supersedes or "
                "rolled_back_from, so it is the immediate rollback context",
            )
        return Disposition(
            key, item.size, "release", REVIEW, "promotion_history_not_recorded",
            "the store cannot say whether this release was ever live. The "
            "pointer is overwritten on every move and keeps one step of "
            "context, so a release that was live three promotions ago looks "
            "exactly like one whose promotion was refused. Deleting it could "
            "destroy a rollback target; a durable promotion history is the "
            "prerequisite for ever deciding this.",
        )

    if key.startswith(db.RUNS_ROOT):
        run_id = _run_id_of(key)
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
    **options: Any,
) -> RetentionPlan:
    """Classify a whole inventory.  Reads nothing and deletes nothing."""

    moment = as_of or datetime.now(timezone.utc)
    dispositions = tuple(
        classify(item, pointer=pointer, runs=runs or {}, as_of=moment, **options)
        for item in sorted(inventory, key=lambda item: item.key)
    )
    return RetentionPlan(
        as_of=moment,
        dispositions=dispositions,
        live_release_id=pointer["release_id"] if pointer else None,
        referenced_release_ids=referenced_release_ids(pointer),
    )


def plan_document(plan: RetentionPlan) -> dict[str, Any]:
    """The machine-readable plan, for review and for a later approved run."""

    return {
        "schema": PLAN_SCHEMA,
        "as_of": plan.as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "live_release_id": plan.live_release_id,
        "referenced_release_ids": list(plan.referenced_release_ids),
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


def describe(plan: RetentionPlan) -> str:
    """The operator-readable dry-run, leading with the number that matters."""

    counts = plan.counts()
    lines = [
        f"retention dry-run — {len(plan.dispositions)} object(s), "
        f"as of {plan.as_of.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"  live release   : {plan.live_release_id or '(none)'}",
        f"  referenced     : {', '.join(plan.referenced_release_ids) or '(none)'}",
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
