"""Integrity checks for the accepted Phase 2A candidate-generation decisions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
DECISIONS = ROOT / "config/phase2a_candidate_generation_decisions_v2.json"
SCHEMA = (
    ROOT
    / "docs/contracts/phase2a/schemas/phase2a-candidate-generation-decisions-v2.schema.json"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_decision_schema_is_meta_valid_and_record_validates():
    schema = _load(SCHEMA)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_load(DECISIONS))


def test_tracked_bindings_are_required_and_local_evidence_is_checked_when_present():
    record = _load(DECISIONS)
    for binding in record["parent_bindings"].values():
        path = ROOT / binding["path"]
        if binding["required_in_clean_clone"]:
            assert path.is_file()
        if path.exists():
            assert path.is_file()
            assert _sha256(path) == binding["sha256"]


def test_decisions_preserve_claim_boundary_and_phase_order():
    record = _load(DECISIONS)
    boundary = record["evidence_boundary"]
    identity = record["identity"]
    gates = record["gates"]
    assert boundary == {
        "qualified_primary_change_labels_present": False,
        "reviewer_usability_result_present": False,
        "scientific_accuracy_result_present": False,
        "technical_method_selection_permitted": True,
        "scientific_accuracy_claim_permitted": False,
        "canonical_public_release_permitted": False,
    }
    assert identity["contract_family"]["required_contracts"] == [
        "acquisition-v2",
        "observation-v2",
        "event-v2",
        "lineage-v2",
        "persistence-contribution-v2",
        "persistence-state-v2",
        "processing-ledger-v2",
    ]
    assert identity["contract_family"]["v1_runtime_serialization_permitted"] is False
    assert identity["observation"]["selected_contract"] == "observation-v2"
    assert identity["event"]["selected_contract"] == "event-v2"
    assert identity["persistence"]["maximum_contributions_per_event_per_utc_date"] == 1
    assert identity["persistence"]["contribution_finalization_condition"] == (
        "all_expected_acquisitions_for_utc_date_are_terminal"
    )
    assert identity["processing_ledger"]["expected_acquisition_set_bound_to_run_manifest"] is True
    assert identity["processing_ledger"]["same_day_multiple_acquisitions_permitted"] is True
    assert identity["processing_ledger"]["chronological_order_key"] == [
        "acquisition_timestamp_utc",
        "acquisition_id",
    ]
    assert gates["candidate_generation_policy_gate_closed"] is True
    assert gates["candidate_generation_implementation_gate_closed"] is False
    assert gates["scientific_validation_gate_closed"] is False
    assert gates["phase2b_green_sequence_authorized"] == [
        "2B.0", "2B.1", "2B.2", "2B.3", "2B.4"
    ]
    assert gates["phase2b_green_only"] is True
    assert gates["ledger_v2_owner"] == "phase2a6_contract_schema_and_backend_producer"
    assert gates["ledger_v2_consumer"] == "phase2b2_publication_integration"
    assert gates["phase2b_exit_requires_phase2a6_ledger_integration"] is True
    assert gates["production_workflow_mutation_authorized"] is False
    assert gates["production_route_or_pointer_mutation_authorized"] is False
    assert gates["phase3_authorized"] is False
    assert gates["phase4_full_replay_authorized"] is False
    assert gates["phase6_canonical_promotion_authorized"] is False


def test_scientific_selections_are_conservative_and_raw_preserving():
    record = _load(DECISIONS)
    p2a4 = record["phase2a4"]
    p2a5 = record["phase2a5"]
    assert p2a4["drought"]["selected_method"] == "drought-disabled-v1"
    assert p2a4["drought"]["activated"] is False
    assert p2a4["cloud_mask"]["selected_method"] == "scl-explicit-allowlist-v2"
    assert p2a4["cloud_mask"]["accepted_scl_classes"] == [4, 5, 6, 7]
    assert p2a4["cloud_mask"]["rejected_scl_classes"] == [0, 1, 2, 3, 8, 9, 10, 11]
    assert p2a4["cloud_mask"]["scl7_policy"]["scientifically_validated"] is False
    assert p2a4["cloud_mask"]["baseline_rebuild_with_identical_mask_required"] is True
    assert p2a4["composition"]["different_datatakes_never_composed"] is True
    assert p2a5["class0_and_nodata_policy"]["may_modify_raw_detection"] is False
    assert p2a5["class0_and_nodata_policy"]["collection10_1_gee_export_30m_2024"]["exported_mask_nodata_value"] == 255
    assert p2a5["class_mappings"]["class33_cross_collection_policy"] == "uncertain_or_mixed_in_both_collections"
    assert p2a5["strong_subset"]["threshold"] == 0.5
    assert p2a5["strong_subset"]["polygon_pixel_rule"] == "detector_grid_pixel_center_within_polygon-v1"
    assert p2a5["strong_subset"]["raw_detection_removal_permitted"] is False
    assert p2a5["contextual_signature"]["public_label_enabled"] is False
    assert p2a5["cross_collection_comparison"]["raw_detection_change_permitted"] is False


def test_direct_download_is_not_mislabeled_as_collection_10_1():
    source = _load(DECISIONS)["phase2a5"]
    direct = source["collection10_direct_download"]
    required = source["collection10_1_required_source"]
    assert direct["corrected_source_id"] == "mapbiomas-col10-30m-brazil-2024-v1"
    assert direct["collection10_1_identity_permitted"] is False
    assert "/collection_10/" in direct["origin_url"]
    assert "/collection10_1/" in required["gee_asset"]
    assert required["band"] == "classification_2024"
    assert required["export_contract"]["masked_pixel_export_value"] == 255
    assert required["required_task_state"] == "COMPLETED"
    assert required["existing_mislabeled_crop_reuse_permitted"] is False


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("phase2a5", "class_mappings", "collection3_beta_10m_2024", "natural_vegetation"), [3]),
        (("phase2a5", "class0_and_nodata_policy", "collection10_1_gee_export_30m_2024", "exported_mask_nodata_value"), 0),
        (("phase2a5", "strong_subset", "polygon_pixel_rule"), "all_touched_true"),
        (("phase2a5", "collection10_1_required_source", "band"), "classification_2023"),
        (("phase2a4", "cloud_mask", "scl7_policy", "scientifically_validated"), True),
        (("phase2a5", "strong_subset", "raw_detection_removal_permitted"), True),
        (("phase2a5", "contextual_signature", "public_label_enabled"), True),
        (("phase2a5", "collection10_direct_download", "collection10_1_identity_permitted"), True),
        (("identity", "observation", "selected_contract"), "observation-v1"),
        (("identity", "persistence", "maximum_contributions_per_event_per_utc_date"), 2),
        (("gates", "phase2b_green_sequence_authorized"), ["2B.0"]),
    ],
)
def test_schema_rejects_mutation_of_locked_policy(path, value):
    schema = _load(SCHEMA)
    record = _load(DECISIONS)
    target = record
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(record)


def test_schema_const_blocks_match_the_accepted_record():
    schema = _load(SCHEMA)
    record = _load(DECISIONS)
    for block in ("evidence_boundary", "identity", "phase2a4", "phase2a5", "gates"):
        assert schema["properties"][block]["const"] == record[block]
