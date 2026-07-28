"""Finite source/reference coverage and scene-anomaly denominator tests."""

import numpy as np
import xarray as xr

from src.detection.change_detect import detect_deforestation
from src.detection.scene_quality import assess_scene_quality
from src.processing.cloud_mask import mask_sentinel2


def _array(values):
    return xr.DataArray(np.asarray(values, dtype=float), dims=["y", "x"])


def test_invalid_cloud_and_nodata_pixels_are_excluded_from_guard_denominator():
    current = xr.Dataset(
        {
            "ndmi": _array([[0.1, 0.5], [np.nan, np.nan]]),
            "nbr": _array([[0.1, 0.5], [np.nan, np.nan]]),
        }
    )
    means = {
        "ndmi": _array([[0.5, 0.5], [0.5, 0.5]]),
        "nbr": _array([[0.5, 0.5], [0.5, 0.5]]),
    }
    stds = {
        "ndmi": _array([[0.1, 0.1], [0.1, 0.1]]),
        "nbr": _array([[0.1, 0.1], [0.1, 0.1]]),
    }
    detection = detect_deforestation(current, means, stds)
    quality = assess_scene_quality(
        detection,
        minimum_required_fraction=0.2,
        anomaly_reject_fraction=0.3,
    )

    assert quality.valid_pixel_count == 2
    assert quality.total_pixel_count == 4
    assert quality.alert_pixel_count == 1
    assert quality.alert_fraction_of_valid == 0.5
    assert quality.scene_decision == "rejected_quality"
    assert np.isnan(detection["confidence"].values[1, 0])


def test_all_nodata_scene_records_low_coverage_reason():
    current = xr.Dataset({"ndmi": _array([[np.nan, np.nan], [np.nan, np.nan]])})
    means = {"ndmi": _array([[0.5, 0.5], [0.5, 0.5]])}
    stds = {"ndmi": _array([[0.1, 0.1], [0.1, 0.1]])}
    quality = assess_scene_quality(
        detect_deforestation(current, means, stds),
        minimum_required_fraction=0.2,
        anomaly_reject_fraction=0.3,
    )
    assert quality.scene_decision == "rejected_low_coverage"
    assert quality.rejection_reason == "no_finite_source_reference_pixels"
    assert quality.valid_coverage_fraction == 0


def test_sentinel_cloud_mask_propagates_to_scene_validity():
    source = xr.Dataset(
        {
            "red": _array([[0.1, 0.1], [0.1, 0.1]]),
            "scl": _array([[4, 9], [3, 5]]),
        }
    )
    masked = mask_sentinel2(source)
    current = xr.Dataset({"ndmi": masked["red"]})
    means = {"ndmi": _array([[0.5, 0.5], [0.5, 0.5]])}
    stds = {"ndmi": _array([[0.1, 0.1], [0.1, 0.1]])}
    detection = detect_deforestation(current, means, stds)
    assert int(detection["valid_pixel_mask"].sum()) == 2
