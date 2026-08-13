"""Adversarial semantic guards for the Package 2A.6A v2 runtime.

These cases deliberately recompute enclosing document checksums after selected
tampering.  A JSON-Schema-only boundary is therefore insufficient: the runtime
must rederive identities and reconcile the linked ledger/state records.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Iterable, Sequence

import pytest
from shapely.geometry import box

from src.detection import ledger_v2
from src.detection.contracts_v2 import ContractV2ValidationError
from src.detection.identity import (
    LINE_FEED,
    canonical_geometry_sha256,
    canonical_sha256,
    identity_sha256,
)
from src.detection.identity_v2 import (
    AcquisitionV2,
    ObservationV2,
    contribution_key_v2,
    create_acquisition_v2,
    create_observation_v2,
    observation_id_v2,
    origin_event_id_v2,
)
from src.detection.ledger_v2 import ProcessingLedgerV2
from src.detection.persistence_v2 import (
    LateArrivalRequiresRebuild,
    ObservationLedgerMismatch,
    PersistenceV2Error,
    _seal_state,
    apply_terminal_date_v2,
    empty_persistence_state_v2,
    validate_persistence_state_v2,
)


RUN_MANIFEST_ID = "run-v2-" + "1" * 64
RUN_MANIFEST_SHA256 = "2" * 64
GENERATION_ID = "gen-v2-" + "3" * 64
MONITORING_EXTENT_ID = "araripe-implementation-rectangle-v1"
ALGORITHM_VERSION = "2.0.0"
BASELINE_VERSION = "2.0.0"
CREATED_AT = "2026-08-13T12:00:00Z"


def _acquisition(
    observed_on: str,
    time_utc: str,
    datatake_id: str,
    *,
    platform: str = "S2A",
    scene_ids: Iterable[str] | None = None,
) -> AcquisitionV2:
    return create_acquisition_v2(
        run_manifest_id=RUN_MANIFEST_ID,
        run_manifest_sha256=RUN_MANIFEST_SHA256,
        collection_id="COPERNICUS_S2_SR_HARMONIZED",
        platform=platform,
        datatake_id=datatake_id,
        acquisition_timestamp_utc=f"{observed_on}T{time_utc}Z",
        scene_ids=scene_ids or (f"{datatake_id}-tile-b", f"{datatake_id}-tile-a"),
        monitoring_extent_id=MONITORING_EXTENT_ID,
        composite_method_id="coverage-ranked-first-valid-by-datatake-v2",
        grid_id="araripe-detector-grid-20m-v2",
    )


def _observation(
    acquisition: AcquisitionV2,
    geometry=None,
    *,
    area_ha: float = 1.0,
) -> ObservationV2:
    return create_observation_v2(
        acquisition=acquisition,
        geometry=geometry or box(-40.10, -7.10, -40.08, -7.08),
        algorithm_version=ALGORITHM_VERSION,
        baseline_version=BASELINE_VERSION,
        area_ha=area_ha,
        created_at=acquisition.acquisition_timestamp_utc,
    )


def _ledger(
    acquisitions: Sequence[AcquisitionV2],
    observations: Sequence[ObservationV2] = (),
) -> ProcessingLedgerV2:
    ledger = ProcessingLedgerV2(
        run_manifest_id=RUN_MANIFEST_ID,
        run_manifest_sha256=RUN_MANIFEST_SHA256,
        acquisitions=acquisitions,
        monitoring_extent_id=MONITORING_EXTENT_ID,
        algorithm_version=ALGORITHM_VERSION,
        created_at=CREATED_AT,
    )
    by_acquisition: dict[str, list[ObservationV2]] = {
        acquisition.acquisition_id: [] for acquisition in acquisitions
    }
    for observation in observations:
        by_acquisition[observation.acquisition_id].append(observation)
    for acquisition in acquisitions:
        records = sorted(
            by_acquisition[acquisition.acquisition_id],
            key=lambda item: item.observation_id.encode("utf-8"),
        )
        ledger.record_terminal(
            acquisition_id=acquisition.acquisition_id,
            status=("complete_with_alerts" if records else "complete_zero_alerts"),
            observation_ids=[item.observation_id for item in records],
            terminal_at=f"{acquisition.observed_on}T23:59:59Z",
            artifact_sha256=canonical_sha256(
                [item.to_dict() for item in records]
            ),
        )
    return ledger


def _empty_state(ledger: ProcessingLedgerV2) -> dict:
    return empty_persistence_state_v2(
        generation_id=GENERATION_ID,
        ledger=ledger,
        baseline_version=BASELINE_VERSION,
        generated_at=CREATED_AT,
    )


def _single_day_history():
    acquisition = _acquisition("2026-06-01", "10:00:00", "DT-STATE-1")
    observation = _observation(acquisition)
    ledger = _ledger([acquisition], [observation])
    transition = apply_terminal_date_v2(
        state=_empty_state(ledger),
        ledger=ledger,
        observed_on=acquisition.observed_on,
        observations=[observation],
        transitioned_at="2026-06-01T23:59:59Z",
    )
    return ledger, acquisition, observation, transition


def _two_day_history():
    day_one = _acquisition("2026-06-01", "10:00:00", "DT-STATE-1")
    day_two = _acquisition("2026-06-02", "10:00:00", "DT-STATE-2")
    geometry = box(-40.10, -7.10, -40.08, -7.08)
    observation_one = _observation(day_one, geometry)
    observation_two = _observation(day_two, geometry)
    ledger = _ledger([day_two, day_one], [observation_two, observation_one])
    first = apply_terminal_date_v2(
        state=_empty_state(ledger),
        ledger=ledger,
        observed_on=day_one.observed_on,
        observations=[observation_one],
        transitioned_at="2026-06-01T23:59:59Z",
    )
    second = apply_terminal_date_v2(
        state=first.state,
        ledger=ledger,
        observed_on=day_two.observed_on,
        observations=[observation_two],
        transitioned_at="2026-06-02T23:59:59Z",
    )
    return ledger, (day_one, day_two), (observation_one, observation_two), first, second


def _parallel_continuation_history():
    day_one = _acquisition("2026-06-10", "10:00:00", "DT-PARALLEL-1")
    day_two = _acquisition("2026-06-11", "10:00:00", "DT-PARALLEL-2")
    geometry_a = box(-40.10, -7.10, -40.08, -7.08)
    geometry_b = box(-39.80, -7.10, -39.78, -7.08)
    day_one_a = _observation(day_one, geometry_a)
    day_one_b = _observation(day_one, geometry_b)
    day_two_a = _observation(day_two, geometry_a)
    day_two_b = _observation(day_two, geometry_b)
    observations = (day_one_a, day_one_b, day_two_a, day_two_b)
    ledger = _ledger([day_two, day_one], observations)
    first = apply_terminal_date_v2(
        state=_empty_state(ledger),
        ledger=ledger,
        observed_on=day_one.observed_on,
        observations=[day_one_a, day_one_b],
        transitioned_at="2026-06-10T23:59:59Z",
    )
    second = apply_terminal_date_v2(
        state=first.state,
        ledger=ledger,
        observed_on=day_two.observed_on,
        observations=[day_two_a, day_two_b],
        transitioned_at="2026-06-11T23:59:59Z",
    )
    return ledger, observations, first, second


def _split_with_parallel_parent_history():
    origin_acquisition = _acquisition(
        "2026-06-12", "10:00:00", "DT-SPLIT-PARENT-1"
    )
    split_acquisition = _acquisition(
        "2026-06-13", "10:00:00", "DT-SPLIT-PARENT-2"
    )
    origin_geometry = box(-40.00, -7.00, -39.98, -6.99)
    parallel_geometry = box(-39.80, -7.00, -39.78, -6.99)
    origin = _observation(origin_acquisition, origin_geometry)
    parallel = _observation(origin_acquisition, parallel_geometry)
    left = _observation(
        split_acquisition, box(-40.00, -7.00, -39.992, -6.99)
    )
    right = _observation(
        split_acquisition, box(-39.988, -7.00, -39.98, -6.99)
    )
    ledger = _ledger(
        [split_acquisition, origin_acquisition],
        [parallel, right, origin, left],
    )
    first = apply_terminal_date_v2(
        state=_empty_state(ledger),
        ledger=ledger,
        observed_on=origin_acquisition.observed_on,
        observations=[parallel, origin],
        transitioned_at="2026-06-12T23:59:59Z",
    )
    second = apply_terminal_date_v2(
        state=first.state,
        ledger=ledger,
        observed_on=split_acquisition.observed_on,
        observations=[right, left],
        transitioned_at="2026-06-13T23:59:59Z",
    )
    return (origin, parallel, left, right), first, second


def _split_merge_history():
    origin_acquisition = _acquisition(
        "2026-06-14", "10:00:00", "DT-SPLIT-MERGE-1"
    )
    split_acquisition = _acquisition(
        "2026-06-15", "10:00:00", "DT-SPLIT-MERGE-2"
    )
    merge_acquisition = _acquisition(
        "2026-06-16", "10:00:00", "DT-SPLIT-MERGE-3"
    )
    origin_geometry = box(-40.00, -7.00, -39.98, -6.99)
    origin = _observation(origin_acquisition, origin_geometry)
    left = _observation(
        split_acquisition, box(-40.00, -7.00, -39.992, -6.99)
    )
    right = _observation(
        split_acquisition, box(-39.988, -7.00, -39.98, -6.99)
    )
    merged = _observation(merge_acquisition, origin_geometry)
    ledger = _ledger(
        [merge_acquisition, split_acquisition, origin_acquisition],
        [merged, right, origin, left],
    )
    first = apply_terminal_date_v2(
        state=_empty_state(ledger),
        ledger=ledger,
        observed_on=origin_acquisition.observed_on,
        observations=[origin],
        transitioned_at="2026-06-14T23:59:59Z",
    )
    second = apply_terminal_date_v2(
        state=first.state,
        ledger=ledger,
        observed_on=split_acquisition.observed_on,
        observations=[right, left],
        transitioned_at="2026-06-15T23:59:59Z",
    )
    third = apply_terminal_date_v2(
        state=second.state,
        ledger=ledger,
        observed_on=merge_acquisition.observed_on,
        observations=[merged],
        transitioned_at="2026-06-16T23:59:59Z",
    )
    return (origin, left, right, merged), first, second, third


def _rewrite_lineage_edge(
    state: dict,
    edge: dict,
    *,
    parent_event_ids: Iterable[str] | None = None,
    child_event_ids: Iterable[str] | None = None,
    trigger_observation_ids: Iterable[str] | None = None,
) -> None:
    """Reidentify one edge and repair all old/new reciprocal event lists."""

    old_lineage_id = edge["lineage_id"]
    if parent_event_ids is not None:
        edge["parent_event_ids"] = sorted(
            set(parent_event_ids), key=lambda item: item.encode("utf-8")
        )
    if child_event_ids is not None:
        edge["child_event_ids"] = sorted(
            set(child_event_ids), key=lambda item: item.encode("utf-8")
        )
    if trigger_observation_ids is not None:
        edge["trigger_observation_ids"] = sorted(
            set(trigger_observation_ids), key=lambda item: item.encode("utf-8")
        )
    digest = identity_sha256(
        "lineage-v2",
        edge["relation"],
        LINE_FEED.join(edge["parent_event_ids"]),
        LINE_FEED.join(edge["child_event_ids"]),
        edge["effective_acquisition_id"],
        edge["effective_timestamp_utc"],
        LINE_FEED.join(edge["trigger_observation_ids"]),
        edge["algorithm_version"],
    )
    new_lineage_id = "lin-v2-" + digest
    edge["lineage_id"] = new_lineage_id
    edge["identity_inputs_sha256"] = digest

    for event in state["events"]:
        event["incoming_lineage_ids"] = [
            item
            for item in event["incoming_lineage_ids"]
            if item != old_lineage_id
        ]
        event["outgoing_lineage_ids"] = [
            item
            for item in event["outgoing_lineage_ids"]
            if item != old_lineage_id
        ]
        if event["event_id"] in edge["child_event_ids"]:
            event["incoming_lineage_ids"].append(new_lineage_id)
        if event["event_id"] in edge["parent_event_ids"]:
            event["outgoing_lineage_ids"].append(new_lineage_id)
        event["incoming_lineage_ids"] = sorted(
            set(event["incoming_lineage_ids"]),
            key=lambda item: item.encode("utf-8"),
        )
        event["outgoing_lineage_ids"] = sorted(
            set(event["outgoing_lineage_ids"]),
            key=lambda item: item.encode("utf-8"),
        )

    for event in state["events"]:
        is_replaced = any(
            candidate["relation"] in {"split", "merge"}
            and event["event_id"] in candidate["parent_event_ids"]
            for candidate in state["lineage"]
        )
        event["status"] = "superseded" if is_replaced else "active"


def _reseal_tampered_state(state: dict) -> dict:
    """Recompute all outer state identities/integrity after semantic tampering."""

    return _seal_state(deepcopy(state))


def _recompute_ledger_outer_checksums(payload: dict) -> dict:
    """Keep every enclosing checksum valid while retaining a bad row digest."""

    tampered = deepcopy(payload)
    rows_by_date: dict[str, list[dict]] = {}
    for row in tampered["terminal_rows"]:
        rows_by_date.setdefault(row["observed_on"], []).append(row)
    for summary in tampered["daily_summaries"]:
        summary["terminal_rows_sha256"] = canonical_sha256(
            rows_by_date[summary["observed_on"]]
        )
        summary_without_digest = deepcopy(summary)
        del summary_without_digest["daily_summary_sha256"]
        summary["daily_summary_sha256"] = canonical_sha256(
            summary_without_digest
        )
    tampered["integrity"]["terminal_rows_sha256"] = canonical_sha256(
        tampered["terminal_rows"]
    )
    tampered["integrity"]["daily_summaries_sha256"] = canonical_sha256(
        tampered["daily_summaries"]
    )
    without_document_checksum = deepcopy(tampered)
    del without_document_checksum["integrity"]["document_sha256"]
    tampered["integrity"]["document_sha256"] = canonical_sha256(
        without_document_checksum
    )
    return tampered


def test_manifest_rejects_duplicate_physical_datatake_key_with_distinct_scene_sets():
    first = _acquisition(
        "2026-06-03",
        "10:00:00",
        "DT-PHYSICAL",
        scene_ids=("scene-a",),
    )
    duplicate_physical_datatake = _acquisition(
        "2026-06-03",
        "10:00:00",
        "DT-PHYSICAL",
        scene_ids=("scene-b",),
    )
    assert first.acquisition_id != duplicate_physical_datatake.acquisition_id

    with pytest.raises(ValueError, match="physical|datatake|duplicate"):
        ProcessingLedgerV2(
            run_manifest_id=RUN_MANIFEST_ID,
            run_manifest_sha256=RUN_MANIFEST_SHA256,
            acquisitions=[first, duplicate_physical_datatake],
            monitoring_extent_id=MONITORING_EXTENT_ID,
            algorithm_version=ALGORITHM_VERSION,
            created_at=CREATED_AT,
        )


def test_semantic_ledger_validator_rejects_bad_terminal_record_digest():
    acquisition = _acquisition("2026-06-04", "10:00:00", "DT-LEDGER-HASH")
    ledger = _ledger([acquisition])
    payload = ledger.to_dict()
    payload["terminal_rows"][0]["terminal_record_sha256"] = "0" * 64
    tampered = _recompute_ledger_outer_checksums(payload)

    with pytest.raises(ContractV2ValidationError):
        ledger_v2.validate_processing_ledger_v2(tampered)


def test_ledger_serializer_runs_semantic_validation_before_emitting_bytes():
    acquisition = _acquisition("2026-06-04", "11:00:00", "DT-SERIALIZE-HASH")
    ledger = _ledger([acquisition])
    ledger._rows[acquisition.acquisition_id]["terminal_record_sha256"] = "0" * 64

    with pytest.raises(ContractV2ValidationError):
        ledger.to_bytes()


def test_same_observation_id_with_changed_scientific_bytes_is_not_a_no_op():
    ledger, acquisition, observation, applied = _single_day_history()
    changed = observation.to_dict()
    changed["area_ha"] = changed["area_ha"] * 2
    assert ObservationV2.from_dict(
        changed, acquisition=acquisition
    ).observation_id == observation.observation_id

    with pytest.raises(
        (
            LateArrivalRequiresRebuild,
            ObservationLedgerMismatch,
            ContractV2ValidationError,
        )
    ):
        apply_terminal_date_v2(
            state=applied.state,
            ledger=ledger,
            observed_on=acquisition.observed_on,
            observations=[changed],
            transitioned_at="2026-06-05T12:00:00Z",
        )


def test_observation_payload_export_cannot_mutate_the_source_record():
    acquisition = _acquisition("2026-06-04", "12:00:00", "DT-IMMUTABLE")
    observation = _observation(acquisition)
    original = observation.to_dict()
    exported = observation.to_dict()

    exported["geometry"]["coordinates"][0][0][0] = -1.0
    exported["raw_detection_policy"]["retained"] = False

    assert observation.to_dict() == original


def test_retry_manifest_provenance_changes_are_a_byte_identical_state_no_op():
    old_ledger, acquisition, observation, applied = _single_day_history()
    new_manifest_id = "run-v2-" + "7" * 64
    new_manifest_sha256 = "8" * 64
    retry_acquisition = create_acquisition_v2(
        run_manifest_id=new_manifest_id,
        run_manifest_sha256=new_manifest_sha256,
        collection_id=acquisition.collection_id,
        platform=acquisition.platform,
        datatake_id=acquisition.datatake_id,
        acquisition_timestamp_utc=acquisition.acquisition_timestamp_utc,
        scene_ids=acquisition.scene_ids,
        monitoring_extent_id=acquisition.monitoring_extent_id,
        composite_method_id=acquisition.composite_method_id,
        grid_id=acquisition.grid_id,
    )
    assert retry_acquisition.acquisition_id == acquisition.acquisition_id
    retry_observation = create_observation_v2(
        acquisition=retry_acquisition,
        geometry=observation.to_dict()["geometry"],
        algorithm_version=ALGORITHM_VERSION,
        baseline_version=BASELINE_VERSION,
        area_ha=observation.to_dict()["area_ha"],
        created_at="2026-06-07T12:00:00Z",
    )
    assert retry_observation.observation_id == observation.observation_id
    retry_ledger = ProcessingLedgerV2(
        run_manifest_id=new_manifest_id,
        run_manifest_sha256=new_manifest_sha256,
        acquisitions=[retry_acquisition],
        monitoring_extent_id=MONITORING_EXTENT_ID,
        algorithm_version=ALGORITHM_VERSION,
        created_at="2026-06-07T12:00:00Z",
    )
    old_artifact = old_ledger.terminal_rows[0]["output"]["artifact_sha256"]
    retry_ledger.record_terminal(
        acquisition_id=retry_acquisition.acquisition_id,
        status="complete_with_alerts",
        observation_ids=[retry_observation.observation_id],
        artifact_sha256=old_artifact,
        terminal_at="2026-06-07T12:05:00Z",
    )

    retry = apply_terminal_date_v2(
        state=applied.state,
        ledger=retry_ledger,
        observed_on=acquisition.observed_on,
        observations=[retry_observation],
        transitioned_at="2026-06-07T12:10:00Z",
    )

    assert retry.outcome == "no_op_replay"
    assert retry.state_changed is False
    assert retry.state is applied.state


def test_non_contract_confirmed_threshold_is_rejected_before_state_mutation():
    ledger, acquisition, observation, _ = _single_day_history()
    state = _empty_state(ledger)
    before = deepcopy(state)

    with pytest.raises(ValueError):
        apply_terminal_date_v2(
            state=state,
            ledger=ledger,
            observed_on=acquisition.observed_on,
            observations=[observation],
            transitioned_at="2026-06-01T23:59:59Z",
            confirmed_min=2,
        )

    assert state == before


@pytest.mark.parametrize(
    "policy_override",
    [
        {"grace_days": 179},
        {"min_overlap_frac": 0.06},
    ],
)
def test_non_contract_lineage_policy_is_rejected_before_state_mutation(
    policy_override,
):
    ledger, acquisition, observation, _ = _single_day_history()
    state = _empty_state(ledger)
    before = deepcopy(state)

    with pytest.raises(ValueError, match="threshold|policy|invalid"):
        apply_terminal_date_v2(
            state=state,
            ledger=ledger,
            observed_on=acquisition.observed_on,
            observations=[observation],
            transitioned_at="2026-06-01T23:59:59Z",
            **policy_override,
        )

    assert state == before


def test_ledger_and_empty_state_identities_bind_runtime_versions():
    acquisition = _acquisition("2026-06-01", "10:00:00", "DT-BINDING")
    default_ledger = _ledger([acquisition])
    different_algorithm = ProcessingLedgerV2(
        run_manifest_id=RUN_MANIFEST_ID,
        run_manifest_sha256=RUN_MANIFEST_SHA256,
        acquisitions=[acquisition],
        monitoring_extent_id=MONITORING_EXTENT_ID,
        algorithm_version="2.0.1",
        created_at=CREATED_AT,
    )
    different_algorithm.record_terminal(
        acquisition_id=acquisition.acquisition_id,
        status="complete_zero_alerts",
        artifact_sha256=canonical_sha256([]),
        terminal_at="2026-06-01T23:59:59Z",
    )

    assert default_ledger.ledger_id != different_algorithm.ledger_id
    default_state = _empty_state(default_ledger)
    different_baseline_state = empty_persistence_state_v2(
        generation_id=GENERATION_ID,
        ledger=default_ledger,
        baseline_version="2.0.1",
        generated_at=CREATED_AT,
    )
    assert default_state["state_id"] != different_baseline_state["state_id"]


def test_state_validator_rejects_tier_tampering_after_outer_reseal():
    *_, applied = _single_day_history()
    tampered = deepcopy(applied.state)
    tampered["events"][0]["persistence_tier"] = "confirmed"

    with pytest.raises(ContractV2ValidationError, match="tier|persistence"):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_state_validator_rejects_status_without_replacing_lineage():
    *_, applied = _single_day_history()
    tampered = deepcopy(applied.state)
    tampered["events"][0]["status"] = "superseded"

    with pytest.raises(ContractV2ValidationError, match="status|lineage"):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_state_validator_rejects_unreconciled_last_transition():
    *_, applied = _single_day_history()
    tampered = deepcopy(applied.state)
    tampered["last_transition"] = {
        "outcome": "initialized",
        "observed_on": None,
        "date_input_digest": None,
        "new_contribution_count": 0,
        "duplicate_contribution_count": 0,
        "state_changed": False,
    }

    with pytest.raises(ContractV2ValidationError, match="transition|finalized"):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_state_validator_rejects_duplicate_event_ids_after_outer_reseal():
    *_, applied = _single_day_history()
    tampered = deepcopy(applied.state)
    tampered["events"].append(deepcopy(tampered["events"][0]))

    with pytest.raises(
        ContractV2ValidationError, match="duplicate event|non-unique"
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_state_validator_rejects_geometry_hash_tampering_after_outer_reseal():
    *_, applied = _single_day_history()
    tampered = deepcopy(applied.state)
    new_geometry, _ = canonical_geometry_sha256(
        box(-40.20, -7.20, -40.18, -7.18)
    )
    tampered["events"][0]["representative_geometry"] = new_geometry

    with pytest.raises(ContractV2ValidationError, match="geometry|hash"):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_state_geometry_and_hash_must_derive_a_retained_observation_id():
    *_, applied = _single_day_history()
    tampered = deepcopy(applied.state)
    event = tampered["events"][0]
    new_geometry, new_geometry_hash = canonical_geometry_sha256(
        box(-40.20, -7.20, -40.18, -7.18)
    )
    event["representative_geometry"] = new_geometry
    event["representative_geometry_sha256"] = new_geometry_hash

    derived_ids = {
        observation_id_v2(
            acquisition_id,
            new_geometry_hash,
            tampered["algorithm_version"],
            tampered["baseline_version"],
        )
        for acquisition_id in event["acquisition_ids"]
    }
    assert derived_ids.isdisjoint(event["observation_ids"])

    with pytest.raises(
        ContractV2ValidationError, match="geometry|observation|identity"
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_state_validator_rederives_event_identity_after_outer_reseal():
    *_, applied = _single_day_history()
    tampered = deepcopy(applied.state)
    event = tampered["events"][0]
    contribution = tampered["contributions"][0]
    finalized = tampered["finalized_dates"][0]
    forged_event_id = "evt-v2-" + "e" * 64
    forged_key = contribution_key_v2(
        forged_event_id, contribution["observed_on"]
    )

    event["event_id"] = forged_event_id
    event["identity_inputs_sha256"] = "e" * 64
    event["contribution_keys"] = [forged_key]
    contribution["event_id"] = forged_event_id
    contribution["contribution_key"] = forged_key
    contribution["identity_inputs_sha256"] = forged_key.removeprefix("pc-v2-")
    finalized["contribution_keys"] = [forged_key]

    with pytest.raises(ContractV2ValidationError, match="event|identity"):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_origin_rekey_cannot_move_first_observation_to_a_later_date():
    _, _, observations, _, second = _two_day_history()
    first_observation, second_observation = observations
    tampered = deepcopy(second.state)
    event = tampered["events"][0]
    old_event_id = event["event_id"]
    new_event_id = origin_event_id_v2(second_observation.observation_id)
    assert first_observation.observation_id in event["observation_ids"]
    assert second_observation.observation_id in event["observation_ids"]
    assert new_event_id != old_event_id

    event["event_id"] = new_event_id
    event["identity_inputs_sha256"] = new_event_id.removeprefix("evt-v2-")
    event["identity_basis"]["first_observation_id"] = (
        second_observation.observation_id
    )
    event["identity_basis"]["trigger_observation_ids"] = [
        second_observation.observation_id
    ]

    key_mapping: dict[str, str] = {}
    for contribution in tampered["contributions"]:
        old_key = contribution["contribution_key"]
        new_key = contribution_key_v2(
            new_event_id, contribution["observed_on"]
        )
        key_mapping[old_key] = new_key
        contribution["event_id"] = new_event_id
        contribution["contribution_key"] = new_key
        contribution["identity_inputs_sha256"] = new_key.removeprefix(
            "pc-v2-"
        )
    event["contribution_keys"] = sorted(
        key_mapping.values(), key=lambda item: item.encode("utf-8")
    )
    for finalized in tampered["finalized_dates"]:
        finalized["contribution_keys"] = sorted(
            (key_mapping[item] for item in finalized["contribution_keys"]),
            key=lambda item: item.encode("utf-8"),
        )

    continuation = next(
        edge
        for edge in tampered["lineage"]
        if edge["relation"] == "continuation"
    )
    assert continuation["parent_event_ids"] == [old_event_id]
    assert continuation["child_event_ids"] == [old_event_id]
    _rewrite_lineage_edge(
        tampered,
        continuation,
        parent_event_ids=[new_event_id],
        child_event_ids=[new_event_id],
    )

    first_date_contribution = next(
        item
        for item in tampered["contributions"]
        if item["observed_on"] == event["first_observed_on"]
    )
    assert (
        second_observation.observation_id
        not in first_date_contribution["source_observation_ids"]
    )

    with pytest.raises(
        ContractV2ValidationError,
        match="first|origin|observation|contribution",
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_state_validator_enforces_lineage_reciprocity_after_outer_reseal():
    *_, second = _two_day_history()
    tampered = deepcopy(second.state)
    assert tampered["lineage"]
    assert tampered["events"][0]["outgoing_lineage_ids"]
    tampered["events"][0]["outgoing_lineage_ids"] = []

    with pytest.raises(ContractV2ValidationError, match="lineage|outgoing"):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_continuation_lineage_must_be_a_parent_equals_child_self_edge():
    _, observations, _, second = _parallel_continuation_history()
    tampered = deepcopy(second.state)
    day_two_a, day_two_b = observations[2:]
    event_a = second.observation_assignments[day_two_a.observation_id]["event_id"]
    event_b = second.observation_assignments[day_two_b.observation_id]["event_id"]
    edge = next(
        item
        for item in tampered["lineage"]
        if item["relation"] == "continuation"
        and item["parent_event_ids"] == [event_a]
    )

    _rewrite_lineage_edge(
        tampered,
        edge,
        child_event_ids=[event_b],
        trigger_observation_ids=[day_two_b.observation_id],
    )

    with pytest.raises(
        (ContractV2ValidationError, ValueError),
        match="continuation|self|parent|child",
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_split_child_identity_basis_must_match_its_lineage_parent():
    observations, first, second = _split_with_parallel_parent_history()
    origin, parallel, _, _ = observations
    tampered = deepcopy(second.state)
    original_parent_id = first.observation_assignments[origin.observation_id][
        "event_id"
    ]
    alternate_parent_id = first.observation_assignments[parallel.observation_id][
        "event_id"
    ]
    edge = next(
        item for item in tampered["lineage"] if item["relation"] == "split"
    )
    assert edge["parent_event_ids"] == [original_parent_id]
    assert all(
        next(
            event
            for event in tampered["events"]
            if event["event_id"] == child_id
        )["identity_basis"]["parent_event_ids"]
        == [original_parent_id]
        for child_id in edge["child_event_ids"]
    )

    _rewrite_lineage_edge(
        tampered,
        edge,
        parent_event_ids=[alternate_parent_id],
    )

    with pytest.raises(
        (ContractV2ValidationError, ValueError),
        match="split|identity|basis|lineage|parent|children",
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_merge_child_identity_basis_must_match_all_lineage_parents():
    _, first, _, third = _split_merge_history()
    tampered = deepcopy(third.state)
    origin_id = next(iter(first.observation_assignments.values()))["event_id"]
    edge = next(
        item for item in tampered["lineage"] if item["relation"] == "merge"
    )
    original_parent_ids = list(edge["parent_event_ids"])
    child = next(
        event
        for event in tampered["events"]
        if event["event_id"] == edge["child_event_ids"][0]
    )
    assert child["identity_basis"]["parent_event_ids"] == original_parent_ids
    mismatched_parents = [origin_id, original_parent_ids[0]]

    _rewrite_lineage_edge(
        tampered,
        edge,
        parent_event_ids=mismatched_parents,
    )

    with pytest.raises(
        (ContractV2ValidationError, ValueError),
        match="merge|identity|basis|lineage|parent|child",
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_lineage_trigger_must_belong_to_the_corresponding_child_event():
    _, observations, _, second = _parallel_continuation_history()
    tampered = deepcopy(second.state)
    day_two_a, day_two_b = observations[2:]
    event_a = second.observation_assignments[day_two_a.observation_id]["event_id"]
    event_b = second.observation_assignments[day_two_b.observation_id]["event_id"]
    assert event_a != event_b
    edge = next(
        item
        for item in tampered["lineage"]
        if item["relation"] == "continuation"
        and item["child_event_ids"] == [event_a]
    )
    child = next(
        event for event in tampered["events"] if event["event_id"] == event_a
    )
    assert day_two_b.observation_id not in child["observation_ids"]

    _rewrite_lineage_edge(
        tampered,
        edge,
        trigger_observation_ids=[day_two_b.observation_id],
    )

    with pytest.raises(
        ContractV2ValidationError, match="trigger|observation|child|lineage"
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_lineage_effective_timestamp_must_use_canonical_utc_spelling():
    *_, second = _two_day_history()
    tampered = deepcopy(second.state)
    edge = tampered["lineage"][0]
    original_id = edge["lineage_id"]
    original_timestamp = edge["effective_timestamp_utc"]
    assert original_timestamp.endswith(":00Z")
    edge["effective_timestamp_utc"] = original_timestamp.removesuffix(
        "Z"
    ) + ".000Z"
    assert edge["lineage_id"] == original_id

    with pytest.raises(
        (ContractV2ValidationError, ValueError),
        match="timestamp|canonical|lineage",
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


@pytest.mark.parametrize(
    "timestamp_field",
    ["generated_at", "watermark.acquisition_timestamp_utc"],
)
def test_state_timestamps_must_use_canonical_utc_spelling(timestamp_field):
    *_, applied = _single_day_history()
    tampered = deepcopy(applied.state)
    if timestamp_field == "generated_at":
        original_timestamp = tampered["generated_at"]
        tampered["generated_at"] = original_timestamp.removesuffix(
            "Z"
        ) + ".000Z"
    else:
        original_timestamp = tampered["watermark"][
            "acquisition_timestamp_utc"
        ]
        tampered["watermark"]["acquisition_timestamp_utc"] = (
            original_timestamp.removesuffix("Z") + ".000Z"
        )

    with pytest.raises(
        (ContractV2ValidationError, ValueError),
        match="timestamp|canonical|generated|watermark",
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_state_validator_rejects_unknown_finalized_contribution_reference():
    *_, applied = _single_day_history()
    tampered = deepcopy(applied.state)
    ghost_key = "pc-v2-" + "f" * 64
    finalized = tampered["finalized_dates"][0]
    finalized["contribution_keys"] = sorted(
        [*finalized["contribution_keys"], ghost_key],
        key=lambda item: item.encode("utf-8"),
    )

    with pytest.raises(ContractV2ValidationError, match="finalized|contribution"):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_state_validator_rejects_consistently_deleted_date_contribution():
    *_, second = _two_day_history()
    tampered = deepcopy(second.state)
    deleted = next(
        item
        for item in tampered["contributions"]
        if item["observed_on"] == "2026-06-02"
    )
    deleted_key = deleted["contribution_key"]
    tampered["contributions"] = [
        item
        for item in tampered["contributions"]
        if item["contribution_key"] != deleted_key
    ]
    tampered["events"][0]["contribution_keys"] = [
        key
        for key in tampered["events"][0]["contribution_keys"]
        if key != deleted_key
    ]
    finalized = next(
        item
        for item in tampered["finalized_dates"]
        if item["observed_on"] == "2026-06-02"
    )
    finalized["contribution_keys"] = []

    with pytest.raises(
        ContractV2ValidationError, match="date|contribution|transition"
    ):
        validate_persistence_state_v2(_reseal_tampered_state(tampered))


def test_invalid_reason_code_fails_before_terminal_ledger_mutation():
    acquisition = _acquisition("2026-06-05", "10:00:00", "DT-BAD-REASON")
    ledger = ProcessingLedgerV2(
        run_manifest_id=RUN_MANIFEST_ID,
        run_manifest_sha256=RUN_MANIFEST_SHA256,
        acquisitions=[acquisition],
        monitoring_extent_id=MONITORING_EXTENT_ID,
        algorithm_version=ALGORITHM_VERSION,
        created_at=CREATED_AT,
    )
    before = ledger.terminal_rows

    with pytest.raises(ValueError, match="reason|code|lowercase"):
        ledger.record_terminal(
            acquisition_id=acquisition.acquisition_id,
            status="rejected_quality",
            reason={"code": "INVALID CODE", "message": "bad quality"},
            terminal_at="2026-06-05T23:59:59Z",
        )

    assert ledger.terminal_rows == before == ()
    assert ledger.is_date_terminal(acquisition.observed_on) is False


def test_transition_cannot_precede_latest_terminal_row_and_is_atomic():
    early = _acquisition("2026-06-17", "10:00:00", "DT-TERMINAL-EARLY")
    late = _acquisition(
        "2026-06-17",
        "11:00:00",
        "DT-TERMINAL-LATE",
        platform="S2B",
    )
    ledger = ProcessingLedgerV2(
        run_manifest_id=RUN_MANIFEST_ID,
        run_manifest_sha256=RUN_MANIFEST_SHA256,
        acquisitions=[late, early],
        monitoring_extent_id=MONITORING_EXTENT_ID,
        algorithm_version=ALGORITHM_VERSION,
        created_at="2026-06-17T12:00:00Z",
    )
    ledger.record_terminal(
        acquisition_id=early.acquisition_id,
        status="complete_zero_alerts",
        terminal_at="2026-06-17T18:00:00Z",
        artifact_sha256=canonical_sha256([]),
    )
    ledger.record_terminal(
        acquisition_id=late.acquisition_id,
        status="complete_zero_alerts",
        terminal_at="2026-06-17T20:00:00Z",
        artifact_sha256=canonical_sha256([]),
    )
    state = empty_persistence_state_v2(
        generation_id=GENERATION_ID,
        ledger=ledger,
        baseline_version=BASELINE_VERSION,
        generated_at="2026-06-17T12:00:00Z",
    )
    before = deepcopy(state)

    with pytest.raises(
        PersistenceV2Error, match="transition|terminal|precede"
    ):
        apply_terminal_date_v2(
            state=state,
            ledger=ledger,
            observed_on="2026-06-17",
            observations=[],
            transitioned_at="2026-06-17T19:00:00Z",
        )

    assert state == before
    assert state["finalized_dates"] == []
    assert state["contributions"] == []


def test_old_date_replay_returns_the_original_historical_assignments():
    ledger, acquisitions, observations, first, second = _two_day_history()

    replay = apply_terminal_date_v2(
        state=second.state,
        ledger=ledger,
        observed_on=acquisitions[0].observed_on,
        observations=[observations[0]],
        transitioned_at="2026-06-03T12:00:00Z",
    )

    assert replay.outcome == "no_op_replay"
    assert replay.state_changed is False
    assert replay.observation_assignments == first.observation_assignments


def test_fractional_utc_timestamps_are_ordered_by_instant_not_lexically():
    whole_second = _acquisition("2026-06-06", "10:00:00", "DT-WHOLE")
    fractional_later = _acquisition(
        "2026-06-06", "10:00:00.9", "DT-FRACTIONAL", platform="S2B"
    )
    assert (
        fractional_later.acquisition_timestamp_utc
        < whole_second.acquisition_timestamp_utc
    )  # Deliberately demonstrates the lexical trap.

    ledger = _ledger([fractional_later, whole_second])

    assert ledger.acquisitions == (whole_second, fractional_later)
    assert [
        item["acquisition_id"] for item in ledger.to_dict()["expected_acquisitions"]
    ] == [whole_second.acquisition_id, fractional_later.acquisition_id]
