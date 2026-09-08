"""Focused Package 2A.6B tests for ``scl-explicit-allowlist-v2``."""

import json
from pathlib import Path

import numpy as np
import pytest

from src.processing.scl_mask_v2 import (
    CLOUD_SHADOW_DILATION_M,
    DARK_NIR_PROXIMITY_MASK,
    PB04_BOUNDARY,
    PROCESSING_BASELINE_FIELD_PRIORITY,
    PROCESSING_BASELINE_NORMALIZATION_RULE,
    REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
    REVIEWED_PROCESSING_BASELINES,
    SCL_ACCEPTED_CLASSES,
    SCL_KNOWN_CLASSES,
    SCL_MASK_METHOD_ID,
    SCL_REJECTED_CLASSES,
    MissingProcessingBaselineError,
    MissingSclError,
    UnexpectedProcessingBaselineError,
    UnexpectedSclValueError,
    UnreviewedProcessingBaselineError,
    compute_scene_scl_mask,
    enumerate_observed_baselines,
    normalize_processing_baseline_value,
    read_processing_baseline,
    require_datatake_baseline_consistency,
    reviewed_baseline_registry_dict,
)


ROOT = Path(__file__).resolve().parent.parent
DECISIONS = json.loads(
    (ROOT / "config" / "phase2a_candidate_generation_decisions_v2.json")
    .read_text(encoding="utf-8")
)
STAC_PROPS = {"s2:processing_baseline": "05.12"}


def _scl(rows, dtype=np.uint8):
    return np.asarray(rows, dtype=dtype)


class TestDecisionRecordBinding:
    def test_method_and_class_lists_match_the_accepted_decision_record(self):
        decided = DECISIONS["phase2a4"]["cloud_mask"]
        assert decided["selected_method"] == SCL_MASK_METHOD_ID
        assert decided["accepted_scl_classes"] == list(SCL_ACCEPTED_CLASSES)
        assert decided["rejected_scl_classes"] == list(SCL_REJECTED_CLASSES)
        assert decided["dark_nir_proximity_mask"] is DARK_NIR_PROXIMITY_MASK
        assert decided["cloud_shadow_dilation_m"] == CLOUD_SHADOW_DILATION_M
        compatibility = decided["processing_baseline_compatibility"]
        assert compatibility["metadata_fields_in_priority_order"] == list(
            PROCESSING_BASELINE_FIELD_PRIORITY
        )
        assert (
            compatibility["normalized_value_rule"]
            == PROCESSING_BASELINE_NORMALIZATION_RULE
        )
        assert compatibility["class2_rejected_under_pre_and_post_pb04_semantics"]

    def test_allowlist_partition_is_complete_and_disjoint(self):
        accepted = set(SCL_ACCEPTED_CLASSES)
        rejected = set(SCL_REJECTED_CLASSES)
        assert accepted | rejected == set(SCL_KNOWN_CLASSES) == set(range(12))
        assert not accepted & rejected


class TestAllowlist:
    @pytest.mark.parametrize("scl_class", sorted(SCL_KNOWN_CLASSES))
    def test_every_scl_class_has_the_decided_outcome(self, scl_class):
        mask = compute_scene_scl_mask(
            _scl([[scl_class]]), properties=STAC_PROPS, scene_id="scene-1"
        )
        expected = scl_class in SCL_ACCEPTED_CLASSES
        assert bool(mask.accepted_mask[0, 0]) is expected
        assert mask.class_pixel_counts[scl_class] == 1
        assert mask.total_pixel_count == 1
        assert mask.accepted_pixel_count == (1 if expected else 0)

    def test_counts_cover_all_classes_and_mask_is_readonly(self):
        grid = _scl([[0, 4, 5, 6], [7, 8, 9, 2]])
        mask = compute_scene_scl_mask(grid, properties=STAC_PROPS)
        assert set(mask.class_pixel_counts) == set(SCL_KNOWN_CLASSES)
        assert sum(mask.class_pixel_counts.values()) == grid.size
        assert mask.accepted_pixel_count == 4
        with pytest.raises(ValueError):
            mask.accepted_mask[0, 0] = True

    def test_class2_rejected_under_pre_and_post_pb04_semantics(self):
        grid = _scl([[2, 4]])
        reviewed = ("03.01", "05.12")
        pre = compute_scene_scl_mask(
            grid,
            properties={"s2:processing_baseline": "03.01"},
            reviewed_baselines=reviewed,
        )
        post = compute_scene_scl_mask(
            grid,
            properties={"s2:processing_baseline": "05.12"},
            reviewed_baselines=reviewed,
        )
        assert pre.processing_baseline.class2_semantics == "dark-area-pixels"
        assert post.processing_baseline.class2_semantics == "cast-shadows"
        for mask in (pre, post):
            assert not mask.accepted_mask[0, 0]
            assert mask.accepted_mask[0, 1]
            assert mask.qa_dict()["processing_baseline"][
                "scl_class2_accepted"
            ] is False

    def test_no_proximity_mask_and_no_dilation_in_policy(self):
        qa = compute_scene_scl_mask(
            _scl([[4]]), properties=STAC_PROPS
        ).qa_dict()
        assert qa["dark_nir_proximity_mask"] is False
        assert qa["cloud_shadow_dilation_m"] == 0


class TestFailClosedSclInputs:
    def test_missing_scl_fails_closed(self):
        with pytest.raises(MissingSclError) as excinfo:
            compute_scene_scl_mask(None, properties=STAC_PROPS, scene_id="s")
        assert excinfo.value.reason_code == "scl-missing"

    @pytest.mark.parametrize("value", [12, 200])
    def test_unexpected_high_scl_value_fails_closed(self, value):
        with pytest.raises(UnexpectedSclValueError) as excinfo:
            compute_scene_scl_mask(
                _scl([[4, value]], dtype=np.uint8), properties=STAC_PROPS
            )
        assert excinfo.value.reason_code == "scl-unexpected-value"

    def test_negative_scl_value_fails_closed(self):
        with pytest.raises(UnexpectedSclValueError):
            compute_scene_scl_mask(
                _scl([[4, -1]], dtype=np.int16), properties=STAC_PROPS
            )

    def test_masked_array_scl_fails_closed(self):
        masked = np.ma.masked_array(
            [[8, 4]], mask=[[False, True]], dtype=np.uint8
        )
        with pytest.raises(UnexpectedSclValueError, match="masked array"):
            compute_scene_scl_mask(masked, properties=STAC_PROPS)

    def test_float_scl_fails_closed(self):
        with pytest.raises(UnexpectedSclValueError):
            compute_scene_scl_mask(
                np.asarray([[4.0, 5.0]]), properties=STAC_PROPS
            )

    def test_non_2d_and_empty_scl_fail_closed(self):
        with pytest.raises(UnexpectedSclValueError):
            compute_scene_scl_mask(
                np.asarray([4, 5], dtype=np.uint8), properties=STAC_PROPS
            )
        with pytest.raises(UnexpectedSclValueError):
            compute_scene_scl_mask(
                np.zeros((0, 3), dtype=np.uint8), properties=STAC_PROPS
            )


class TestProcessingBaseline:
    def test_stac_field_has_priority_over_gee_field(self):
        baseline = read_processing_baseline(
            {"s2:processing_baseline": "05.11", "PROCESSING_BASELINE": "05.12"}
        )
        assert baseline.source_field == "s2:processing_baseline"
        assert baseline.normalized_value == "05.11"

    def test_gee_field_used_when_stac_field_absent(self):
        baseline = read_processing_baseline({"PROCESSING_BASELINE": "05.12"})
        assert baseline.source_field == "PROCESSING_BASELINE"
        assert baseline.normalized_value == "05.12"

    def test_missing_baseline_fails_closed(self):
        with pytest.raises(MissingProcessingBaselineError) as excinfo:
            read_processing_baseline({})
        assert excinfo.value.reason_code == "processing-baseline-missing"
        with pytest.raises(MissingProcessingBaselineError):
            read_processing_baseline(None)

    def test_null_priority_field_fails_closed_without_fallback(self):
        with pytest.raises(MissingProcessingBaselineError):
            read_processing_baseline(
                {
                    "s2:processing_baseline": None,
                    "PROCESSING_BASELINE": "05.12",
                }
            )

    def test_invalid_priority_field_fails_closed_without_fallback(self):
        with pytest.raises(UnexpectedProcessingBaselineError):
            read_processing_baseline(
                {
                    "s2:processing_baseline": "N05.12",
                    "PROCESSING_BASELINE": "05.12",
                }
            )

    def test_normalization_pads_major_and_preserves_fraction_verbatim(self):
        assert (
            normalize_processing_baseline_value("5.11", source_field="t")
            == "05.11"
        )
        assert (
            normalize_processing_baseline_value("05.10", source_field="t")
            == "05.10"
        )

    @pytest.mark.parametrize(
        "value",
        ["05.1", "05.110", "0511", " 05.12", "05.12 ", "5,12", 5.12, 5, True],
    )
    def test_non_provider_decimal_forms_fail_closed(self, value):
        with pytest.raises(UnexpectedProcessingBaselineError):
            normalize_processing_baseline_value(value, source_field="t")

    def test_unreviewed_baseline_fails_closed_and_reports_value(self):
        with pytest.raises(UnreviewedProcessingBaselineError) as excinfo:
            compute_scene_scl_mask(
                _scl([[4]]),
                properties={"s2:processing_baseline": "05.10"},
                scene_id="scene-x",
            )
        assert excinfo.value.reason_code == "processing-baseline-unreviewed"
        assert excinfo.value.observed_baseline == "05.10"

    def test_reviewed_registry_extension_is_explicit(self):
        mask = compute_scene_scl_mask(
            _scl([[4]]),
            properties={"s2:processing_baseline": "05.10"},
            reviewed_baselines=("05.10",),
        )
        assert mask.processing_baseline.normalized_value == "05.10"

    def test_registry_dict_is_normalized_and_fail_closed_policy(self):
        registry = reviewed_baseline_registry_dict()
        assert registry["registry_id"] == REVIEWED_PROCESSING_BASELINE_REGISTRY_ID
        assert registry["reviewed_values"] == sorted(
            REVIEWED_PROCESSING_BASELINES
        )
        assert registry["unreviewed_value_policy"] == "unavailable_fail_closed"
        with pytest.raises(ValueError):
            reviewed_baseline_registry_dict(("5.12",))

    def test_datatake_suffix_must_agree_with_baseline(self):
        baseline = read_processing_baseline(STAC_PROPS)
        require_datatake_baseline_consistency(
            "GS2B_20260716T130249_048884_N05.12", baseline
        )
        with pytest.raises(UnexpectedProcessingBaselineError):
            require_datatake_baseline_consistency(
                "GS2B_20260716T130249_048884_N05.11", baseline
            )
        with pytest.raises(UnexpectedProcessingBaselineError):
            require_datatake_baseline_consistency("GS2B_malformed", baseline)
        # Non-provider identifiers carry no suffix and are not cross-checked.
        require_datatake_baseline_consistency("dt-fixture-1", baseline)

    def test_pb04_boundary_token(self):
        assert PB04_BOUNDARY == "04.00"


class TestScl7Fraction:
    def test_fraction_of_accepted_pixels(self):
        mask = compute_scene_scl_mask(
            _scl([[4, 5, 6, 7], [8, 9, 0, 7]]), properties=STAC_PROPS
        )
        assert mask.scl7_pixel_count == 2
        assert mask.accepted_pixel_count == 5
        assert mask.scl7_fraction_of_accepted == pytest.approx(2 / 5)

    def test_fraction_is_null_when_nothing_is_accepted(self):
        mask = compute_scene_scl_mask(
            _scl([[8, 9], [3, 0]]), properties=STAC_PROPS
        )
        assert mask.accepted_pixel_count == 0
        assert mask.scl7_fraction_of_accepted is None

    def test_qa_records_no_scientific_validation_claim(self):
        qa = compute_scene_scl_mask(
            _scl([[7]]), properties=STAC_PROPS
        ).qa_dict()
        assert qa["scl7"]["candidate_generation_treatment"] == (
            "provisionally_clear"
        )
        assert qa["scl7"]["scientifically_validated"] is False
        assert qa["scl7"]["public_quality_claim_permitted"] is False

    def test_enumerate_observed_baselines_is_sorted_unique(self):
        masks = [
            compute_scene_scl_mask(
                _scl([[4]]),
                properties={"s2:processing_baseline": value},
                reviewed_baselines=("05.11", "05.12"),
            )
            for value in ("05.12", "05.11", "05.12")
        ]
        assert enumerate_observed_baselines(masks) == ("05.11", "05.12")
