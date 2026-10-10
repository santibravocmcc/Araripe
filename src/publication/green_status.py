"""The status of every green product, derived from what the bucket already says.

``docs/implementation/PHASE_6Y_2026-10-10.md`` is the design.  Nothing here is
stored: every fact below already has exactly one owner — the pointer says what
is published, the release how far its data goes, the heartbeat when the
automation tried, the context and sources pointers what they describe, the
chain head what was deposited — and a status document written beside them
would be a second answer to each of those questions, stale between its write
and its read.  So this module only *reads* them, together, and says one line
per product.

Two rules, both from measurements in that record:

* **ages come from the data, never from an object's stamp.**  Every date of
  the live release carries ``max_terminal_at`` 2026-10-07, because the whole
  series was rebuilt that day; ``promoted_utc`` is renewed by a rollback to
  older data.  Neither is read here.
* **whether a context or a sources document is current is the route's
  answer**, computed by calling ``delivery_boundary.resolve`` itself — so this
  reading and the Worker cannot disagree about what the page receives.

No age becomes "late" here.  Which age counts as late is the owner's decision
(PHASE_6Y §4); this module reports, and judges only what is a fact rather than
a limit: a document that cannot be read or does not check, a chain the head
resolution refuses, a route refusal that is not "waiting for a lane".

Nothing here touches a store: ``scripts/green_status.py`` reads, and hands the
documents — or the reason one could not be read — to :func:`assess`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from src.publication import delivery_boundary as db

#: A product is as the page and the route would have it.
OK = "ok"
#: Waiting on a lane that has not run yet: deposited dates the pointer does not
#: carry, or a context or sources document for an earlier release.
PENDING = "pending"
#: Never published.
ABSENT = "absent"
#: A fact the producer promises against: unreadable, unchecked, refused.
BROKEN = "broken"

STATES = (OK, PENDING, ABSENT, BROKEN)

STAMP = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Unreadable:
    """A document that is there but could not be read or did not check."""

    detail: str


@dataclass(frozen=True)
class Head:
    """What the chain head covers — ``state_chain.resolve_head`` and the head's ledger."""

    run_id: str
    last_observed_on: str


@dataclass(frozen=True)
class Reading:
    """Every document the status is derived from, as the reader found it.

    Each field is the parsed document, ``None`` when the key is absent, or an
    :class:`Unreadable` naming why it could not be used.  ``context`` and
    ``sources`` are the documents the two pointers name, read only when the
    pointer names the live release (otherwise the route never opens them
    either, and they stay ``None``).
    """

    pointer: Mapping[str, Any] | Unreadable | None
    release: Mapping[str, Any] | Unreadable | None
    heartbeat: Mapping[str, Any] | Unreadable | None
    context_pointer: Mapping[str, Any] | Unreadable | None
    context: Mapping[str, Any] | Unreadable | None
    sources_pointer: Mapping[str, Any] | Unreadable | None
    sources: Mapping[str, Any] | Unreadable | None
    head: Head | Unreadable | None


@dataclass(frozen=True)
class Row:
    product: str
    state: str
    #: The date or instant the age is counted from, as the owner stored it.
    since: str | None
    #: Whole days from ``since`` to the reading; ``None`` when there is no date.
    age_days: int | None
    detail: str


def _days_since_date(day: str, now: datetime) -> int:
    return (now.date() - date.fromisoformat(day)).days


def _days_since_instant(stamp: str, now: datetime) -> int:
    moment = datetime.strptime(stamp, STAMP).replace(tzinfo=timezone.utc)
    return int((now - moment).total_seconds() // 86400)


def last_date_with_products(release: Mapping[str, Any]) -> str | None:
    """The last date the page can show: the last ``dates[]`` with ``paths``.

    Not ``coverage.last_observed_on``, which counts the dates looked at and
    refused too — in 2026, 62 of 107 (PHASE_6Y §1).
    """

    shown = [entry["observed_on"] for entry in release.get("dates", []) if entry.get("paths")]
    return max(shown) if shown else None


def finalized_through(pointer: Mapping[str, Any]) -> str | None:
    watermark = pointer.get("state_watermark") or {}
    return watermark.get("finalized_through") or (pointer.get("coverage") or {}).get("last_observed_on")


def _release_rows(reading: Reading, now: datetime) -> tuple[list[Row], Mapping[str, Any] | None]:
    pointer, release = reading.pointer, reading.release
    if isinstance(pointer, Unreadable):
        why = f"the pointer cannot be used: {pointer.detail}"
        return [Row("alerts.shown", BROKEN, None, None, why),
                Row("alerts.observed", BROKEN, None, None, why)], None
    if pointer is None:
        why = "no green release has been promoted"
        return [Row("alerts.shown", ABSENT, None, None, why),
                Row("alerts.observed", ABSENT, None, None, why)], None
    if isinstance(release, Unreadable) or release is None:
        why = ("the live release cannot be used: " + release.detail if release is not None
               else f"the pointer names {pointer['release_id']} and its release.json is absent")
        return [Row("alerts.shown", BROKEN, None, None, why),
                Row("alerts.observed", BROKEN, None, None, why)], None

    rid = release["release_id"]
    seq = pointer.get("sequence")
    shown = last_date_with_products(release)
    rows = [
        Row("alerts.shown", OK, shown, None if shown is None else _days_since_date(shown, now),
            f"the last date the page can show, in {rid[:15]}… (pointer seq. {seq}); "
            "a gap of 30 days was normal in the 2026 rainy season"
            if shown else f"{rid[:15]}… holds no date with a product"),
    ]
    observed = (release.get("coverage") or {}).get("last_observed_on")
    rows.append(Row(
        "alerts.observed", OK, observed, None if observed is None else _days_since_date(observed, now),
        "the last date looked at, products or not — the date that says whether the series moves",
    ))
    return rows, release


def _queue_row(reading: Reading) -> Row:
    head, pointer = reading.head, reading.pointer
    if isinstance(head, Unreadable):
        return Row("deposits.unpublished", BROKEN, None, None, f"the chain head is refused: {head.detail}")
    if head is None:
        return Row("deposits.unpublished", ABSENT, None, None, "no chain has been deposited")
    if not isinstance(pointer, Mapping):
        return Row("deposits.unpublished", PENDING, head.last_observed_on, None,
                   f"head {head.run_id} covers to {head.last_observed_on}; nothing is published to compare")
    through = finalized_through(pointer)
    if head.last_observed_on == through:
        return Row("deposits.unpublished", OK, head.last_observed_on, None,
                   f"head {head.run_id} covers to {through}, as the pointer does: nothing waits")
    if through is None or head.last_observed_on > through:
        return Row("deposits.unpublished", PENDING, head.last_observed_on, None,
                   f"head {head.run_id} covers to {head.last_observed_on} and the pointer to "
                   f"{through}: deposited dates wait for the operational publication")
    # Not refused: a new generation's chain grows from its own root while the
    # pointer still names the old one (PHASE_6W), and nothing promises the head
    # is never behind.
    return Row("deposits.unpublished", PENDING, head.last_observed_on, None,
               f"head {head.run_id} covers to {head.last_observed_on}, less than the pointer's "
               f"{through} — a chain still growing toward the published one")


def _heartbeat_rows(reading: Reading, now: datetime) -> list[Row]:
    beat = reading.heartbeat
    if isinstance(beat, Unreadable):
        why = f"the heartbeat cannot be used: {beat.detail}"
        return [Row("automation.latest", BROKEN, None, None, why),
                Row("automation.last_success", BROKEN, None, None, why)]
    if beat is None:
        why = "the deposit lane has not recorded an attempt"
        return [Row("automation.latest", ABSENT, None, None, why),
                Row("automation.last_success", ABSENT, None, None, why)]
    rows = []
    for product, attempt in (("automation.latest", beat["latest"]),
                             ("automation.last_success", beat["last_success"])):
        if attempt is None:
            rows.append(Row(product, ABSENT, None, None, "no attempt has succeeded yet"))
            continue
        stage = f" at {attempt['stage']}" if attempt.get("stage") else ""
        rows.append(Row(product, OK, attempt["finished_utc"],
                        _days_since_instant(attempt["finished_utc"], now),
                        f"{attempt['outcome']}{stage}, {attempt['run_id']}"))
    return rows


#: Route refusals that mean "a lane has not caught up yet", not "something is
#: wrong": the normal state right after a promotion (delivery_boundary).
_WAITING = {"context_not_live", "sources_not_live"}
_NEVER = {"context_absent", "sources_absent"}


def _served_row(product: str, url: str, reading: Reading, release: Mapping[str, Any] | None,
                inputs: Sequence[str], describe) -> Row:
    """What ``delivery_boundary.resolve`` answers for ``url`` — the route's own rule.

    ``inputs`` are the documents that answer depends on: the sources need the
    context pointer too, because "live" for them is the live release *and* the
    context that is live for it.
    """

    for name in inputs:
        value = getattr(reading, name)
        if isinstance(value, Unreadable):
            return Row(product, BROKEN, None, None, f"{name.replace('_', ' ')} cannot be used: {value.detail}")
    if release is None:
        return Row(product, ABSENT if reading.pointer is None else BROKEN, None, None,
                   "no live release to describe")
    try:
        db.resolve(
            "GET", url,
            pointer=reading.pointer, manifest=release,
            context_pointer=reading.context_pointer, context=reading.context,
            sources_pointer=reading.sources_pointer, sources=reading.sources,
        )
    except db.DeliveryRefused as exc:
        code = exc.codes[0]
        detail = "; ".join(f.detail for f in exc.findings)
        state = PENDING if code in _WAITING else ABSENT if code in _NEVER else BROKEN
        return Row(product, state, None, None, f"the route answers {code}: {detail}")
    return Row(product, OK, None, None, describe())


def assess(reading: Reading, now: datetime) -> list[Row]:
    """One row per product, in a fixed order; ``now`` is an argument, not the clock."""

    now = now.astimezone(timezone.utc)
    rows, release = _release_rows(reading, now)
    rows.append(_queue_row(reading))
    rows.extend(_heartbeat_rows(reading, now))

    def context_text():
        cp = reading.context_pointer
        return (f"served: {cp['context_id'][:15]}… (seq. {cp.get('sequence')}, written "
                f"{cp.get('written_utc')}) describes the live release")

    def sources_text():
        sp = reading.sources_pointer
        return (f"served: {sp['sources_id'][:15]}… (seq. {sp.get('sequence')}, written "
                f"{sp.get('written_utc')}) describes the live release and context")

    rows.append(_served_row("context", db.MOUNT + db.CONTEXT_DIR + db.CONTEXT_DOCUMENT_NAME,
                            reading, release, ("context_pointer", "context"), context_text))
    rows.append(_served_row("sources", db.MOUNT + db.SOURCES_NAME, reading, release,
                            ("context_pointer", "sources_pointer", "sources"), sources_text))
    return rows


def broken(rows: Sequence[Row]) -> bool:
    return any(row.state == BROKEN for row in rows)


# ── rendering ────────────────────────────────────────────────────────────────


def _age(row: Row) -> str:
    return "—" if row.age_days is None else f"{row.age_days} d"


def as_text(rows: Sequence[Row], now: datetime) -> str:
    width = max(len(row.product) for row in rows)
    lines = [f"green status at {now.astimezone(timezone.utc).strftime(STAMP)} "
             "(read-only; no age is judged — the limits are the owner's)"]
    for row in rows:
        lines.append(f"{row.product.ljust(width)}  {row.state.ljust(7)}  "
                     f"{(row.since or '—').ljust(20)}  {_age(row).rjust(5)}  {row.detail}")
    return "\n".join(lines)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def as_markdown(rows: Sequence[Row], now: datetime) -> str:
    lines = [
        "## Green status",
        "",
        f"Read at {now.astimezone(timezone.utc).strftime(STAMP)}, read-only. Ages are "
        "reported, not judged: which age counts as late is the owner's decision "
        "(PHASE_6Y §4).",
        "",
        "| product | state | since | age | detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(f"| `{row.product}` | {row.state} | {row.since or '—'} | {_age(row)} | {_cell(row.detail)} |")
    return "\n".join(lines) + "\n"
