"""The Phase 4 expected-acquisition set, its coverage screen, and its rows.

Phase 4, roadmap bullets 2, 4 and 5 — *"Query every available 2026 physical
acquisition/datatake ... grouping only the ledger summaries by UTC date"*,
*"Record every manifest-bound expected acquisition as ... ; derive a daily
summary only after all expected acquisitions for that date are terminal"*, and
*"Verify acquisition/scene IDs, coverage, checksums, daily reconciliation, and
artifacts before accepting each batch"*.

This module is pure: it takes a run manifest document and measurements, and
returns identities, a screen and terminal rows.  No Earth Engine, no network,
no clock, no object store.  The driver that does hold those is
``scripts/replay_2026.py``.

Why there is a coverage screen at all
-------------------------------------
Measured on 2026-09-09 against ``ee-araripe``: the monitoring extent is
crossed by exactly two Sentinel-2 relative orbits, and one of them — R138,
about 13:13 UTC — clips at most **5.8%** of the extent.  That is swath
geometry, not cloud.  52 of the 107 physical datatakes of 2026 are R138, and
every one of them is below the ``min_clear`` 20% valid-coverage minimum that
``run_detection_from_gee`` already applies, so every one of them is destined
for ``rejected_low_coverage``.  Pulling a 729 MB composite to be told that
costs about nine minutes each.

What the screen is and is not
-----------------------------
It is **not** a second authority on scene quality.  ``assess_scene_quality``
remains the only thing that accepts an acquisition.  The screen may only
*reject*, it must be conservative, and its correctness condition is written
down and testable:

    nothing the screen rejects could have been accepted by the real gate.

That holds when the screened fraction is below the gate by a margin wider than
any disagreement between the two measurements — a coarse server-side reducer
against the fine local one.  :data:`SCREEN_SAFETY_DIVISOR` sets that margin,
and :func:`screen_by_coverage` refuses a threshold that does not leave one.
Anything in the margin band is pulled and decided by the real gate, which is
the fail-open direction: the screen can waste a download, never lose a date.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.detection.identity_v3 import AcquisitionV3, create_acquisition_v3
from src.detection.ledger_v3 import TERMINAL_STATUSES

#: The screen rejects only below ``minimum_fraction / SCREEN_SAFETY_DIVISOR``.
#: Two, so a datatake must be at least twice as far below the gate as the gate
#: itself before a download is skipped.  With the measured R138 ceiling of
#: 5.8% against a 20% gate the real margin is 3.4x, comfortably inside this.
SCREEN_SAFETY_DIVISOR = 2

#: Reason code for a datatake the screen rejects on measured extent coverage.
SCREEN_REASON_CODE = "datatake-extent-coverage-below-minimum"

#: Reason code for the real gate's coverage rejection, kept distinct so the
#: ledger says which of the two decided.  Conflating them would hide whether a
#: row was measured coarsely or evaluated fully.
GATE_COVERAGE_REASON_CODE = "scene-valid-coverage-below-minimum"

#: Reason code for the real gate's anomaly rejection.
GATE_ANOMALY_REASON_CODE = "scene-alert-fraction-anomalous"

#: A date whose event lineage the accepted persistence contract refuses to
#: resolve.  Package 2A.1: "Ambiguous many-to-many components fail closed for
#: reviewed correction", and no reviewed-correction mechanism exists yet.
LINEAGE_REASON_CODE = "persistence-ambiguous-lineage"


class EnumerationError(RuntimeError):
    """The manifest or the measurements do not support an expected set."""


@dataclass(frozen=True)
class ScreenedAcquisition:
    """One expected acquisition and what the screen decided about it."""

    acquisition: AcquisitionV3
    extent_coverage_fraction: float
    pull: bool
    screen_reason: str | None

    @property
    def acquisition_id(self) -> str:
        return self.acquisition.acquisition_id

    @property
    def observed_on(self) -> str:
        return self.acquisition.observed_on


def expected_acquisitions(
    run_manifest: Mapping[str, Any],
) -> tuple[AcquisitionV3, ...]:
    """Mint the expected acquisition set the manifest binds.

    The identities are minted here rather than read, because the manifest
    deliberately carries none: ``acquisition_id`` binds the composite method
    and the grid, and the export refuses to pre-compute an ID it might get
    wrong.  This function supplies both from the manifest's own run-level
    fields, so the identity is a function of the document.
    """

    for field in (
        "run_manifest_id",
        "run_manifest_sha256",
        "collection_id",
        "monitoring_extent_id",
        "composite_method_id",
        "composition_unit",
        "grid_id",
        "datatakes",
    ):
        if field not in run_manifest:
            raise EnumerationError(f"the run manifest has no {field}")

    unit = run_manifest["composition_unit"]
    if unit != "datatake":
        raise EnumerationError(
            f"this replay enumerates the datatake unit; the manifest declares "
            f"{unit!r}. A date-unit manifest expects one composite per date, "
            "which the v3 ledger cannot account for per acquisition."
        )

    datatakes = list(run_manifest["datatakes"])
    if not datatakes:
        raise EnumerationError("the run manifest declares no datatake")

    acquisitions = tuple(
        create_acquisition_v3(
            run_manifest_id=run_manifest["run_manifest_id"],
            run_manifest_sha256=run_manifest["run_manifest_sha256"],
            collection_id=run_manifest["collection_id"],
            platform=item["platform"],
            datatake_id=item["datatake_id"],
            acquisition_timestamp_utc=item["acquisition_timestamp_utc"],
            scene_ids=item["scene_ids"],
            monitoring_extent_id=run_manifest["monitoring_extent_id"],
            composite_method_id=run_manifest["composite_method_id"],
            grid_id=run_manifest["grid_id"],
        )
        for item in datatakes
    )
    identifiers = [item.acquisition_id for item in acquisitions]
    if len(set(identifiers)) != len(identifiers):
        raise EnumerationError(
            "the manifest mints a duplicate acquisition identity; a physical "
            "datatake was declared more than once"
        )
    return acquisitions


def screen_by_coverage(
    acquisitions: Sequence[AcquisitionV3],
    *,
    extent_coverage: Mapping[str, float],
    minimum_fraction: float,
) -> tuple[ScreenedAcquisition, ...]:
    """Decide which acquisitions are worth pulling, conservatively.

    ``extent_coverage`` maps ``datatake_id`` to the fraction of the monitoring
    extent that datatake covers with valid pixels, measured server-side.  Every
    expected acquisition must appear: a missing measurement is not a rejection,
    it is an unmeasured acquisition, and guessing one would be the whole defect
    this module exists to avoid.
    """

    if not 0 < minimum_fraction < 1:
        raise EnumerationError(
            "minimum_fraction is a fraction of the extent, strictly between 0 "
            f"and 1; got {minimum_fraction!r}"
        )
    threshold = minimum_fraction / SCREEN_SAFETY_DIVISOR
    if threshold >= minimum_fraction:
        raise EnumerationError(
            "the screen threshold must leave a margin below the gate"
        )

    screened = []
    for acquisition in acquisitions:
        key = acquisition.datatake_id
        if key not in extent_coverage:
            raise EnumerationError(
                f"no extent coverage was measured for datatake {key}; an "
                "unmeasured acquisition is not a rejected one"
            )
        fraction = float(extent_coverage[key])
        if not 0.0 <= fraction <= 1.0:
            raise EnumerationError(
                f"extent coverage for {key} is {fraction!r}, not a fraction"
            )
        reject = fraction < threshold
        screened.append(
            ScreenedAcquisition(
                acquisition=acquisition,
                extent_coverage_fraction=fraction,
                pull=not reject,
                screen_reason=(
                    f"the datatake covers {fraction * 100:.2f}% of the "
                    f"monitoring extent, below the screen threshold of "
                    f"{threshold * 100:.2f}% (the {minimum_fraction * 100:.0f}% "
                    f"minimum divided by the safety margin of "
                    f"{SCREEN_SAFETY_DIVISOR}); no composite is pulled and the "
                    "acquisition is terminal on measured coverage"
                    if reject
                    else None
                ),
            )
        )
    return tuple(screened)


def screen_summary(screened: Iterable[ScreenedAcquisition]) -> dict[str, Any]:
    """What the screen decided, as a document a record can carry."""

    items = list(screened)
    pulled = [item for item in items if item.pull]
    rejected = [item for item in items if not item.pull]
    return {
        "expected_acquisitions": len(items),
        "to_pull": len(pulled),
        "rejected_on_measured_coverage": len(rejected),
        "screen_safety_divisor": SCREEN_SAFETY_DIVISOR,
        "screen_reason_code": SCREEN_REASON_CODE,
        "highest_rejected_coverage": (
            max((item.extent_coverage_fraction for item in rejected), default=None)
        ),
        "lowest_pulled_coverage": (
            min((item.extent_coverage_fraction for item in pulled), default=None)
        ),
        "dates_with_at_least_one_pull": len(
            {item.observed_on for item in pulled}
        ),
        "dates_expected": len({item.observed_on for item in items}),
    }


def screen_rejection(item: ScreenedAcquisition) -> dict[str, str]:
    """The ledger reason for a screen rejection, with its measurement."""

    if item.pull:
        raise EnumerationError(
            "this acquisition was not rejected by the screen; asking for its "
            "rejection reason would invent one"
        )
    assert item.screen_reason is not None
    return {"code": SCREEN_REASON_CODE, "message": item.screen_reason}


def gate_rejection(quality: Any) -> tuple[str, dict[str, str]]:
    """Map a scene-quality rejection onto a terminal status and reason.

    ``assess_scene_quality`` decides; this only translates, and it fails closed
    on a decision it does not recognize rather than defaulting to a status.
    Defaulting here would put a wrong but plausible row in the ledger, and the
    exit gate cannot tell a wrong terminal row from a right one.
    """

    reason = getattr(quality, "rejection_reason", None)
    if getattr(quality, "scene_decision", None) == "accepted":
        raise EnumerationError(
            "the scene was accepted; it has no rejection to translate"
        )
    coverage = float(getattr(quality, "valid_coverage_fraction", 0.0))
    minimum = float(getattr(quality, "minimum_required_fraction", 0.0))
    if coverage < minimum:
        return (
            "rejected_low_coverage",
            {
                "code": GATE_COVERAGE_REASON_CODE,
                "message": (
                    f"valid coverage {coverage * 100:.2f}% is below the "
                    f"{minimum * 100:.2f}% minimum "
                    f"({reason or 'no reason recorded'})"
                ),
            },
        )
    return (
        "rejected_quality",
        {
            "code": GATE_ANOMALY_REASON_CODE,
            "message": (
                f"scene rejected by the quality gate: "
                f"{reason or 'no reason recorded'} "
                f"(alert fraction of valid "
                f"{float(getattr(quality, 'alert_fraction_of_valid', 0.0)) * 100:.2f}%)"
            ),
        },
    )


def lineage_failure(error: BaseException) -> tuple[str, dict[str, str]]:
    """Translate a fail-closed persistence refusal into a terminal row.

    ``update_tracks`` raises when a date's overlap graph contains a
    many-to-many split/merge component, which the accepted Package 2A.1
    contract says must "fail closed for reviewed correction".  The correction
    mechanism does not exist, so the replay cannot give that date event
    lineage under the frozen rules.

    It records the date instead of dropping it.  ``failed_processing`` is one
    of the seven contract terminal statuses and roadmap bullet 4 names it, so
    the exit gate still gets one terminal row per expected acquisition, and
    the affected dates are enumerable from the ledger rather than only from a
    log line.  The blue path drops them: ``run_detection_from_gee`` catches
    every exception around its per-date block and continues, which is why the
    blue time-series carries fewer dates than were observed.

    This translates and does not decide.  It never returns a success status,
    so a date whose lineage was refused can never be recorded as complete —
    that would claim observations the persistence layer declined to bind.
    """

    message = str(error).strip() or error.__class__.__name__
    return (
        "failed_processing",
        {
            "code": LINEAGE_REASON_CODE,
            "message": (
                "update_tracks failed closed for reviewed correction: "
                f"{message[:300]}"
            ),
        },
    )


def reconciles(
    *, expected: Sequence[AcquisitionV3], rows: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Whether every expected acquisition has exactly one terminal row.

    The clause the exit gate is worded in.  Returns the finding rather than
    raising, because the caller reports it per batch and a partial run is a
    legitimate intermediate state — but ``complete`` is only true when the two
    sets are equal and every status is a contract terminal status.
    """

    expected_ids = {item.acquisition_id for item in expected}
    row_ids = set(rows)
    unexpected = sorted(row_ids - expected_ids)
    missing = sorted(expected_ids - row_ids)
    unresolved = sorted(
        identifier
        for identifier, row in rows.items()
        if row.get("status") not in TERMINAL_STATUSES
    )
    return {
        "expected": len(expected_ids),
        "terminal": len(row_ids & expected_ids),
        "missing": missing,
        "unexpected": unexpected,
        "non_terminal_status": unresolved,
        "complete": not missing and not unexpected and not unresolved,
    }
