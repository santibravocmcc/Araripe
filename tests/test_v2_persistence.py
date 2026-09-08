"""Focused executable rules for the Package 2A.6A persistence contract."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Mapping, Sequence

import pytest
from shapely.geometry import box

from src.detection.identity import canonical_sha256
from src.detection.identity_v2 import (
    AcquisitionV2,
    ObservationV2,
    acquisition_order_key,
    create_acquisition_v2,
    create_observation_v2,
    origin_event_id_v2,
)
from src.detection.ledger_v2 import ProcessingLedgerV2
from src.detection.persistence_v2 import (
    LateArrivalRequiresRebuild,
    OutOfOrderRequiresRebuild,
    apply_terminal_date_v2,
    empty_persistence_state_v2,
    persistence_state_bytes_v2,
    rebuild_persistence_state_v2,
)


RUN_MANIFEST_ID = "run-v2-" + "1" * 64
RUN_MANIFEST_SHA256 = "2" * 64
GENERATION_ID = "gen-v2-" + "3" * 64
MONITORING_EXTENT_ID = "araripe-implementation-rectangle-v1"
ALGORITHM_VERSION = "2.0.0"
BASELINE_VERSION = "2.0.0"
CREATED_AT = "2026-08-13T12:00:00Z"


def _byte_sorted(values: Iterable[str]) -> list[str]:
    return sorted(values, key=lambda value: value.encode("utf-8"))


def _acquisition(
    observed_on: str,
    time_utc: str,
    datatake_id: str,
    *,
    platform: str = "S2A",
    run_manifest_id: str = RUN_MANIFEST_ID,
    run_manifest_sha256: str = RUN_MANIFEST_SHA256,
) -> AcquisitionV2:
    return create_acquisition_v2(
        run_manifest_id=run_manifest_id,
        run_manifest_sha256=run_manifest_sha256,
        collection_id="COPERNICUS_S2_SR_HARMONIZED",
        platform=platform,
        datatake_id=datatake_id,
        acquisition_timestamp_utc=f"{observed_on}T{time_utc}Z",
        scene_ids=(f"{datatake_id}-tile-b", f"{datatake_id}-tile-a"),
        monitoring_extent_id=MONITORING_EXTENT_ID,
        composite_method_id="coverage-ranked-first-valid-by-datatake-v2",
        grid_id="araripe-detector-grid-20m-v2",
    )


def _observation(
    acquisition: AcquisitionV2,
    geometry,
    *,
    created_at: str | None = None,
) -> ObservationV2:
    return create_observation_v2(
        acquisition=acquisition,
        geometry=geometry,
        algorithm_version=ALGORITHM_VERSION,
        baseline_version=BASELINE_VERSION,
        area_ha=1.0,
        created_at=created_at or acquisition.acquisition_timestamp_utc,
    )


def _terminal_ledger(
    acquisitions: Sequence[AcquisitionV2],
    observations: Sequence[ObservationV2] = (),
    *,
    terminal_order: Sequence[AcquisitionV2] | None = None,
    statuses: Mapping[str, str] | None = None,
) -> ProcessingLedgerV2:
    if not acquisitions:
        raise ValueError("test ledger needs at least one acquisition")
    first = acquisitions[0]
    ledger = ProcessingLedgerV2(
        run_manifest_id=first.run_manifest_id,
        run_manifest_sha256=first.run_manifest_sha256,
        acquisitions=acquisitions,
        monitoring_extent_id=MONITORING_EXTENT_ID,
        algorithm_version=ALGORITHM_VERSION,
        created_at=CREATED_AT,
    )
    observations_by_acquisition: dict[str, list[str]] = defaultdict(list)
    for observation in observations:
        observations_by_acquisition[observation.acquisition_id].append(
            observation.observation_id
        )
    for acquisition in terminal_order or acquisitions:
        observation_ids = observations_by_acquisition[acquisition.acquisition_id]
        status = (statuses or {}).get(
            acquisition.acquisition_id,
            "complete_with_alerts" if observation_ids else "complete_zero_alerts",
        )
        ledger.record_terminal(
            acquisition_id=acquisition.acquisition_id,
            status=status,
            observation_ids=observation_ids,
            terminal_at=f"{acquisition.observed_on}T23:59:59Z",
            artifact_sha256=canonical_sha256(
                {
                    "acquisition_id": acquisition.acquisition_id,
                    "observation_ids": _byte_sorted(observation_ids),
                }
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


def test_same_day_datatakes_are_independent_observations_but_one_contribution():
    early = _acquisition("2026-04-07", "10:00:00", "DT-EARLY", platform="S2A")
    late = _acquisition("2026-04-07", "10:10:00", "DT-LATE", platform="S2B")
    footprint = box(-40.10, -7.10, -40.08, -7.08)
    early_observation = _observation(early, footprint)
    late_observation = _observation(late, footprint)
    ledger = _terminal_ledger(
        [late, early],
        [late_observation, early_observation],
        terminal_order=[late, early],
    )

    transition = apply_terminal_date_v2(
        state=_empty_state(ledger),
        ledger=ledger,
        observed_on="2026-04-07",
        observations=[late_observation, early_observation],
        transitioned_at="2026-04-07T23:59:59Z",
    )

    assert early.acquisition_id != late.acquisition_id
    assert early_observation.observation_id != late_observation.observation_id
    assert ledger.acquisitions == (early, late)
    assert transition.outcome == "applied"
    assert transition.state_changed is True
    assert len(transition.state["events"]) == 1
    assert len(transition.state["contributions"]) == 1

    event = transition.state["events"][0]
    contribution = transition.state["contributions"][0]
    assert event["identity_basis"]["first_observation_id"] == (
        early_observation.observation_id
    )
    assert event["n_distinct_observation_dates"] == 1
    assert event["observation_dates"] == ["2026-04-07"]
    assert event["acquisition_ids"] == _byte_sorted(
        [early.acquisition_id, late.acquisition_id]
    )
    assert event["observation_ids"] == _byte_sorted(
        [early_observation.observation_id, late_observation.observation_id]
    )
    assert contribution["event_id"] == event["event_id"]
    assert contribution["source_acquisition_ids"] == event["acquisition_ids"]
    assert contribution["source_observation_ids"] == event["observation_ids"]
    assert transition.state["finalized_dates"][0]["contribution_keys"] == [
        contribution["contribution_key"]
    ]
    assert {
        assignment["event_id"]
        for assignment in transition.observation_assignments.values()
    } == {event["event_id"]}
    assert {
        assignment["contribution_key"]
        for assignment in transition.observation_assignments.values()
    } == {contribution["contribution_key"]}
    assert transition.state["watermark"] == {
        "observed_on": "2026-04-07",
        "acquisition_timestamp_utc": late.acquisition_timestamp_utc,
        "acquisition_id": late.acquisition_id,
    }


def test_exact_retry_is_no_op_and_keeps_state_bytes_identical():
    acquisition = _acquisition("2026-05-01", "13:00:00", "DT-RETRY")
    observation = _observation(
        acquisition, box(-40.20, -7.20, -40.18, -7.18)
    )
    ledger = _terminal_ledger([acquisition], [observation])
    applied = apply_terminal_date_v2(
        state=_empty_state(ledger),
        ledger=ledger,
        observed_on="2026-05-01",
        observations=[observation],
        transitioned_at="2026-05-01T23:59:59Z",
    )
    before = persistence_state_bytes_v2(applied.state)

    replay = apply_terminal_date_v2(
        state=applied.state,
        ledger=ledger,
        observed_on="2026-05-01",
        observations=[observation],
        transitioned_at="2026-05-03T10:00:00Z",
    )

    assert replay.outcome == "no_op_replay"
    assert replay.state_changed is False
    assert replay.observation_assignments == applied.observation_assignments
    assert persistence_state_bytes_v2(replay.state) == before
    assert persistence_state_bytes_v2(applied.state) == before


def test_zero_alert_terminal_date_closes_without_a_contribution():
    acquisition = _acquisition("2026-05-02", "13:00:00", "DT-ZERO")
    ledger = _terminal_ledger([acquisition])

    transition = apply_terminal_date_v2(
        state=_empty_state(ledger),
        ledger=ledger,
        observed_on="2026-05-02",
        observations=[],
        transitioned_at="2026-05-02T23:59:59Z",
    )

    assert transition.outcome == "applied"
    assert transition.observation_assignments == {}
    assert transition.state["events"] == []
    assert transition.state["lineage"] == []
    assert transition.state["contributions"] == []
    assert transition.state["finalized_dates"] == [
        {
            "observed_on": "2026-05-02",
            "run_manifest_id": RUN_MANIFEST_ID,
            "run_manifest_sha256": RUN_MANIFEST_SHA256,
            "date_input_digest": ledger.date_input_digest("2026-05-02", []),
            "daily_summary_sha256": ledger.daily_summary("2026-05-02")[
                "daily_summary_sha256"
            ],
            "contribution_keys": [],
        }
    ]


def test_input_order_is_invariant_and_processing_uses_timestamp_then_id():
    tie_a = _acquisition("2026-05-03", "10:00:00", "DT-TIE-A", platform="S2A")
    tie_b = _acquisition("2026-05-03", "10:00:00", "DT-TIE-B", platform="S2B")
    later = _acquisition("2026-05-03", "10:10:00", "DT-LATER", platform="S2A")
    acquisitions = [later, tie_b, tie_a]
    footprint = box(-40.30, -7.30, -40.28, -7.28)
    observations = [_observation(item, footprint) for item in acquisitions]
    by_acquisition = {
        item.acquisition_id: observation
        for item, observation in zip(acquisitions, observations)
    }
    expected_order = tuple(sorted(acquisitions, key=acquisition_order_key))

    ledger_a = _terminal_ledger(
        acquisitions,
        observations,
        terminal_order=[tie_b, later, tie_a],
    )
    ledger_b = _terminal_ledger(
        list(reversed(acquisitions)),
        list(reversed(observations)),
        terminal_order=[tie_a, tie_b, later],
    )
    result_a = apply_terminal_date_v2(
        state=_empty_state(ledger_a),
        ledger=ledger_a,
        observed_on="2026-05-03",
        observations=[observations[1], observations[2], observations[0]],
        transitioned_at="2026-05-03T23:59:59Z",
    )
    result_b = apply_terminal_date_v2(
        state=_empty_state(ledger_b),
        ledger=ledger_b,
        observed_on="2026-05-03",
        observations=list(reversed(observations)),
        transitioned_at="2026-05-03T23:59:59Z",
    )

    assert ledger_a.acquisitions == expected_order
    assert ledger_b.acquisitions == expected_order
    assert ledger_a.to_bytes() == ledger_b.to_bytes()
    assert persistence_state_bytes_v2(result_a.state) == persistence_state_bytes_v2(
        result_b.state
    )
    assert result_a.state["events"][0]["identity_basis"][
        "first_observation_id"
    ] == by_acquisition[expected_order[0].acquisition_id].observation_id
    assert result_a.state["watermark"]["acquisition_id"] == expected_order[
        -1
    ].acquisition_id


def test_changed_observations_for_finalized_same_day_require_rebuild_without_mutation():
    acquisition = _acquisition("2026-05-04", "10:00:00", "DT-OBS-CHANGE")
    original_observation = _observation(
        acquisition, box(-40.40, -7.40, -40.38, -7.38)
    )
    original_ledger = _terminal_ledger([acquisition], [original_observation])
    applied = apply_terminal_date_v2(
        state=_empty_state(original_ledger),
        ledger=original_ledger,
        observed_on="2026-05-04",
        observations=[original_observation],
        transitioned_at="2026-05-04T23:59:59Z",
    )
    original_bytes = persistence_state_bytes_v2(applied.state)

    changed_observation = _observation(
        acquisition, box(-40.40, -7.40, -40.37, -7.37)
    )
    changed_ledger = _terminal_ledger([acquisition], [changed_observation])
    with pytest.raises(LateArrivalRequiresRebuild):
        apply_terminal_date_v2(
            state=applied.state,
            ledger=changed_ledger,
            observed_on="2026-05-04",
            observations=[changed_observation],
            transitioned_at="2026-05-05T12:00:00Z",
        )

    assert persistence_state_bytes_v2(applied.state) == original_bytes
    assert changed_observation.observation_id not in original_bytes.decode("utf-8")


def test_late_same_day_manifest_acquisition_requires_rebuild_without_mutation():
    original_acquisition = _acquisition(
        "2026-05-05", "10:00:00", "DT-ORIGINAL", platform="S2A"
    )
    original_observation = _observation(
        original_acquisition, box(-40.50, -7.50, -40.48, -7.48)
    )
    original_ledger = _terminal_ledger(
        [original_acquisition], [original_observation]
    )
    applied = apply_terminal_date_v2(
        state=_empty_state(original_ledger),
        ledger=original_ledger,
        observed_on="2026-05-05",
        observations=[original_observation],
        transitioned_at="2026-05-05T23:59:59Z",
    )
    original_bytes = persistence_state_bytes_v2(applied.state)

    revised_manifest_id = "run-v2-" + "4" * 64
    revised_manifest_sha256 = "5" * 64
    rebound_original = _acquisition(
        "2026-05-05",
        "10:00:00",
        "DT-ORIGINAL",
        platform="S2A",
        run_manifest_id=revised_manifest_id,
        run_manifest_sha256=revised_manifest_sha256,
    )
    late_acquisition = _acquisition(
        "2026-05-05",
        "10:10:00",
        "DT-LATE-ARRIVAL",
        platform="S2B",
        run_manifest_id=revised_manifest_id,
        run_manifest_sha256=revised_manifest_sha256,
    )
    rebound_observation = _observation(
        rebound_original, box(-40.50, -7.50, -40.48, -7.48)
    )
    late_observation = _observation(
        late_acquisition, box(-40.50, -7.50, -40.48, -7.48)
    )
    revised_ledger = _terminal_ledger(
        [late_acquisition, rebound_original],
        [late_observation, rebound_observation],
    )

    assert rebound_original.acquisition_id == original_acquisition.acquisition_id
    with pytest.raises(LateArrivalRequiresRebuild):
        apply_terminal_date_v2(
            state=applied.state,
            ledger=revised_ledger,
            observed_on="2026-05-05",
            observations=[late_observation, rebound_observation],
            transitioned_at="2026-05-06T12:00:00Z",
        )

    assert persistence_state_bytes_v2(applied.state) == original_bytes
    assert late_acquisition.acquisition_id not in original_bytes.decode("utf-8")


def test_rebuild_from_empty_is_deterministic_for_all_input_permutations():
    day_one_early = _acquisition("2026-05-06", "09:00:00", "DT-R1")
    day_one_late = _acquisition(
        "2026-05-06", "09:10:00", "DT-R2", platform="S2B"
    )
    day_two = _acquisition("2026-05-07", "09:00:00", "DT-R3")
    day_three_zero = _acquisition("2026-05-08", "09:00:00", "DT-R4")
    acquisitions = [day_two, day_three_zero, day_one_late, day_one_early]
    footprint = box(-40.60, -7.60, -40.58, -7.58)
    observations = [
        _observation(day_one_early, footprint),
        _observation(day_one_late, footprint),
        _observation(day_two, footprint),
    ]
    ledger_a = _terminal_ledger(
        acquisitions,
        observations,
        terminal_order=[day_three_zero, day_one_late, day_two, day_one_early],
    )
    ledger_b = _terminal_ledger(
        list(reversed(acquisitions)),
        list(reversed(observations)),
        terminal_order=[day_one_early, day_two, day_one_late, day_three_zero],
    )

    rebuilt_a = rebuild_persistence_state_v2(
        generation_id=GENERATION_ID,
        ledger=ledger_a,
        observations=[observations[2], observations[0], observations[1]],
        baseline_version=BASELINE_VERSION,
        generated_at=CREATED_AT,
    )
    rebuilt_b = rebuild_persistence_state_v2(
        generation_id=GENERATION_ID,
        ledger=ledger_b,
        observations=list(reversed(observations)),
        baseline_version=BASELINE_VERSION,
        generated_at=CREATED_AT,
    )

    manual = _empty_state(ledger_a)
    observations_by_date: dict[str, list[ObservationV2]] = defaultdict(list)
    for observation in observations:
        observations_by_date[observation.to_dict()["observed_on"]].append(observation)
    for observed_on in ("2026-05-06", "2026-05-07", "2026-05-08"):
        manual = apply_terminal_date_v2(
            state=manual,
            ledger=ledger_a,
            observed_on=observed_on,
            observations=list(reversed(observations_by_date[observed_on])),
            transitioned_at=CREATED_AT,
        ).state

    rebuilt_bytes = persistence_state_bytes_v2(rebuilt_a)
    assert persistence_state_bytes_v2(rebuilt_b) == rebuilt_bytes
    assert persistence_state_bytes_v2(manual) == rebuilt_bytes
    assert [item["observed_on"] for item in rebuilt_a["finalized_dates"]] == [
        "2026-05-06",
        "2026-05-07",
        "2026-05-08",
    ]
    assert len(rebuilt_a["events"]) == 1
    assert rebuilt_a["events"][0]["n_distinct_observation_dates"] == 2
    assert len(rebuilt_a["contributions"]) == 2
    assert rebuilt_a["finalized_dates"][-1]["contribution_keys"] == []


def test_split_and_merge_lineage_has_stable_cardinality_and_order():
    origin_acquisition = _acquisition("2026-05-09", "09:00:00", "DT-L1")
    split_acquisition = _acquisition("2026-05-10", "09:00:00", "DT-L2")
    merge_acquisition = _acquisition("2026-05-11", "09:00:00", "DT-L3")
    origin_observation = _observation(
        origin_acquisition, box(-40.00, -7.00, -39.98, -6.99)
    )
    left_observation = _observation(
        split_acquisition, box(-40.00, -7.00, -39.992, -6.99)
    )
    right_observation = _observation(
        split_acquisition, box(-39.988, -7.00, -39.98, -6.99)
    )
    merge_observation = _observation(
        merge_acquisition, box(-40.00, -7.00, -39.98, -6.99)
    )
    observations = [
        merge_observation,
        right_observation,
        origin_observation,
        left_observation,
    ]
    ledger = _terminal_ledger(
        [merge_acquisition, split_acquisition, origin_acquisition],
        observations,
        terminal_order=[split_acquisition, origin_acquisition, merge_acquisition],
    )

    state = rebuild_persistence_state_v2(
        generation_id=GENERATION_ID,
        ledger=ledger,
        observations=observations,
        baseline_version=BASELINE_VERSION,
        generated_at=CREATED_AT,
    )

    chronological_lineage = sorted(
        state["lineage"],
        key=lambda item: (
            item["effective_timestamp_utc"],
            item["lineage_id"].encode("utf-8"),
        ),
    )
    assert [item["relation"] for item in chronological_lineage] == [
        "split",
        "merge",
    ]
    split, merge = chronological_lineage
    assert len(split["parent_event_ids"]) == 1
    assert len(split["child_event_ids"]) == 2
    assert len(split["trigger_observation_ids"]) == 2
    assert len(merge["parent_event_ids"]) == 2
    assert len(merge["child_event_ids"]) == 1
    assert len(merge["trigger_observation_ids"]) == 1
    assert merge["parent_event_ids"] == split["child_event_ids"]
    assert split["trigger_observation_ids"] == _byte_sorted(
        [left_observation.observation_id, right_observation.observation_id]
    )
    assert merge["trigger_observation_ids"] == [merge_observation.observation_id]

    origin_event_id = origin_event_id_v2(origin_observation.observation_id)
    events = {item["event_id"]: item for item in state["events"]}
    assert split["parent_event_ids"] == [origin_event_id]
    assert events[origin_event_id]["status"] == "superseded"
    assert all(
        events[event_id]["status"] == "superseded"
        for event_id in split["child_event_ids"]
    )
    assert events[merge["child_event_ids"][0]]["status"] == "active"
    assert events[merge["child_event_ids"][0]]["identity_basis"][
        "parent_event_ids"
    ] == split["child_event_ids"]

    assert [item["event_id"] for item in state["events"]] == _byte_sorted(events)
    assert [item["lineage_id"] for item in state["lineage"]] == _byte_sorted(
        item["lineage_id"] for item in state["lineage"]
    )
    assert [
        item["contribution_key"] for item in state["contributions"]
    ] == _byte_sorted(item["contribution_key"] for item in state["contributions"])
    for lineage in state["lineage"]:
        assert lineage["parent_event_ids"] == _byte_sorted(
            lineage["parent_event_ids"]
        )
        assert lineage["child_event_ids"] == _byte_sorted(
            lineage["child_event_ids"]
        )
        assert lineage["trigger_observation_ids"] == _byte_sorted(
            lineage["trigger_observation_ids"]
        )

    preserved = Counter(
        observation_id
        for event in state["events"]
        for observation_id in event["observation_ids"]
    )
    assert preserved == Counter(
        observation.observation_id for observation in observations
    )
    assert len(state["events"]) == 4
    assert len(state["contributions"]) == 4


def test_out_of_order_date_requires_rebuild_and_does_not_mutate_state():
    older_acquisition = _acquisition("2026-05-12", "09:00:00", "DT-OLDER")
    newer_acquisition = _acquisition("2026-05-13", "09:00:00", "DT-NEWER")
    footprint = box(-40.70, -7.70, -40.68, -7.68)
    older_observation = _observation(older_acquisition, footprint)
    newer_observation = _observation(newer_acquisition, footprint)
    ledger = _terminal_ledger(
        [newer_acquisition, older_acquisition],
        [newer_observation, older_observation],
    )
    newer_state = apply_terminal_date_v2(
        state=_empty_state(ledger),
        ledger=ledger,
        observed_on="2026-05-13",
        observations=[newer_observation],
        transitioned_at="2026-05-13T23:59:59Z",
    ).state
    before = persistence_state_bytes_v2(newer_state)

    with pytest.raises(OutOfOrderRequiresRebuild):
        apply_terminal_date_v2(
            state=newer_state,
            ledger=ledger,
            observed_on="2026-05-12",
            observations=[older_observation],
            transitioned_at="2026-05-14T12:00:00Z",
        )

    assert persistence_state_bytes_v2(newer_state) == before
