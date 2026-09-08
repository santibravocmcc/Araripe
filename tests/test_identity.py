"""Accepted Phase 1 deterministic identity and canonicalization vectors."""

import json
from pathlib import Path

from shapely.geometry import Polygon

from src.detection.identity import (
    canonical_geometry_sha256,
    child_event_id,
    contribution_key,
    create_acquisition_identity,
    jcs_dumps,
    lineage_id,
    observation_id,
)


ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "docs" / "contracts" / "phase1" / "examples"


def _example(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_identity_helpers_reproduce_accepted_phase1_fixture():
    observation = _example("observation-v1.example.json")
    event = _example("event-v1.example.json")
    acquisition_record = observation["acquisition"]
    acquisition = create_acquisition_identity(
        collection_id=acquisition_record["collection_id"],
        observed_on=acquisition_record["observed_on"],
        scene_ids=reversed(acquisition_record["scene_ids"]),
        monitoring_extent_id=observation["monitoring_extent_id"],
        composite_method_id=acquisition_record["composite_method_id"],
    )
    assert acquisition.acquisition_id == acquisition_record["acquisition_id"]

    _, geometry_hash = canonical_geometry_sha256(observation["geometry"])
    assert geometry_hash == observation["canonical_geometry_sha256"]
    assert (
        observation_id(
            acquisition.acquisition_id,
            geometry_hash,
            observation["algorithm_version"],
            observation["baseline_version"],
        )
        == observation["observation_id"]
    )

    assert (
        child_event_id(
            event["identity_basis"]["kind"],
            reversed(event["identity_basis"]["parent_event_ids"]),
            event["identity_basis"]["trigger_observation_ids"],
        )
        == event["event_id"]
    )
    edge = event["lineage"]["incoming"][0]
    assert (
        lineage_id(
            relation=edge["relation"],
            parent_event_ids=reversed(edge["parent_event_ids"]),
            child_event_ids=edge["child_event_ids"],
            acquisition_id=edge["effective_acquisition_id"],
            observed_on=edge["effective_on"],
            trigger_observation_ids=edge["trigger_observation_ids"],
            algorithm_version=edge["algorithm_version"],
        )
        == edge["lineage_id"]
    )
    assert (
        contribution_key(event["event_id"], acquisition.acquisition_id)
        == observation["persistence_contribution_key"]
    )


def test_geometry_hash_is_invariant_to_ring_start_and_orientation():
    first = Polygon(
        [(-39.9, -7.3), (-39.89, -7.3), (-39.89, -7.29), (-39.9, -7.29)]
    )
    second = Polygon(
        [(-39.89, -7.29), (-39.89, -7.3), (-39.9, -7.3), (-39.9, -7.29)]
    )
    assert canonical_geometry_sha256(first)[1] == canonical_geometry_sha256(second)[1]


def test_jcs_number_notation_matches_rfc8785_thresholds():
    assert jcs_dumps(1e-7) == "1e-7"
    assert jcs_dumps(1e-6) == "0.000001"
    assert jcs_dumps(1e20) == "100000000000000000000"
    assert jcs_dumps(1e21) == "1e+21"
    assert jcs_dumps(-0.0) == "0"
    assert (
        jcs_dumps([333333333.33333329, 1e30, 4.50, 2e-3, 1e-27])
        == "[333333333.3333333,1e+30,4.5,0.002,1e-27]"
    )
