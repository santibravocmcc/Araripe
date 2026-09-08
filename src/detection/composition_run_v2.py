"""Package 2A.6B run producer: physical acquisitions plus terminal evidence.

Consumes — never redefines — the closed Package 2A.6A contracts:
``AcquisitionV2``/``ObservationV2`` from :mod:`src.detection.identity_v2` and
``ProcessingLedgerV2`` from :mod:`src.detection.ledger_v2`.  For one run
manifest it:

- turns each declared physical datatake (platform + datatake + timestamp and
  its provider-native scenes) into exactly one ``AcquisitionV2`` bound to
  ``coverage-ranked-first-valid-v1``;
- composes each datatake independently under ``scl-explicit-allowlist-v2``,
  proving local/GEE-plan parity for every successful composite;
- records fail-closed terminal ledger rows for mask-unavailable datatakes
  (missing metadata -> ``failed_missing_input``; unexpected or unreviewed
  metadata -> ``rejected_quality``) and zero-valid composites
  (``rejected_low_coverage``); and
- lets the detection caller record ``complete_with_alerts`` /
  ``complete_zero_alerts`` rows whose observations and composition-evidence
  artifact checksum reconcile with the manifest-bound ledger.

Whether a normalized platform (for example Sentinel-2C, present in the
Phase 2A.4 pilot scenes) is representable is decided by the closed
acquisition-v2 contract; this module deliberately adds no platform policy of
its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

from src.detection.identity import canonical_sha256
from src.detection.identity_v2 import (
    AcquisitionV2,
    ObservationV2,
    create_acquisition_v2,
    normalize_utc_timestamp,
    require_nonempty,
    require_semver,
)
from src.detection.ledger_v2 import ProcessingLedgerV2
from src.processing.composition_v2 import (
    COMPOSITION_METHOD_ID,
    DatatakeCompositeV2,
    SceneInputV2,
    group_scenes_by_datatake,
    compose_datatake,
    normalize_platform,
)
from src.processing.gee_composition_v2 import (
    assert_local_gee_parity,
    build_gee_composition_plan,
    execute_gee_plan_locally,
)
from src.processing.scl_mask_v2 import (
    REVIEWED_PROCESSING_BASELINES,
    MissingProcessingBaselineError,
    MissingSclError,
    SclMaskUnavailableError,
    reviewed_baseline_registry_dict,
)


RUN_EVIDENCE_VERSION = "phase2a6b-composition-run-evidence-v1"
ZERO_VALID_REASON_CODE = "composite-zero-valid-pixels"
_MISSING_INPUT_ERRORS = (MissingSclError, MissingProcessingBaselineError)
_DATATAKE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"


@dataclass(frozen=True)
class DatatakeRunInputV2:
    """One manifest-declared physical datatake and its native scenes."""

    platform: str
    datatake_id: str
    acquisition_timestamp_utc: str
    scenes: tuple[SceneInputV2, ...]


@dataclass
class CompositionOutcomeV2:
    """The composition result for exactly one expected acquisition."""

    acquisition: AcquisitionV2
    scenes: tuple[SceneInputV2, ...]
    composite: DatatakeCompositeV2 | None = None
    gee_plan: Mapping[str, Any] | None = None
    parity_evidence: Mapping[str, Any] | None = None
    error: SclMaskUnavailableError | None = None
    terminal_row: Mapping[str, Any] | None = None

    @property
    def evidence_sha256(self) -> str | None:
        if self.composite is None:
            return None
        return self.composite.composition_evidence_sha256


def _declared_input(value: DatatakeRunInputV2) -> DatatakeRunInputV2:
    if not isinstance(value, DatatakeRunInputV2):
        raise TypeError("datatakes must be DatatakeRunInputV2 records")
    platform = normalize_platform(value.platform)
    datatake_id = require_nonempty(value.datatake_id, label="datatake_id")
    timestamp = normalize_utc_timestamp(
        value.acquisition_timestamp_utc, label="acquisition_timestamp_utc"
    )
    scenes = tuple(value.scenes)
    if not scenes:
        raise ValueError(
            f"datatake {datatake_id} declares no provider-native scenes"
        )
    groups = group_scenes_by_datatake(scenes)
    if len(groups) != 1 or (groups[0].platform, groups[0].datatake_id) != (
        platform,
        datatake_id,
    ):
        raise ValueError(
            f"scenes supplied for datatake {datatake_id} do not form exactly "
            "that one physical datatake; different datatakes are never "
            "composed"
        )
    if datatake_id.startswith("GS2"):
        parts = datatake_id.split("_")
        if len(parts) < 2:
            raise ValueError(
                f"provider datatake_id {datatake_id!r} embeds no sensing "
                "instant"
            )
        embedded = parts[1]
        instant = datetime.fromisoformat(timestamp[:-1] + "+00:00")
        if instant.strftime(_DATATAKE_TIMESTAMP_FORMAT) != embedded:
            raise ValueError(
                f"declared acquisition timestamp {timestamp} disagrees with "
                f"the sensing instant embedded in datatake {datatake_id}"
            )
    return DatatakeRunInputV2(
        platform=platform,
        datatake_id=datatake_id,
        acquisition_timestamp_utc=timestamp,
        scenes=scenes,
    )


@dataclass
class CompositionRunV2:
    """One manifest-bound Package 2A.6B composition run."""

    run_manifest_id: str
    run_manifest_sha256: str
    collection_id: str
    monitoring_extent_id: str
    grid_id: str
    algorithm_version: str
    created_at: str
    datatakes: tuple[DatatakeRunInputV2, ...]
    reviewed_baselines: tuple[str, ...] = REVIEWED_PROCESSING_BASELINES
    ledger: ProcessingLedgerV2 = field(init=False)
    outcomes: tuple[CompositionOutcomeV2, ...] = field(init=False)

    def __post_init__(self) -> None:
        self.algorithm_version = require_semver(
            self.algorithm_version, label="algorithm_version"
        )
        declared = tuple(_declared_input(item) for item in self.datatakes)
        if not declared:
            raise ValueError("a composition run requires at least one datatake")
        physical_keys = [
            (item.platform, item.datatake_id) for item in declared
        ]
        if len(set(physical_keys)) != len(physical_keys):
            # The 2A.6A ledger key includes the exact timestamp string, so a
            # microsecond-different retiming could otherwise smuggle one
            # physical datatake into two expected acquisitions.
            raise ValueError(
                "a physical platform/datatake was declared more than once "
                "in this run manifest"
            )
        acquisitions = tuple(
            create_acquisition_v2(
                run_manifest_id=self.run_manifest_id,
                run_manifest_sha256=self.run_manifest_sha256,
                collection_id=self.collection_id,
                platform=item.platform,
                datatake_id=item.datatake_id,
                acquisition_timestamp_utc=item.acquisition_timestamp_utc,
                scene_ids=tuple(scene.scene_id for scene in item.scenes),
                monitoring_extent_id=self.monitoring_extent_id,
                composite_method_id=COMPOSITION_METHOD_ID,
                grid_id=self.grid_id,
            )
            for item in declared
        )
        self.ledger = ProcessingLedgerV2(
            run_manifest_id=self.run_manifest_id,
            run_manifest_sha256=self.run_manifest_sha256,
            acquisitions=acquisitions,
            monitoring_extent_id=self.monitoring_extent_id,
            algorithm_version=self.algorithm_version,
            created_at=self.created_at,
        )
        by_key = {
            (item.platform, item.datatake_id, item.acquisition_timestamp_utc): item
            for item in declared
        }
        self.outcomes = tuple(
            CompositionOutcomeV2(
                acquisition=acquisition,
                scenes=by_key[
                    (
                        acquisition.platform,
                        acquisition.datatake_id,
                        acquisition.acquisition_timestamp_utc,
                    )
                ].scenes,
            )
            for acquisition in self.ledger.acquisitions
        )
        self.datatakes = declared

    def compose_all(self, *, terminal_at: str) -> tuple[CompositionOutcomeV2, ...]:
        """Compose every expected acquisition, recording fail-closed rows.

        Successful composites additionally build the explicit GEE plan,
        execute it locally with mosaic semantics, and prove parity.  They are
        NOT terminal yet: detection outcome rows belong to the caller through
        :meth:`record_complete` / :meth:`record_zero_valid`.
        """

        for outcome in self.outcomes:
            if outcome.composite is not None or outcome.error is not None:
                continue
            group = group_scenes_by_datatake(outcome.scenes)[0]
            try:
                composite = compose_datatake(
                    group, reviewed_baselines=self.reviewed_baselines
                )
            except SclMaskUnavailableError as exc:
                status = (
                    "failed_missing_input"
                    if isinstance(exc, _MISSING_INPUT_ERRORS)
                    else "rejected_quality"
                )
                result = self.ledger.record_terminal(
                    acquisition_id=outcome.acquisition.acquisition_id,
                    status=status,
                    reason={"code": exc.reason_code, "message": str(exc)},
                    terminal_at=terminal_at,
                )
                outcome.error = exc
                outcome.terminal_row = result.row
                continue
            plan = build_gee_composition_plan(
                composite, image_collection_id=self.collection_id
            )
            execution = execute_gee_plan_locally(
                plan,
                outcome.scenes,
                reviewed_baselines=self.reviewed_baselines,
            )
            outcome.composite = composite
            outcome.gee_plan = plan
            outcome.parity_evidence = assert_local_gee_parity(
                composite, execution
            )
        return self.outcomes

    def _composable_outcome(
        self, outcome: CompositionOutcomeV2
    ) -> CompositionOutcomeV2:
        if not any(outcome is item for item in self.outcomes):
            raise ValueError("outcome does not belong to this run")
        if outcome.error is not None:
            raise ValueError(
                "acquisition already failed closed during composition"
            )
        if outcome.composite is None:
            raise ValueError("acquisition has not been composed yet")
        if outcome.terminal_row is not None:
            raise ValueError("acquisition already has a terminal row")
        composite = outcome.composite
        acquisition = outcome.acquisition
        composite_scene_ids = tuple(
            sorted(
                composite.composition_order_scene_ids,
                key=lambda item: item.encode("utf-8"),
            )
        )
        if (
            composite.platform != acquisition.platform
            or composite.datatake_id != acquisition.datatake_id
            or composite_scene_ids != acquisition.scene_ids
        ):
            # A swapped-in composite would bind another datatake's evidence
            # checksum (or bypass the zero-valid gate) on this acquisition's
            # terminal row.
            raise ValueError(
                "composite does not belong to this outcome's acquisition"
            )
        return outcome

    def record_complete(
        self,
        outcome: CompositionOutcomeV2,
        *,
        observations: Iterable[ObservationV2],
        terminal_at: str,
    ) -> Mapping[str, Any]:
        """Record the detection-complete terminal row for one composite."""

        outcome = self._composable_outcome(outcome)
        assert outcome.composite is not None
        if outcome.composite.composed_pixel_count == 0:
            raise ValueError(
                "a zero-valid composite cannot be complete; use "
                "record_zero_valid"
            )
        observation_records = tuple(observations)
        observation_ids = []
        for observation in observation_records:
            if not isinstance(observation, ObservationV2):
                raise TypeError("observations must be ObservationV2 records")
            record = observation.to_dict()
            if record["acquisition_id"] != outcome.acquisition.acquisition_id:
                raise ValueError(
                    "observation belongs to a different acquisition"
                )
            if record["algorithm_version"] != self.algorithm_version:
                raise ValueError(
                    "observation algorithm_version differs from the run"
                )
            observation_ids.append(record["observation_id"])
        status = (
            "complete_with_alerts" if observation_ids else "complete_zero_alerts"
        )
        result = self.ledger.record_terminal(
            acquisition_id=outcome.acquisition.acquisition_id,
            status=status,
            observation_ids=observation_ids,
            terminal_at=terminal_at,
            artifact_sha256=outcome.composite.composition_evidence_sha256,
        )
        outcome.terminal_row = result.row
        return result.row

    def record_zero_valid(
        self, outcome: CompositionOutcomeV2, *, terminal_at: str
    ) -> Mapping[str, Any]:
        """Record ``rejected_low_coverage`` for an empty composite."""

        outcome = self._composable_outcome(outcome)
        assert outcome.composite is not None
        if outcome.composite.composed_pixel_count != 0:
            raise ValueError(
                "composite has valid pixels; rejected_low_coverage would "
                "misstate it"
            )
        result = self.ledger.record_terminal(
            acquisition_id=outcome.acquisition.acquisition_id,
            status="rejected_low_coverage",
            reason={
                "code": ZERO_VALID_REASON_CODE,
                "message": (
                    "no pixel passed scl-explicit-allowlist-v2 with all "
                    "bands finite in any scene of this datatake"
                ),
            },
            terminal_at=terminal_at,
        )
        outcome.terminal_row = result.row
        return result.row

    def run_evidence(self) -> dict[str, Any]:
        """Summarize the run: acquisitions, baselines, parity, and statuses.

        Requires every expected acquisition to be terminal so the summary can
        embed the fully reconciled ledger identity.
        """

        ledger_document = self.ledger.to_dict()
        observed: set[str] = set()
        acquisitions_summary = []
        for outcome in self.outcomes:
            if outcome.composite is not None:
                observed.update(outcome.composite.observed_processing_baselines)
            if outcome.error is not None:
                # The composition gate enumerates every readable baseline of
                # a failed datatake, not only the failing value.
                observed.update(outcome.error.observed_baselines)
            row = outcome.terminal_row
            if row is None:
                raise ValueError(
                    "run evidence requires every acquisition to be terminal"
                )
            acquisitions_summary.append(
                {
                    "acquisition_id": outcome.acquisition.acquisition_id,
                    "platform": outcome.acquisition.platform,
                    "datatake_id": outcome.acquisition.datatake_id,
                    "acquisition_timestamp_utc": (
                        outcome.acquisition.acquisition_timestamp_utc
                    ),
                    "observed_on": outcome.acquisition.observed_on,
                    "status": row["status"],
                    "reason_code": (
                        row["reason"]["code"] if row["reason"] else None
                    ),
                    "composition_evidence_sha256": outcome.evidence_sha256,
                    "gee_plan_sha256": (
                        outcome.gee_plan["gee_plan_sha256"]
                        if outcome.gee_plan is not None
                        else None
                    ),
                    "local_gee_parity": (
                        outcome.parity_evidence["parity"]
                        if outcome.parity_evidence is not None
                        else None
                    ),
                }
            )
        reviewed_set = set(self.reviewed_baselines)
        unreviewed = {value for value in observed if value not in reviewed_set}
        body = {
            "run_evidence_version": RUN_EVIDENCE_VERSION,
            "run_manifest_id": self.run_manifest_id,
            "run_manifest_sha256": self.run_manifest_sha256,
            "ledger_id": ledger_document["ledger_id"],
            "monitoring_extent_id": self.monitoring_extent_id,
            "algorithm_version": self.algorithm_version,
            "composite_method_id": COMPOSITION_METHOD_ID,
            "grid_id": self.grid_id,
            "acquisitions": acquisitions_summary,
            "observed_processing_baselines": sorted(observed),
            "unreviewed_processing_baselines": sorted(unreviewed),
            "reviewed_processing_baseline_registry": (
                reviewed_baseline_registry_dict(self.reviewed_baselines)
            ),
        }
        return {**body, "run_evidence_sha256": canonical_sha256(body)}
