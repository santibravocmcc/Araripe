"""Package 2A.6D regressions: v2 MapBiomas context, 10.1 export, drought lock.

Covers the closure gates the decision record requires: the checksum-bound
legend fixture, the exact v2 mappings and 0/27/255 policy, the inclusive 50%
pixel-centre subset, the 60% dominant-share aggregator, the fresh Collection
10.1 export contract, the invalidation of the mislabeled crop, and the
regenerated v2 artifacts — every one fail-closed and deterministic.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from src.validation import phase2a5_context_v2 as ctx
from src.validation.phase2a5_context_v2 import (
    COL3_KEY_V2,
    COL10_1_KEY_V2,
    Phase2A5ContextV2Error,
    aggregate_dominant_share_v2,
    align_secondary_nearest,
    calculate_agreement_disagreement_v2,
    classify_mapbiomas_codes_v2,
    generate_context_registry_v2,
    load_context_registry_v2,
    strong_subset_membership_v2,
    summarize_polygon_context_v2,
    verify_legend_fixture,
)
from src.validation.phase2a5_package_v2 import (
    FAMILY_CANDIDATES,
    derive_balanced_blinding,
    signature_candidate_outcomes,
)

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def registry():
    return load_context_registry_v2(
        REPO / "config/phase2a5_context_registry_v2.json", root=REPO
    )


# ─── legend fixture and registry drift ───────────────────────────────────────


def test_legend_fixture_verifies_in_bytes_and_content():
    result = verify_legend_fixture(REPO)
    assert result["bytes"] == 84039
    assert result["sha256"].startswith("77fb06eb")
    # every mapped v2 code is present in the transcribed legend table
    assert 62 in result["mapped_codes_verified_in_legend"]
    assert 27 not in result["mapped_codes_verified_in_legend"]


def test_registry_is_rederived_from_the_decision_record(registry):
    derived = generate_context_registry_v2(REPO)
    assert registry == derived


def test_a_drifted_registry_fails_closed(tmp_path):
    drifted = generate_context_registry_v2(REPO)
    drifted["class_mappings"]["collection3_beta_10m_2024"][
        "natural_vegetation"
    ] = drifted["class_mappings"]["collection3_beta_10m_2024"][
        "natural_vegetation"
    ] + [21]
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(drifted), encoding="utf-8")
    with pytest.raises(Phase2A5ContextV2Error, match="drift"):
        load_context_registry_v2(path, root=REPO)


def test_mapping_codes_match_the_accepted_decision_lists(registry):
    decisions = json.loads(
        (REPO / "config/phase2a_candidate_generation_decisions_v2.json").read_text()
    )
    assert registry["class_mappings"] == decisions["phase2a5"]["class_mappings"]
    col10 = registry["class_mappings"]["collection10_family_30m_2024"]
    # the corrected Collection-10-family anthropic list is the long one
    assert 62 in col10["anthropic_cover"] and 18 in col10["anthropic_cover"]


# ─── classification and the 0/27/255 policy ──────────────────────────────────


def test_v2_special_states_per_collection(registry):
    codes = np.array([0, 3, 15, 27, 33, 200, 255])
    col3 = classify_mapbiomas_codes_v2(codes, COL3_KEY_V2, registry)
    assert list(col3) == [
        "nodata",
        "natural_vegetation",
        "anthropic_cover",
        "not_observed",
        "uncertain_or_mixed",
        "unmapped",
        "unmapped",
    ]
    col10 = classify_mapbiomas_codes_v2(codes, COL10_1_KEY_V2, registry)
    assert list(col10) == [
        "unknown_unclassified",
        "natural_vegetation",
        "anthropic_cover",
        "not_observed",
        "uncertain_or_mixed",
        "unmapped",
        "nodata",
    ]


def test_denominator_excludes_exactly_the_four_states(registry):
    values = np.array([3, 3, 15, 0, 27, 255, 200, 33])
    summary = summarize_polygon_context_v2(values, COL10_1_KEY_V2, registry)
    assert summary["total_pixel_count"] == 8
    assert summary["valid_mapped_pixel_count"] == 4  # 3,3,15,33
    assert summary["excluded_pixel_counts"] == {
        "nodata": 1,
        "unknown_unclassified": 1,
        "not_observed": 1,
        "unmapped": 1,
    }
    assert summary["natural_fraction"] == pytest.approx(0.5)


def test_duplicate_code_across_categories_fails(registry):
    corrupted = copy.deepcopy(dict(registry))
    corrupted["class_mappings"]["collection3_beta_10m_2024"][
        "anthropic_cover"
    ].append(3)
    with pytest.raises(Phase2A5ContextV2Error, match="appears in both"):
        classify_mapbiomas_codes_v2(np.array([3]), COL3_KEY_V2, corrupted)


# ─── the inclusive 50% subset ────────────────────────────────────────────────


def test_subset_threshold_is_inclusive_at_exactly_half(registry):
    outcome = strong_subset_membership_v2(2, 4, registry)
    assert outcome["selected"]["membership"] == "included"
    assert outcome["selected"]["natural_fraction"] == pytest.approx(0.5)
    assert outcome["sensitivity_only"]["membership"] == "excluded"
    assert outcome["sensitivity_only"]["selected"] is False


def test_subset_zero_denominator_is_not_assessed_never_excluded(registry):
    outcome = strong_subset_membership_v2(0, 0, registry)
    assert outcome["selected"]["membership"] == "not_assessed"
    assert outcome["selected"]["raw_detection_retained"] is True


def test_subset_numerator_cannot_exceed_denominator(registry):
    with pytest.raises(Phase2A5ContextV2Error, match="exceeds"):
        strong_subset_membership_v2(5, 4, registry)


# ─── nearest alignment and cross-collection comparison ───────────────────────


def test_nearest_alignment_is_exact_on_a_phase_offset_lattice():
    # secondary 30-unit grid; primary 10-unit grid offset by (2, 1) primary px
    secondary = np.arange(12, dtype=np.int32).reshape(3, 4)
    st = [30.0, 0.0, 0.0, 0.0, -30.0, 90.0]
    pt = [10.0, 0.0, 20.0, 0.0, -10.0, 80.0]
    aligned = align_secondary_nearest(
        primary_transform=pt,
        primary_shape=(6, 6),
        secondary_values=secondary,
        secondary_transform=st,
    )
    # first primary centre: x=25, y=75 -> secondary col 0, row 0
    assert aligned[0, 0] == secondary[0, 0]
    # x=25+50=75 -> col 2; y stays row 0
    assert aligned[0, 5] == secondary[0, 2]
    assert aligned[5, 0] == secondary[2, 0]


def test_nearest_alignment_fails_closed_outside_the_secondary():
    secondary = np.zeros((2, 2), dtype=np.int32)
    with pytest.raises(Phase2A5ContextV2Error, match="outside"):
        align_secondary_nearest(
            primary_transform=[10.0, 0.0, -5.0, 0.0, -10.0, 0.0],
            primary_shape=(2, 2),
            secondary_values=secondary,
            secondary_transform=[30.0, 0.0, 0.0, 0.0, -30.0, 60.0],
        )


def test_agreement_denominator_is_primary_valid_and_mapped(registry):
    primary = np.array([3, 3, 15, 0, 27, 200])       # mapped: 3,3,15
    secondary = np.array([3, 15, 15, 3, 3, 3])       # aligned
    result = calculate_agreement_disagreement_v2(primary, secondary, registry)
    assert result["primary_valid_mapped_pixel_count"] == 3
    assert result["assessed_pixel_count"] == 3
    assert result["agreement_count"] == 2            # 3~3, 15~15; 3 vs 15 differs
    assert result["state"] == "agreement"
    assert result["tie_breaking_permitted"] is False


def test_secondary_excluded_states_become_not_assessed(registry):
    primary = np.array([3, 3, 3, 3])
    secondary = np.array([255, 0, 27, 3])
    result = calculate_agreement_disagreement_v2(primary, secondary, registry)
    assert result["primary_valid_mapped_pixel_count"] == 4
    assert result["assessed_pixel_count"] == 1
    assert result["not_assessed_pixel_count"] == 3


# ─── the 60% dominant-share aggregator and the 0.15 margin alternative ───────


def _labels(fire: int, soil: int, mixed: int, unassessed: int = 0) -> np.ndarray:
    return np.array(
        ["fire_like"] * fire
        + ["exposed_soil_or_clearing_like"] * soil
        + ["mixed_or_uncertain"] * mixed
        + ["not_assessed"] * unassessed
    )


def test_aggregator_emits_top_class_only_at_sixty_percent(registry):
    exact = aggregate_dominant_share_v2(_labels(6, 3, 1), registry)
    assert exact["label"] == "fire_like"          # 0.60 inclusive
    below = aggregate_dominant_share_v2(_labels(5, 4, 1), registry)
    assert below["label"] == "mixed_or_uncertain"  # 0.50 top share


def test_aggregator_zero_assessed_is_not_assessed(registry):
    outcome = aggregate_dominant_share_v2(_labels(0, 0, 0, 7), registry)
    assert outcome["label"] == "not_assessed"
    assert outcome["causal_inference"] is False


def test_aggregator_requires_a_unique_top(registry):
    tie = aggregate_dominant_share_v2(_labels(5, 5, 0), registry)
    assert tie["label"] == "mixed_or_uncertain"


def test_margin_alternative_recomputes_from_the_same_shares():
    observation = {
        "status": "available",
        "aggregate": {
            "label": "mixed_or_uncertain",
            "assessed_pixel_count": 10,
            "shares": {
                "fire_like": 0.55,
                "exposed_soil_or_clearing_like": 0.40,
                "mixed_or_uncertain": 0.05,
            },
        },
    }
    outcomes = signature_candidate_outcomes(observation)
    # 0.55 top share fails the 0.60 rule but passes the 0.15 margin rule
    assert outcomes["dominant-assessed-share-0.60-v1"]["label"] == "mixed_or_uncertain"
    assert outcomes["plurality-assessed-margin-0.15-v1"]["label"] == "fire_like"


# ─── keyed balanced blinding ─────────────────────────────────────────────────


def test_keyed_blinding_is_balanced_and_deterministic():
    ids = [f"blind-{index:02d}" for index in range(60)]
    key = "ab" * 32
    first = derive_balanced_blinding(ids, key)
    second = derive_balanced_blinding(ids, key)
    assert first == second
    for family in FAMILY_CANDIDATES:
        counts = {"candidate_0_as_A": 0, "candidate_1_as_A": 0}
        for case in ids:
            counts[first[case][family]] += 1
        assert counts == {"candidate_0_as_A": 30, "candidate_1_as_A": 30}
    other = derive_balanced_blinding(ids, "cd" * 32)
    assert other != first


def test_keyed_blinding_requires_even_unique_cases():
    with pytest.raises(Exception, match="even"):
        derive_balanced_blinding([f"c{index}" for index in range(59)], "ab" * 32)
    with pytest.raises(Exception, match="repeat"):
        derive_balanced_blinding(["dup", "dup"], "ab" * 32)


# ─── the Collection 10.1 export manifest and the invalidation ────────────────


def test_export_manifest_satisfies_the_locked_contract():
    manifest = json.loads(
        (REPO / "config/collection10_1_export_manifest_v1.json").read_text()
    )
    decisions = json.loads(
        (REPO / "config/phase2a_candidate_generation_decisions_v2.json").read_text()
    )
    contract = decisions["phase2a5"]["collection10_1_required_source"]
    missing = set(contract["required_export_manifest_fields"]) - set(manifest)
    assert not missing
    assert manifest["asset_id"] == contract["gee_asset"]
    assert manifest["selected_band"] == contract["band"]
    assert manifest["task_state"] == contract["required_task_state"]
    header = manifest["output_header"]
    assert header["dtype"] == "uint8"
    assert header["nodata"] == 255
    assert header["crs"] == manifest["source_projection"]["crs"]
    total = sum(manifest["class_histogram"].values())
    assert total == header["width"] * header["height"]
    # the mask is never conflated with class 0
    assert manifest["nodata_pixel_count"] == manifest["class_histogram"].get("255", 0)
    assert manifest["unknown_class0_pixel_count"] == manifest["class_histogram"].get("0", 0)
    assert manifest["masked_value_is_distinct_from_class0"] is True
    assert manifest["existing_national_file_modified"] is False


def test_mislabeled_crop_is_invalidated_but_never_deleted(registry):
    block = registry["mislabeled_collection10_invalidation"]
    assert block["runtime_use_permitted"] is False
    assert block["qualified_review_use_permitted"] is False
    assert block["audit_bytes_deleted"] is False
    path = REPO / block["path"]
    assert path.exists()
    assert path.stat().st_size == block["bytes"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == block["sha256"]


def test_regional_manifest_v2_binds_every_regional_byte():
    manifest = json.loads(
        (REPO / "config/phase2a5_regional_context_manifest_v2.json").read_text()
    )
    for source in manifest["regional_sources"].values():
        path = REPO / source["path"]
        assert path.stat().st_size == source["bytes"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == source["sha256"]
    reconciliation = manifest["grid_reconciliation"]
    assert reconciliation["ratio"] == [3, 3]
    assert reconciliation["centre_on_boundary_possible"] is False
    invalidation = manifest["mislabeled_collection10_invalidation"]
    assert invalidation["audit_bytes_verified"] is True


# ─── drought stays locked at the entrypoint module ───────────────────────────


def test_change_detect_has_no_reachable_drought_branch():
    source = (REPO / "src/detection/change_detect.py").read_text()
    assert "DroughtAdjustmentDisabledError" in source
    assert "DROUGHT_Z_ADJUSTMENT" not in source
    assert "drought-disabled-v1" in source
