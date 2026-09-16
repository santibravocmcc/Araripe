"""Which seasonal source regime each replay month was composed against.

Why this document has to exist
------------------------------
The owner chose baseline ``2.1.0`` for the replay, and ``2.1.0`` admits
pre-Collection-1 products in calendar months 1-4 under the regime
``wet-season-mixed-lineage-v1``, whose provenance state is
``mixed_lineage_pending_esa_reprocessing``.  ESA is reprocessing those months;
when that lands, the regime is to be retired and the wet season rebuilt.  That
is the cost the owner accepted with the decision, and the decision file says so
in its own ``accepted_cost``.

The consequence for *this* run's record is arithmetic.  Without a per-month
statement of which regime each month was composed against, retiring one regime
means redoing **every** month, because nothing records which months depended on
it.  With it, retiring ``wet-season-mixed-lineage-v1`` scopes the rework to the
months that regime owns — four instead of twelve.

Where the answer comes from, and why not from the amendment
-----------------------------------------------------------
From the **generation's own manifest**.  The amendment document
(``config/phase2a6c1_seasonal_source_regime_amendment_v2.json``) says which
regimes were *accepted*; the manifest says which regime each month of *this
generation's rasters* was actually *built* under, in
``rebuild_execution.months[*].source_regime``.  A replay month is composed
against a baseline calendar month, so the regime of the replay month is the
regime of that baseline month.  Reading the accepted set and assuming the build
followed it would be recording an intention as an outcome.

And the manifest's two statements about regimes are cross-checked rather than
trusted.  ``source_regime_contract`` promises that the regimes partition
calendar months 1-12; it does **not** promise that the per-month
``source_regime`` field agrees with that partition.  So the agreement is
verified here, per month, and a disagreement fails closed — the manifest would
be describing two different builds.

What this module deliberately does not do
-----------------------------------------
It does not count acquisitions per month.  That accounting is the ledger's,
keyed per physical acquisition with a UTC date, and a calendar month is a
prefix of that date — so the two documents join without either restating the
other.  Two answers to one question is the failure this whole line of work
keeps paying for.

Floats are refused on purpose: the record is a candidate for a signed document,
and ``json.dumps`` and the RFC 8785 form disagree on a float of integral value
(``1.0`` against ``1``) and on exponents (``1e-07`` against ``1e-7``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

#: The provenance state that means "ESA has not finished reprocessing these
#: products, and this regime is to be retired when it does".  Declared by the
#: accepted amendment and carried into the generation manifest.
PENDING_PROVENANCE_STATE = "mixed_lineage_pending_esa_reprocessing"

#: Where the retirement condition is watched.  Named so the record points at
#: the vigilance instead of describing it in prose.
WATCH_SCRIPT = "scripts/check_esa_reprocessing.py"
WATCH_QUERY_CONFIG = "config/esa_reprocessing_watch_query_v1.json"

RECORD_SCHEMA = "araripe-replay-composition-regimes-v1"


class SeasonalRegimeError(RuntimeError):
    """The manifest cannot answer which regime a month was composed under."""


@dataclass(frozen=True)
class MonthRegime:
    """One calendar month of the replay window and the regime behind it."""

    month: int
    regime_id: str
    provenance_state: str
    scene_cloud_filter_percent: int
    recorded_reviews: tuple[str, ...]

    @property
    def rebuild_pending(self) -> bool:
        """True when this month rides on products ESA is still reprocessing."""

        return self.provenance_state == PENDING_PROVENANCE_STATE

    def as_dict(self) -> dict[str, Any]:
        return {
            "month": int(self.month),
            "regime_id": self.regime_id,
            "provenance_state": self.provenance_state,
            "scene_cloud_filter_percent": int(self.scene_cloud_filter_percent),
            "rebuild_pending_on_esa_reprocessing": bool(self.rebuild_pending),
            "recorded_reviews": list(self.recorded_reviews),
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SeasonalRegimeError(message)


def _regimes_by_id(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    declared = manifest.get("source_regimes")
    _require(
        isinstance(declared, list) and bool(declared),
        "the baseline manifest declares no source_regimes, so it cannot say "
        "which regime a month was composed against",
    )
    by_id: dict[str, Mapping[str, Any]] = {}
    for entry in declared:
        _require(
            isinstance(entry, Mapping),
            "every source_regimes entry must be an object",
        )
        regime_id = entry.get("regime_id")
        _require(
            isinstance(regime_id, str) and bool(regime_id.strip()),
            "a source regime carries no regime_id",
        )
        _require(
            regime_id not in by_id,
            f"the manifest declares source regime {regime_id!r} twice",
        )
        by_id[regime_id] = entry
    return by_id


def _owner_by_month(
    by_id: Mapping[str, Mapping[str, Any]]
) -> dict[int, str]:
    """The month -> regime map the declared partition implies."""

    owner: dict[int, str] = {}
    for regime_id, entry in by_id.items():
        months = entry.get("months")
        _require(
            isinstance(months, list) and bool(months),
            f"source regime {regime_id!r} owns no month",
        )
        for month in months:
            _require(
                isinstance(month, int) and not isinstance(month, bool)
                and 1 <= month <= 12,
                f"source regime {regime_id!r} names month {month!r}, "
                "which is not an integer 1..12",
            )
            _require(
                month not in owner,
                f"calendar month {month:02d} is claimed by both "
                f"{owner.get(month)!r} and {regime_id!r}; the regimes do not "
                "partition the calendar",
            )
            owner[month] = regime_id
    return owner


def regimes_for_months(
    manifest: Mapping[str, Any], months: Iterable[int]
) -> tuple[MonthRegime, ...]:
    """The regime behind each named calendar month, from the manifest.

    Fails closed on a month the manifest does not build, on a per-month
    ``source_regime`` naming a regime the manifest does not declare, and on a
    per-month ``source_regime`` that contradicts the declared partition.
    """

    wanted = sorted({int(month) for month in months})
    _require(bool(wanted), "no calendar month was named")
    for month in wanted:
        _require(
            1 <= month <= 12, f"month {month} is not a calendar month 1..12"
        )

    by_id = _regimes_by_id(manifest)
    owner = _owner_by_month(by_id)

    execution = manifest.get("rebuild_execution")
    _require(
        isinstance(execution, Mapping),
        "the baseline manifest has no rebuild_execution block",
    )
    built = execution.get("months")
    _require(
        isinstance(built, list) and bool(built),
        "the baseline manifest records no built month",
    )
    declared_month: dict[int, str] = {}
    for entry in built:
        _require(
            isinstance(entry, Mapping),
            "every rebuild_execution month must be an object",
        )
        month = entry.get("month")
        _require(
            isinstance(month, int) and not isinstance(month, bool),
            f"a built month carries a non-integer month {month!r}",
        )
        _require(
            month not in declared_month,
            f"the manifest records calendar month {month:02d} twice",
        )
        regime_id = entry.get("source_regime")
        _require(
            isinstance(regime_id, str) and bool(regime_id.strip()),
            f"built month {month:02d} names no source_regime, so nothing "
            "records what it was composed against",
        )
        declared_month[month] = regime_id

    resolved = []
    for month in wanted:
        _require(
            month in declared_month,
            f"the baseline manifest does not record calendar month "
            f"{month:02d}, which the replay window composes against",
        )
        regime_id = declared_month[month]
        _require(
            regime_id in by_id,
            f"built month {month:02d} names source regime {regime_id!r}, "
            "which the manifest does not declare",
        )
        # The contract promises the regimes partition the calendar. It does
        # not promise this field agrees with that partition, so verify it: a
        # disagreement means the manifest describes two different builds.
        _require(
            owner.get(month) == regime_id,
            f"built month {month:02d} says it was composed under "
            f"{regime_id!r}, but the declared partition gives that month to "
            f"{owner.get(month)!r}",
        )
        entry = by_id[regime_id]
        provenance = entry.get("provenance_state")
        _require(
            isinstance(provenance, str) and bool(provenance.strip()),
            f"source regime {regime_id!r} declares no provenance_state, so "
            "nothing says whether month "
            f"{month:02d} is pending reprocessing",
        )
        cloud = entry.get("scene_cloud_filter_percent")
        _require(
            isinstance(cloud, int) and not isinstance(cloud, bool),
            f"source regime {regime_id!r} declares a non-integer "
            f"scene_cloud_filter_percent {cloud!r}",
        )
        resolved.append(
            MonthRegime(
                month=month,
                regime_id=regime_id,
                provenance_state=provenance,
                scene_cloud_filter_percent=cloud,
                recorded_reviews=tuple(entry.get("recorded_reviews", ())),
            )
        )
    return tuple(resolved)


def rework_scope(
    resolved: Iterable[MonthRegime],
) -> dict[str, list[int]]:
    """Regime -> the window months that would have to be redone with it.

    This is the whole point of the record.  Retiring one regime reruns the
    months it owns; without this grouping, retiring one regime reruns the year.
    """

    scope: dict[str, list[int]] = {}
    for item in resolved:
        scope.setdefault(item.regime_id, []).append(int(item.month))
    return {key: sorted(value) for key, value in sorted(scope.items())}


def composition_regime_record(
    manifest: Mapping[str, Any],
    *,
    months: Iterable[int],
    baseline_version: str,
    window_start: str,
    window_end_exclusive: str,
) -> dict[str, Any]:
    """The run record's statement of what each month was composed against.

    A pure function of the window's months and the generation manifest, so
    every batch of one replay writes the same document byte for byte.
    """

    declared_version = manifest.get("baseline_version")
    _require(
        declared_version == baseline_version,
        f"the manifest declares baseline_version {declared_version!r} but the "
        f"run composed against {baseline_version!r}; the record would name a "
        "generation it did not use",
    )
    resolved = regimes_for_months(manifest, months)
    scope = rework_scope(resolved)
    pending = [item for item in resolved if item.rebuild_pending]
    return {
        "schema": RECORD_SCHEMA,
        "baseline_version": baseline_version,
        "baseline_id": manifest.get("baseline_id"),
        "window": {
            "start": window_start,
            "end_exclusive": window_end_exclusive,
            "calendar_months": [int(item.month) for item in resolved],
        },
        "months": [item.as_dict() for item in resolved],
        "rework_scope_by_regime": scope,
        "pending_on_esa_reprocessing": {
            "months": sorted(int(item.month) for item in pending),
            "regimes": sorted({item.regime_id for item in pending}),
            "provenance_state": PENDING_PROVENANCE_STATE,
            "reading": (
                "these months, and only these, are composed against products "
                "ESA is still reprocessing. When the regime is retired they "
                "are the months to redo; the rest of the window is unaffected."
            ),
            "watched_by": WATCH_SCRIPT,
            "watch_query_config": WATCH_QUERY_CONFIG,
        },
        "source_regime_contract_id": (
            manifest.get("source_regime_contract", {}) or {}
        ).get("contract_id"),
    }
