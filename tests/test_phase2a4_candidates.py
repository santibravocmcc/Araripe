"""Deterministic, audit-only Phase 2A.4 candidate algorithm tests."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from src.detection.identity import canonical_sha256
from src.validation.phase2a4 import (
    CompositionCandidateConfig,
    CompositionScene,
    DroughtCandidateConfig,
    MASK_OUTSIDE_COMPARISON_CODE,
    MASK_REASON_CODES,
    MaskCandidateConfig,
    apply_mask_policy,
    canonical_array_record,
    compose_coverage_ranked_first_valid,
    compose_min_cloudprob_sclrank_sceneid,
    compute_season_matched_spi3,
)


def _drought_config(**overrides):
    values = {
        "candidate_id": "chirps-v2-spi3-season-matched-1981-2025-v1",
        "reference_start_year": 1981,
        "reference_end_year": 2025,
        "minimum_complete_reference_windows": 40,
        "minimum_positive_reference_windows": 2,
        "normal_probability_clip": (0.001, 0.999),
        "drought_threshold": -1.0,
        "z_threshold_adjustment": 0.5,
    }
    values.update(overrides)
    return DroughtCandidateConfig(**values)


def test_registry_fixes_both_drought_reference_minima():
    registry = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "config/phase2a4_candidates_v1.json"
        ).read_text(encoding="utf-8")
    )
    distribution = registry["families"]["drought_adjustment"]["candidates"][1][
        "reference_distribution"
    ]
    assert distribution["minimum_complete_windows"] == 40
    assert distribution["minimum_positive_windows"] == 2


def test_registry_fixes_shared_reflectance_normalization_policy():
    registry = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "config/phase2a4_candidates_v1.json"
        ).read_text(encoding="utf-8")
    )
    assert registry["fixed_bindings"]["imagery_source"][
        "reflectance_normalization"
    ] == {
        "policy_version": (
            "sentinel2-l2a-stac-scale-offset-zero-fill-nonnegative-v1"
        ),
        "scale_offset_source": "raster:bands[0].scale_and_offset_required",
        "raw_zero_fill": "invalid_before_resampling_and_scaling",
        "negative_scaled_reflectance": "clip_to_zero",
        "output_dtype": "float32",
    }
    provenance = registry["fixed_bindings"]["imagery_source"][
        "asset_provenance"
    ]
    assert provenance["provider_asset_href_required"] is True
    assert provenance["transport_href_resolution_policy"] == (
        "earth-search-provider-https-or-fixed-public-s3-bucket-to-https-v1"
    )


def _seasonal_monthly(*, omit=(), target=(2026, 6, 25.0)):
    """Forty-five April-June windows with deterministic positive variation."""
    omitted = set(omit)
    values = {}
    for year in range(1981, 2026):
        annual_total = 30.0 + float((year - 1981) ** 2) / 4.0
        for month, fraction in ((4, 0.2), (5, 0.3), (6, 0.5)):
            if (year, month) not in omitted:
                values[(year, month)] = annual_total * fraction
        # Distractor months must not enter a June-ending seasonal fit.
        values[(year, 1)] = 50_000.0 + year
        values[(year, 2)] = 60_000.0 + year
        values[(year, 3)] = 70_000.0 + year
    target_year, target_month, target_total = target
    for month, fraction in ((4, 0.2), (5, 0.3), (6, 0.5)):
        values[(target_year, month)] = target_total * fraction
    return values


def test_drought_uses_registry_reference_previous_month_and_same_season_only():
    result = compute_season_matched_spi3(
        "2026-07-31", _seasonal_monthly(), config=_drought_config()
    )

    assert result["status"] == "available"
    assert result["target_ending_month"] == "2026-06"
    assert result["target_window_months"] == ["2026-04", "2026-05", "2026-06"]
    assert result["reference_ending_month"] == 6
    assert result["reference_years_considered"] == list(range(1981, 2026))
    assert result["reference_complete_count"] == 45
    assert result["required_complete_reference_count"] == 40
    assert result["target_precipitation_3month_mm"] == pytest.approx(25.0)
    assert result["spi_3month"] < 0
    assert result["selected_or_activated"] is False
    assert result["output_sha256"] == canonical_sha256(
        {key: value for key, value in result.items() if key != "output_sha256"}
    )


def test_drought_minimum_is_exactly_40_not_percentage_rounded_to_41():
    omitted = [(year, 5) for year in range(1981, 1986)]
    result = compute_season_matched_spi3(
        "2026-07-01", _seasonal_monthly(omit=omitted), config=_drought_config()
    )
    assert result["status"] == "available"
    assert result["reference_complete_count"] == 40
    assert result["required_complete_reference_count"] == 40


def test_drought_invalid_reference_window_is_retained_and_excluded():
    monthly = _seasonal_monthly()
    monthly[(1987, 5)] = -1.0

    result = compute_season_matched_spi3(
        "2026-07-01", monthly, config=_drought_config()
    )

    assert result["status"] == "available"
    assert result["reference_complete_count"] == 44
    assert result["reference_years_incomplete"] == [
        {
            "ending_year": 1987,
            "missing_months": [],
            "invalid_months": ["1987-05"],
        }
    ]


def test_drought_fit_never_uses_months_before_fixed_reference_start():
    monthly = {}
    for ending_year in range(1981, 2026):
        total = float(ending_year - 1970) ** 1.5
        for year, month, fraction in (
            (ending_year - 1, 11, 0.2),
            (ending_year - 1, 12, 0.3),
            (ending_year, 1, 0.5),
        ):
            monthly[(year, month)] = total * fraction
    monthly[(2025, 11)] = 2.0
    monthly[(2025, 12)] = 3.0
    monthly[(2026, 1)] = 5.0

    result = compute_season_matched_spi3(
        "2026-02-15", monthly, config=_drought_config()
    )
    assert result["status"] == "available"
    assert result["reference_complete_count"] == 44
    assert result["reference_years_incomplete"][0] == {
        "ending_year": 1981,
        "missing_months": ["1980-11", "1980-12"],
        "invalid_months": [],
    }


def test_drought_is_per_acquisition_date_not_wall_clock():
    monthly = _seasonal_monthly()
    monthly[(2026, 3)] = 15.0
    may_target = compute_season_matched_spi3(
        "2026-06-15", monthly, config=_drought_config()
    )
    june_target = compute_season_matched_spi3(
        "2026-07-15", monthly, config=_drought_config()
    )
    assert may_target["status"] == "available"
    assert may_target["target_ending_month"] == "2026-05"
    assert june_target["target_ending_month"] == "2026-06"
    assert may_target["input_sha256"] != june_target["input_sha256"]
    assert may_target["spi_3month"] != june_target["spi_3month"]


def test_drought_missing_target_is_explicitly_unavailable_never_zero():
    monthly = _seasonal_monthly()
    monthly.pop((2026, 5))
    result = compute_season_matched_spi3(
        "2026-07-01", monthly, config=_drought_config()
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "missing_target_precipitation"
    assert result["target_missing_months"] == ["2026-05"]
    assert result["spi_3month"] is None
    assert result["is_drought"] is None
    assert result["drought_status"] == "unavailable"


def test_drought_39_complete_windows_has_no_statistical_fallback():
    omitted = [(year, 5) for year in range(1981, 1987)]
    result = compute_season_matched_spi3(
        "2026-07-01", _seasonal_monthly(omit=omitted), config=_drought_config()
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "insufficient_complete_reference_windows"
    assert result["reference_complete_count"] == 39
    assert result["required_complete_reference_count"] == 40
    assert result["spi_3month"] is None


def test_drought_degenerate_gamma_is_unavailable_not_zscore():
    monthly = {}
    for year in range(1981, 2026):
        monthly[(year, 4)] = 10.0
        monthly[(year, 5)] = 10.0
        monthly[(year, 6)] = 10.0
    monthly.update({(2026, 4): 1.0, (2026, 5): 1.0, (2026, 6): 1.0})
    result = compute_season_matched_spi3(
        "2026-07-01", monthly, config=_drought_config()
    )
    assert result["status"] == "unavailable"
    assert result["unavailable_reason"] == "degenerate_positive_reference_distribution"
    assert result["spi_3month"] is None


def test_drought_mapping_order_and_key_form_do_not_change_digests():
    first = _seasonal_monthly()
    second = {
        f"{year:04d}-{month:02d}": value
        for (year, month), value in reversed(list(first.items()))
    }
    a = compute_season_matched_spi3("2026-07-31", first, config=_drought_config())
    b = compute_season_matched_spi3("2026-07-31", second, config=_drought_config())
    assert a == b


def test_mixed_zero_gamma_is_finite_and_recorded():
    monthly = _seasonal_monthly()
    for year in range(1981, 1986):
        monthly[(year, 4)] = 0.0
        monthly[(year, 5)] = 0.0
        monthly[(year, 6)] = 0.0
    monthly[(2026, 4)] = monthly[(2026, 5)] = monthly[(2026, 6)] = 0.0
    result = compute_season_matched_spi3(
        "2026-07-01", monthly, config=_drought_config()
    )
    assert result["status"] == "available"
    assert result["zero_probability"] == pytest.approx(5 / 45)
    assert math.isfinite(result["spi_3month"])
    assert result["mixed_cdf"] == pytest.approx(5 / 45)


def _scl_only_config(**overrides):
    values = {
        "candidate_id": "scl-explicit-clear-shadow-v1",
        "scl_clear_classes": (2, 4, 5, 6, 7, 11),
        "scl_shadow_classes": (3,),
        "scl_invalid_classes": (0, 1),
        "scl_cloud_classes": (8, 9, 10),
        "shadow_mode": "scl_class_only",
        "pixel_size_m": 20,
        "dilation_m": 0,
    }
    values.update(overrides)
    return MaskCandidateConfig(**values)


def _extended_mask_config(**overrides):
    values = {
        "candidate_id": "scl-cloudprob-darkshadow-dilate-v1",
        "scl_clear_classes": (4, 5, 6, 7),
        "scl_shadow_classes": (3,),
        "scl_invalid_classes": (0, 1),
        "scl_cloud_classes": (8, 9, 10, 11),
        "cloud_probability_max_percent": 40,
        "cloud_probability_uint8_required": True,
        "shadow_mode": "scl_or_projected_dark_nir",
        "dark_nir_reflectance_max": 0.15,
        "within_cloud_distance_m": 1000,
        "pixel_size_m": 20,
        "dilation_m": 60,
    }
    values.update(overrides)
    return MaskCandidateConfig(**values)


def test_scl_policy_has_disjoint_reasons_and_coverage_accounting():
    scl = np.array([[4, 9, 0], [3, 4, 6]])
    source = np.array([[True, True, True], [True, False, True]])
    result = apply_mask_policy(scl, config=_scl_only_config(), source_valid_mask=source)

    expected_reasons = np.array(
        [
            [0, MASK_REASON_CODES["cloud_rejected"], MASK_REASON_CODES["scl_rejected"]],
            [
                MASK_REASON_CODES["dark_shadow_rejected"],
                MASK_REASON_CODES["source_invalid"],
                0,
            ],
        ],
        dtype=np.uint8,
    )
    np.testing.assert_array_equal(result.reason_map, expected_reasons)
    np.testing.assert_array_equal(
        result.valid_mask, np.array([[True, False, False], [False, False, True]])
    )
    assert result.record["exclusive_reason_counts"] == {
        "valid": 2,
        "source_invalid": 1,
        "scl_rejected": 1,
        "cloud_rejected": 1,
        "dark_shadow_rejected": 1,
    }
    assert result.record["valid_coverage_fraction"] == pytest.approx(2 / 6)
    assert sum(result.record["exclusive_reason_counts"].values()) == 6


def test_mask_comparison_mask_controls_denominator_counts_and_output():
    scl = np.full((2, 2), 4, dtype=np.uint8)
    comparison = np.array([[True, False], [False, True]])
    result = apply_mask_policy(
        scl, config=_scl_only_config(), comparison_mask=comparison
    )

    np.testing.assert_array_equal(result.valid_mask, comparison)
    np.testing.assert_array_equal(
        result.reason_map,
        np.array(
            [
                [MASK_REASON_CODES["valid"], MASK_OUTSIDE_COMPARISON_CODE],
                [MASK_OUTSIDE_COMPARISON_CODE, MASK_REASON_CODES["valid"]],
            ],
            dtype=np.uint8,
        ),
    )
    assert result.record["array_pixel_count"] == 4
    assert result.record["total_pixel_count"] == 2
    assert result.record["outside_comparison_pixel_count"] == 2
    assert result.record["valid_pixel_count"] == 2
    assert result.record["exclusive_reason_counts"]["valid"] == 2
    assert sum(result.record["exclusive_reason_counts"].values()) == 2

    full = apply_mask_policy(scl, config=_scl_only_config())
    assert result.record["input_sha256"] != full.record["input_sha256"]


@pytest.mark.parametrize(
    ("comparison", "error", "match"),
    [
        (np.ones((1, 2), dtype=bool), ValueError, "shape"),
        (np.ones((2, 2), dtype=np.uint8), TypeError, "boolean dtype"),
        (np.zeros((2, 2), dtype=bool), ValueError, "at least one true"),
    ],
)
def test_mask_comparison_mask_is_strict(comparison, error, match):
    with pytest.raises(error, match=match):
        apply_mask_policy(
            np.full((2, 2), 4),
            config=_scl_only_config(),
            comparison_mask=comparison,
        )


def test_mask_missing_required_auxiliaries_is_explicitly_unavailable():
    scl = np.full((2, 2), 4, dtype=np.uint8)
    missing_both = apply_mask_policy(scl, config=_extended_mask_config())
    assert missing_both.record["status"] == "unavailable"
    assert missing_both.record["missing_inputs"] == [
        "cloud_probability",
        "dark_nir_reflectance",
    ]
    assert missing_both.valid_mask is None
    assert missing_both.record["valid_coverage_fraction"] is None

    missing_nir = apply_mask_policy(
        scl,
        config=_extended_mask_config(),
        cloud_probability=np.zeros((2, 2), dtype=np.uint8),
    )
    assert missing_nir.record["status"] == "unavailable"
    assert missing_nir.record["missing_inputs"] == ["dark_nir_reflectance"]


def test_cloud_probability_threshold_is_inclusive():
    config = _scl_only_config(
        candidate_id="cloud-threshold-boundary-v1",
        scl_clear_classes=(4,),
        scl_shadow_classes=(),
        scl_invalid_classes=(),
        scl_cloud_classes=(),
        cloud_probability_max_percent=40,
        cloud_probability_uint8_required=True,
    )
    result = apply_mask_policy(
        np.array([[4, 4]]),
        config=config,
        cloud_probability=np.array([[40, 41]], dtype=np.uint8),
    )
    np.testing.assert_array_equal(result.valid_mask, [[True, False]])


def test_dark_nir_threshold_and_1000_m_distance_are_inclusive():
    config = _extended_mask_config(dilation_m=0)
    scl = np.full((1, 52), 4, dtype=np.uint8)
    cloud = np.zeros((1, 52), dtype=np.uint8)
    cloud[0, 0] = 41
    nir = np.full((1, 52), 0.2)
    nir[0, 50:52] = 0.15
    result = apply_mask_policy(
        scl, config=config, cloud_probability=cloud, dark_nir_reflectance=nir
    )
    assert result.dark_shadow_mask[0, 50]
    assert not result.dark_shadow_mask[0, 51]
    assert not result.valid_mask[0, 50]
    assert result.valid_mask[0, 51]


def test_projected_dark_nir_and_scl_class_three_are_unioned():
    config = _extended_mask_config(within_cloud_distance_m=40, dilation_m=0)
    scl = np.array([[4, 4, 4, 4, 3]], dtype=np.uint8)
    cloud = np.array([[41, 0, 0, 0, 0]], dtype=np.uint8)
    nir = np.array([[0.2, 0.1, 0.1, 0.1, 0.2]])
    result = apply_mask_policy(
        scl, config=config, cloud_probability=cloud, dark_nir_reflectance=nir
    )
    np.testing.assert_array_equal(
        result.dark_shadow_mask, [[False, True, True, False, True]]
    )
    np.testing.assert_array_equal(
        result.valid_mask, [[False, False, False, True, False]]
    )


def test_sixty_metre_dilation_uses_euclidean_distance_on_20_m_grid():
    config = _extended_mask_config()
    scl = np.full((9, 9), 4, dtype=np.uint8)
    cloud = np.zeros((9, 9), dtype=np.uint8)
    cloud[4, 4] = 41
    nir = np.full((9, 9), 0.2)
    result = apply_mask_policy(
        scl, config=config, cloud_probability=cloud, dark_nir_reflectance=nir
    )
    assert np.count_nonzero(result.cloud_mask) == 29
    assert result.cloud_mask[4, 7]
    assert result.cloud_mask[6, 6]
    assert not result.cloud_mask[5, 7]
    np.testing.assert_array_equal(result.rejection_mask, result.cloud_mask)


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        ({"cloud_probability": np.array([[np.nan]])}, ValueError, "finite"),
        ({"cloud_probability": np.array([[101.0]])}, ValueError, r"\[0, 100\]"),
        ({"cloud_probability": np.ones((2, 1))}, ValueError, "shape"),
        ({"dark_nir_reflectance": np.array([[np.nan]])}, ValueError, "finite"),
    ],
)
def test_mask_policy_strict_numeric_validation(kwargs, error, match):
    config = _scl_only_config(
        candidate_id="strict-mask-input-v1",
        scl_clear_classes=(4,),
        scl_shadow_classes=(),
        scl_invalid_classes=(),
        scl_cloud_classes=(),
        cloud_probability_max_percent=40,
    )
    with pytest.raises(error, match=match):
        apply_mask_policy(np.array([[4]]), config=config, **kwargs)


def test_dark_nir_nodata_is_allowed_only_outside_source_validity():
    result = apply_mask_policy(
        np.array([[4, 4]], dtype=np.uint8),
        config=_extended_mask_config(dilation_m=0),
        cloud_probability=np.array([[0, 0]], dtype=np.uint8),
        dark_nir_reflectance=np.array([[0.2, np.nan]]),
        source_valid_mask=np.array([[True, False]], dtype=bool),
    )
    assert result.record["status"] == "available"
    np.testing.assert_array_equal(result.valid_mask, [[True, False]])
    assert result.record["exclusive_reason_counts"]["source_invalid"] == 1

    with pytest.raises(ValueError, match="finite wherever source_valid_mask is true"):
        apply_mask_policy(
            np.array([[4]], dtype=np.uint8),
            config=_extended_mask_config(dilation_m=0),
            cloud_probability=np.array([[0]], dtype=np.uint8),
            dark_nir_reflectance=np.array([[np.nan]]),
            source_valid_mask=np.array([[True]], dtype=bool),
        )


def test_registry_cloud_policy_requires_uint8_probability():
    with pytest.raises(TypeError, match="uint8"):
        apply_mask_policy(
            np.array([[4]]),
            config=_extended_mask_config(),
            cloud_probability=np.array([[10.0]]),
            dark_nir_reflectance=np.array([[0.2]]),
        )


def test_mask_rejects_noninteger_scl_and_nonboolean_source_mask():
    with pytest.raises(ValueError, match="integer class"):
        apply_mask_policy(np.array([[4.5]]), config=_scl_only_config())
    with pytest.raises(TypeError, match="boolean dtype"):
        apply_mask_policy(
            np.array([[4]]),
            config=_scl_only_config(),
            source_valid_mask=np.array([[1]]),
        )


def test_mask_digests_are_stable_across_layout_and_numeric_dtype():
    config = _scl_only_config(
        candidate_id="stable-mask-digest-v1",
        scl_clear_classes=(4, 5),
        scl_shadow_classes=(),
        scl_invalid_classes=(),
        scl_cloud_classes=(),
        cloud_probability_max_percent=50,
    )
    scl = np.array([[4, 9], [5, 4]], dtype=np.int16)
    cloud = np.array([[10, 90], [20, 30]], dtype=np.float32)
    first = apply_mask_policy(scl, config=config, cloud_probability=cloud)
    second = apply_mask_policy(
        np.asfortranarray(scl.astype(np.float64)),
        config=config,
        cloud_probability=np.asfortranarray(cloud.astype(np.float64)),
    )
    assert first.record == second.record


def _scene(
    scene_id,
    values,
    valid,
    *,
    cloud=None,
    scl=None,
    metadata_digit=None,
    cloud_dtype=np.uint8,
):
    return CompositionScene(
        scene_id=scene_id,
        values=np.asarray(values, dtype=float),
        valid_mask=np.asarray(valid, dtype=bool),
        source_metadata_sha256=(
            metadata_digit * 64
            if metadata_digit
            else canonical_sha256({"scene_id": scene_id})
        ),
        scl=(None if scl is None else np.asarray(scl, dtype=np.int16)),
        cloud_probability=(
            None if cloud is None else np.asarray(cloud, dtype=cloud_dtype)
        ),
    )


def _pixel_config(**overrides):
    values = {
        "candidate_id": "min-cloudprob-sclrank-sceneid-v1",
        "method": "min_cloudprob_sclrank_sceneid",
        "scl_rank_order": (2, 4, 5, 6, 7, 11),
    }
    values.update(overrides)
    return CompositionCandidateConfig(**values)


def test_coverage_ranked_first_valid_is_input_order_invariant():
    config = CompositionCandidateConfig(
        candidate_id="coverage-ranked-first-valid-v1",
        method="coverage_ranked_first_valid",
    )
    a = _scene(
        "S2/A",
        [[1, 1], [1, 1]],
        [[True, True], [False, False]],
        metadata_digit="a",
    )
    b = _scene(
        "S2/B",
        [[2, 2], [2, 2]],
        [[True, False], [True, True]],
        metadata_digit="b",
    )
    first = compose_coverage_ranked_first_valid([a, b], config=config)
    second = compose_coverage_ranked_first_valid([b, a], config=config)

    np.testing.assert_array_equal(first.values, [[2, 1], [2, 2]])
    np.testing.assert_array_equal(first.valid_mask, np.ones((2, 2), dtype=bool))
    np.testing.assert_array_equal(first.contributor_map, [[1, 0], [1, 1]])
    assert first.source_scene_ids == ("S2/A", "S2/B")
    assert first.contributing_scene_ids == ("S2/A", "S2/B")
    assert first.per_scene_pixel_counts == {"S2/A": 1, "S2/B": 3}
    assert first.record["per_scene_valid_pixel_counts"] == {"S2/A": 2, "S2/B": 3}
    assert first.record["composition_order_scene_ids"] == ["S2/B", "S2/A"]
    assert first.record == second.record
    np.testing.assert_array_equal(first.contributor_map, second.contributor_map)


def test_coverage_ranked_tie_breaks_by_utf8_scene_id():
    config = CompositionCandidateConfig(
        candidate_id="coverage-ranked-first-valid-v1",
        method="coverage_ranked_first_valid",
    )
    z = _scene("Z", [[9, 9]], [[True, False]])
    a = _scene("A", [[1, 1]], [[True, False]])
    result = compose_coverage_ranked_first_valid([z, a], config=config)
    np.testing.assert_array_equal(result.values, [[1, np.nan]])
    assert result.record["composition_order_scene_ids"] == ["A", "Z"]
    assert result.per_scene_pixel_counts == {"A": 1, "Z": 0}
    assert result.contributing_scene_ids == ("A",)
    assert result.record["valid_coverage_fraction"] == 0.5


def test_composition_comparison_mask_controls_coverage_and_uncovered_output():
    config = CompositionCandidateConfig(
        candidate_id="coverage-ranked-first-valid-v1",
        method="coverage_ranked_first_valid",
    )
    scene = _scene("A", [[1, 2], [3, 4]], np.ones((2, 2), dtype=bool))
    comparison = np.array([[True, False], [False, True]])
    result = compose_coverage_ranked_first_valid(
        [scene], config=config, comparison_mask=comparison
    )

    np.testing.assert_array_equal(result.valid_mask, comparison)
    np.testing.assert_array_equal(result.contributor_map, [[0, -1], [-1, 0]])
    assert result.values[0, 0] == 1
    assert result.values[1, 1] == 4
    assert np.isnan(result.values[0, 1]) and np.isnan(result.values[1, 0])
    assert result.record["array_pixel_count"] == 4
    assert result.record["total_pixel_count"] == 2
    assert result.record["valid_pixel_count"] == 2
    assert result.record["per_scene_valid_pixel_counts"] == {"A": 2}
    assert result.per_scene_pixel_counts == {"A": 2}

    full = compose_coverage_ranked_first_valid([scene], config=config)
    assert result.record["input_sha256"] != full.record["input_sha256"]


def test_composition_comparison_mask_is_strict_for_both_methods():
    coverage_config = CompositionCandidateConfig(
        candidate_id="coverage-ranked-first-valid-v1",
        method="coverage_ranked_first_valid",
    )
    coverage_scene = _scene("A", [[1]], [[True]])
    with pytest.raises(ValueError, match="at least one true"):
        compose_coverage_ranked_first_valid(
            [coverage_scene],
            config=coverage_config,
            comparison_mask=np.array([[False]]),
        )

    pixel_scene = _scene("A", [[1]], [[True]], cloud=[[10]], scl=[[4]])
    with pytest.raises(TypeError, match="boolean dtype"):
        compose_min_cloudprob_sclrank_sceneid(
            [pixel_scene],
            config=_pixel_config(),
            comparison_mask=np.array([[1]], dtype=np.uint8),
        )


def test_pixel_composition_uses_cloud_then_scl_rank_then_scene_id():
    a = _scene(
        "A",
        [[1, 1], [1, 1]],
        [[True, True], [False, True]],
        cloud=[[10, 20], [99, 30]],
        scl=[[4, 7], [4, 5]],
    )
    b = _scene(
        "B",
        [[2, 2], [2, 2]],
        [[True, True], [True, True]],
        cloud=[[5, 20], [15, 40]],
        scl=[[7, 4], [6, 4]],
    )
    first = compose_min_cloudprob_sclrank_sceneid([b, a], config=_pixel_config())
    second = compose_min_cloudprob_sclrank_sceneid([a, b], config=_pixel_config())
    # B wins lower cloud at [0,0]/[1,0], lower SCL rank at [0,1]; A wins [1,1].
    np.testing.assert_array_equal(first.values, [[2, 2], [2, 1]])
    np.testing.assert_array_equal(first.contributor_map, [[1, 1], [1, 0]])
    assert first.per_scene_pixel_counts == {"A": 1, "B": 3}
    assert first.record == second.record
    assert first.record["valid_coverage_fraction"] == 1.0


def test_pixel_composition_full_tie_uses_utf8_scene_id():
    z = _scene("Z", [[9]], [[True]], cloud=[[20]], scl=[[4]])
    a = _scene("A", [[1]], [[True]], cloud=[[20]], scl=[[4]])
    result = compose_min_cloudprob_sclrank_sceneid([z, a], config=_pixel_config())
    np.testing.assert_array_equal(result.values, [[1]])
    assert result.contributing_scene_ids == ("A",)


def test_composition_preserves_multiband_values_and_missing_coverage():
    first = _scene(
        "A",
        [[[1, 1]], [[10, 10]]],
        [[True, False]],
        cloud=[[5, 99]],
        scl=[[4, 4]],
    )
    second = _scene(
        "B",
        [[[2, 2]], [[20, 20]]],
        [[False, False]],
        cloud=[[99, 99]],
        scl=[[4, 4]],
    )
    result = compose_min_cloudprob_sclrank_sceneid(
        [first, second], config=_pixel_config()
    )
    assert result.values.shape == (2, 1, 2)
    np.testing.assert_array_equal(result.values[:, 0, 0], [1, 10])
    assert np.isnan(result.values[:, 0, 1]).all()
    np.testing.assert_array_equal(result.contributor_map, [[0, -1]])
    assert result.record["valid_pixel_count"] == 1
    assert result.record["total_pixel_count"] == 2
    assert result.record["valid_coverage_fraction"] == 0.5


def test_composition_requires_unique_ids_metadata_and_finite_valid_values():
    config = CompositionCandidateConfig(
        candidate_id="coverage-ranked-first-valid-v1",
        method="coverage_ranked_first_valid",
    )
    scene = _scene("A", [[1]], [[True]])
    with pytest.raises(ValueError, match="duplicate scene_id"):
        compose_coverage_ranked_first_valid(
            [scene, copy.deepcopy(scene)], config=config
        )
    bad_value = _scene("B", [[np.nan]], [[True]])
    with pytest.raises(ValueError, match="non-finite values"):
        compose_coverage_ranked_first_valid([bad_value], config=config)
    missing_metadata = CompositionScene(
        scene_id="C",
        values=np.array([[1.0]]),
        valid_mask=np.array([[True]]),
        source_metadata_sha256=None,  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="source_metadata_sha256 is required"):
        compose_coverage_ranked_first_valid([missing_metadata], config=config)


def test_pixel_composition_requires_uint8_probability_and_ranked_scl():
    missing_cloud = _scene("A", [[1]], [[True]], scl=[[4]])
    with pytest.raises(ValueError, match="lacks cloud_probability"):
        compose_min_cloudprob_sclrank_sceneid([missing_cloud], config=_pixel_config())

    missing_scl = _scene("A", [[1]], [[True]], cloud=[[10]])
    with pytest.raises(ValueError, match="lacks SCL"):
        compose_min_cloudprob_sclrank_sceneid([missing_scl], config=_pixel_config())

    float_cloud = _scene(
        "A", [[1]], [[True]], cloud=[[10.0]], scl=[[4]], cloud_dtype=float
    )
    with pytest.raises(ValueError, match="uint8"):
        compose_min_cloudprob_sclrank_sceneid([float_cloud], config=_pixel_config())

    out_of_range = _scene("A", [[1]], [[True]], cloud=[[101]], scl=[[4]])
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        compose_min_cloudprob_sclrank_sceneid([out_of_range], config=_pixel_config())

    unranked_scl = _scene("A", [[1]], [[True]], cloud=[[10]], scl=[[3]])
    with pytest.raises(ValueError, match="absent from rank order"):
        compose_min_cloudprob_sclrank_sceneid([unranked_scl], config=_pixel_config())


def test_canonical_array_digest_normalizes_layout_dtype_nan_and_negative_zero():
    first = np.array([[np.nan, -0.0], [1.5, 2.5]], dtype=">f4")
    second = np.asfortranarray(
        np.array([[np.nan, 0.0], [1.5, 2.5]], dtype=np.float64)
    )
    assert canonical_array_record(first) == canonical_array_record(second)


def test_config_digest_changes_for_scientifically_material_parameter():
    first = _extended_mask_config()
    second = _extended_mask_config(dilation_m=40)
    assert first.config_sha256 != second.config_sha256
    assert _pixel_config().config_sha256 != _pixel_config(
        scl_rank_order=(4, 2, 5, 6, 7, 11)
    ).config_sha256
