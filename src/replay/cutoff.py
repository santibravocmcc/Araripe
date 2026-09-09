"""The replay cutoff, and the queue of everything after it.

Phase 3, scope items 5 and part of 2 — the roadmap bullet *"Choose and record
the replay cutoff date. Queue acquisitions after that cutoff for later
incremental processing"*, and its Phase 6 counterpart *"process **queued
post-cutoff dates** through the five-day incremental contract"*.

Why the cutoff is a rule and not only a date
--------------------------------------------
``docs/operations/PHASE_3_INPUTS_2026-09-08.md`` measured the trade and it
points one way: the replay is cheap and the queue is the awkward part, because
the queue is drained at cutover and grows for as long as Phases 4 and 5 run.
So the cutoff should be as late as terminality allows — and fixing a literal
date today, then running Phase 4 in three weeks, would add three weeks of
queue for nothing.

Hence two recorded things, and the distinction is the whole point:

* :data:`CUTOFF_RULE` — the last UTC date the ledger declares fully terminal
  at the moment the Phase 4 query is issued, **resolved and fixed as a literal
  in that execution's record**;
* a **provisional** cutoff for the Phase 3 rehearsal and photograph, read from
  what the producer declares rather than guessed:
  ``data/timeseries/RELEASE.json``'s ``latest_observation``.

Why "queued" has to be written down
-----------------------------------
Without an explicit record, a date that was left out of the batch and a date
that was lost look identical from the outside.  :func:`build_queue` therefore
produces a document that names every post-cutoff date it knows about, says
which observation source declared it, and carries the five-day incremental
contract the cutover will drain it through.  A date is *queued* because a
document says so, not because someone remembers.

What this module refuses to do
------------------------------
Guess.  It never invents dates between the cutoff and today from a calendar:
Sentinel-2 revisit, cloud rejection and terminality mean the observed dates
are a measured set, not an arithmetic one.  Callers hand in the dates they
measured, and a queue built from nothing is an empty queue that says so.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from config import settings
from src.detection.identity import canonical_sha256

#: Version token of the queue document.
REPLAY_QUEUE_VERSION = "phase3-post-cutoff-queue-v1"

#: The recorded cutoff rule.  Phase 4 resolves it and writes the literal it
#: resolved to into its own record; this string is what it resolves.
CUTOFF_RULE = (
    "The replay cutoff is the last UTC date the processing ledger declares "
    "fully terminal at the moment the Phase 4 query is issued, resolved and "
    "fixed as a literal date in that execution's record."
)

#: The rule's identifier, so a record can cite the rule it resolved.
CUTOFF_RULE_ID = "phase3-cutoff-rule-v1"

#: How the queue is drained.  Named, not described: the cutover seeds the
#: scheduled process from the rebuilt watermark and then walks the queue
#: through the accepted incremental contract.
INCREMENTAL_CONTRACT = {
    "search_days_back": settings.SEARCH_DAYS_BACK,
    "cadence": "Monday and Thursday 06:00 UTC",
    "drained_by": "Phase 6 cutover, after the scheduled process is seeded",
}

#: The only queue disposition Phase 3 may assign.  A date is queued or it is
#: not in the document; there is no "probably fine" state.
QUEUED = "queued_for_incremental"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CutoffError(ValueError):
    """The cutoff or its queue is not usable."""


@dataclass(frozen=True)
class ProvisionalCutoff:
    """A cutoff read from a producer, with the evidence it was read from."""

    date: str
    source_path: str
    source_field: str
    source_published_utc: str
    source_run_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "source_path": self.source_path,
            "source_field": self.source_field,
            "source_published_utc": self.source_published_utc,
            "source_run_id": self.source_run_id,
        }


def require_date(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _DATE.match(value):
        raise CutoffError(f"{label} must be an ISO YYYY-MM-DD date, got {value!r}")
    return value


def read_provisional_cutoff(release_path: Path | None = None) -> ProvisionalCutoff:
    """The provisional cutoff, read from the time-series release signal.

    ``latest_observation`` is what the system itself declares as the last
    fully evaluated date — not an estimate with a margin.  Reading it is why
    the rehearsal's cutoff is defensible without the owner choosing a date
    today.
    """

    path = Path(
        Path(settings.TIMESERIES_DIR) / "RELEASE.json"
        if release_path is None
        else release_path
    )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CutoffError(f"cannot read the release signal {path}: {exc}") from exc
    for field in ("latest_observation", "published_utc", "run_id", "schema"):
        if field not in document:
            raise CutoffError(f"{path} has no {field}")
    if document["schema"] != "araripe.timeseries.release/1":
        raise CutoffError(
            f"{path} declares schema {document['schema']!r}, which this reader "
            "does not know"
        )
    return ProvisionalCutoff(
        date=require_date(
            document["latest_observation"], label="latest_observation"
        ),
        source_path=path.as_posix(),
        source_field="latest_observation",
        source_published_utc=str(document["published_utc"]),
        source_run_id=str(document["run_id"]),
    )


def split_at_cutoff(
    cutoff: str, observed_dates: Iterable[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(in_batch, after_cutoff)`` for the dates handed in.

    The cutoff is **inclusive** on the batch side: Phase 4 queries *"from
    January 1 through the recorded cutoff"*, so the cutoff date itself is
    replayed and only strictly later dates are queued.  Stated here because
    an off-by-one at this boundary is a whole date silently processed twice or
    not at all.
    """

    require_date(cutoff, label="cutoff")
    dates = sorted(
        {require_date(value, label="observed date") for value in observed_dates}
    )
    in_batch = tuple(value for value in dates if value <= cutoff)
    after = tuple(value for value in dates if value > cutoff)
    return in_batch, after


def build_queue(
    *,
    cutoff: str,
    observed_dates: Iterable[str],
    observation_source: str,
    cutoff_is_provisional: bool,
    cutoff_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The explicit post-cutoff queue document.

    ``observation_source`` says who declared the dates — the difference
    between "these dates exist" and "somebody looked".  An empty queue is a
    valid, and useful, answer: it records that the measurement was made.
    """

    require_date(cutoff, label="cutoff")
    if not isinstance(observation_source, str) or not observation_source.strip():
        raise CutoffError("observation_source must say who declared the dates")
    in_batch, after = split_at_cutoff(cutoff, observed_dates)
    body = {
        "replay_queue_version": REPLAY_QUEUE_VERSION,
        "cutoff": {
            "rule_id": CUTOFF_RULE_ID,
            "rule": CUTOFF_RULE,
            "date": cutoff,
            "date_is_provisional": bool(cutoff_is_provisional),
            "inclusive_on_the_batch_side": True,
            "evidence": dict(cutoff_evidence or {}),
        },
        "observation_source": observation_source.strip(),
        "in_batch": {
            "count": len(in_batch),
            "dates": list(in_batch),
            # The batch side is a by-product of splitting the observation
            # source, and the source is whatever the caller could measure
            # without a credential — for Phase 3 that is the tracked
            # time-series database, which is the BLUE product and therefore
            # only knows the dates blue processed. Phase 4 enumerates every
            # physical acquisition from Earth Engine and will see more. The
            # queue's job is the other side of the split.
            "is_authoritative_for_phase_4": False,
            "authoritative_enumeration": (
                "Phase 4 queries every available 2026 physical "
                "acquisition/datatake from January 1 through the recorded "
                "cutoff; this list is the observation source's view, not that "
                "enumeration"
            ),
        },
        "queued": {
            "count": len(after),
            "disposition": QUEUED,
            "dates": list(after),
            "incremental_contract": dict(INCREMENTAL_CONTRACT),
        },
        "not_a_calendar": (
            "only dates an observation source declared are listed; the "
            "observed set is measured, never derived from a date range"
        ),
    }
    document = dict(body)
    document["queue_sha256"] = canonical_sha256(body)
    return document


def validate_queue(document: Mapping[str, Any]) -> None:
    """Fail closed on a queue that does not account for what it lists."""

    if not isinstance(document, Mapping):
        raise CutoffError("the queue document must be a mapping")
    if document.get("replay_queue_version") != REPLAY_QUEUE_VERSION:
        raise CutoffError(
            f"queue version is {document.get('replay_queue_version')!r}, "
            f"expected {REPLAY_QUEUE_VERSION!r}"
        )
    body = {key: value for key, value in document.items() if key != "queue_sha256"}
    if canonical_sha256(body) != document.get("queue_sha256"):
        raise CutoffError("queue_sha256 does not match the document body")

    cutoff = require_date(document["cutoff"]["date"], label="cutoff.date")
    if document["cutoff"].get("rule_id") != CUTOFF_RULE_ID:
        raise CutoffError("the queue cites an unknown cutoff rule")
    if document["cutoff"].get("inclusive_on_the_batch_side") is not True:
        raise CutoffError(
            "this reader only knows a batch-inclusive cutoff; an exclusive "
            "one would move a whole date between the batch and the queue"
        )

    in_batch = list(document["in_batch"]["dates"])
    queued = list(document["queued"]["dates"])
    for label, dates in (("in_batch", in_batch), ("queued", queued)):
        for value in dates:
            require_date(value, label=f"{label} date")
        if dates != sorted(dates):
            raise CutoffError(f"{label} dates are not sorted")
        if len(set(dates)) != len(dates):
            raise CutoffError(f"{label} dates contain a duplicate")
    if document["in_batch"].get("is_authoritative_for_phase_4") is not False:
        raise CutoffError(
            "the batch list must declare itself non-authoritative for Phase 4; "
            "it is the observation source's view, not the replay enumeration"
        )
    if document["in_batch"]["count"] != len(in_batch):
        raise CutoffError("in_batch count disagrees with its own list")
    if document["queued"]["count"] != len(queued):
        raise CutoffError("queued count disagrees with its own list")
    if document["queued"].get("disposition") != QUEUED:
        raise CutoffError(
            f"the only Phase 3 disposition is {QUEUED!r}; a queued date is "
            "queued or it is not in this document"
        )
    if any(value > cutoff for value in in_batch):
        raise CutoffError("a date after the cutoff is listed in the batch")
    if any(value <= cutoff for value in queued):
        raise CutoffError("a date at or before the cutoff is listed as queued")
    if set(in_batch) & set(queued):
        raise CutoffError("a date is both replayed and queued")


def resolve_recorded_cutoff(
    *, terminal_dates: Iterable[str], asked_at_utc: str
) -> dict[str, Any]:
    """Resolve :data:`CUTOFF_RULE` against a ledger's terminal dates.

    This is the function Phase 4 calls to turn the rule into the literal it
    records.  It takes the terminal dates rather than a ledger so it can be
    exercised without one, and it fails closed on an empty set: "no date is
    terminal" is not a cutoff, and defaulting to today would batch dates the
    exit gate cannot close on.
    """

    dates = sorted(
        {require_date(value, label="terminal date") for value in terminal_dates}
    )
    if not dates:
        raise CutoffError(
            "no date is declared terminal, so the rule resolves to nothing; a "
            "cutoff must not be defaulted"
        )
    return {
        "rule_id": CUTOFF_RULE_ID,
        "rule": CUTOFF_RULE,
        "date": dates[-1],
        "date_is_provisional": False,
        "inclusive_on_the_batch_side": True,
        "resolved_at_utc": asked_at_utc,
        "terminal_date_count": len(dates),
        "earliest_terminal_date": dates[0],
    }
