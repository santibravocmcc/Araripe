"""Tests for change detection and alert generation."""

import numpy as np
import pytest
import xarray as xr

from src.detection.baseline import compute_delta, compute_zscore
from src.detection.change_detect import detect_deforestation


def _make_array(values, name=None):
    """Create a 3x3 DataArray."""
    da = xr.DataArray(
        np.array(values, dtype=np.float64).reshape(3, 3),
        dims=["y", "x"],
        attrs={"_FillValue": np.nan},
    )
    da = da.rio.set_spatial_dims(x_dim="x", y_dim="y")
    if name:
        da.name = name
    return da


class TestZScore:
    def test_basic_zscore(self):
        current = _make_array([[0.3, 0.3, 0.3]] * 3)
        mean = _make_array([[0.5, 0.5, 0.5]] * 3)
        std = _make_array([[0.1, 0.1, 0.1]] * 3)

        z = compute_zscore(current, mean, std)
        # z = (0.3 - 0.5) / 0.1 = -2.0
        np.testing.assert_almost_equal(z.values[0, 0], -2.0)

    def test_min_std_clamping(self):
        current = _make_array([[0.3]] * 3)
        mean = _make_array([[0.5]] * 3)
        std = _make_array([[0.001]] * 3)  # Very small std

        z = compute_zscore(current, mean, std, min_std=0.01)
        # Should use min_std=0.01: z = (0.3-0.5)/0.01 = -20
        np.testing.assert_almost_equal(z.values[0, 0], -20.0)

    def test_positive_zscore(self):
        current = _make_array([[0.7]] * 3)
        mean = _make_array([[0.5]] * 3)
        std = _make_array([[0.1]] * 3)

        z = compute_zscore(current, mean, std)
        np.testing.assert_almost_equal(z.values[0, 0], 2.0)


class TestDelta:
    def test_negative_delta(self):
        current = _make_array([[0.3]] * 3)
        mean = _make_array([[0.5]] * 3)

        d = compute_delta(current, mean)
        np.testing.assert_almost_equal(d.values[0, 0], -0.2)


class TestDetectDeforestation:
    def test_high_confidence_detection(self):
        """Pixels with extreme anomalies in both NDMI and NBR → high confidence."""
        # Current values well below baseline
        current = xr.Dataset({
            "ndmi": _make_array([[0.1, 0.5, 0.5]] * 3),
            "nbr": _make_array([[0.05, 0.5, 0.5]] * 3),
        })

        means = {
            "ndmi": _make_array([[0.5, 0.5, 0.5]] * 3),
            "nbr": _make_array([[0.5, 0.5, 0.5]] * 3),
        }
        stds = {
            "ndmi": _make_array([[0.1, 0.1, 0.1]] * 3),
            "nbr": _make_array([[0.1, 0.1, 0.1]] * 3),
        }

        result = detect_deforestation(current, means, stds)

        assert "confidence" in result
        assert "is_alert" in result
        # First pixel should be high confidence (z = -4.0 for NDMI, -4.5 for NBR)
        assert result["confidence"].values[0, 0] == 3

    def test_no_deforestation(self):
        """Pixels near baseline → no alerts."""
        current = xr.Dataset({
            "ndmi": _make_array([[0.49, 0.50, 0.51]] * 3),
            "nbr": _make_array([[0.49, 0.50, 0.51]] * 3),
        })

        means = {
            "ndmi": _make_array([[0.5, 0.5, 0.5]] * 3),
            "nbr": _make_array([[0.5, 0.5, 0.5]] * 3),
        }
        stds = {
            "ndmi": _make_array([[0.1, 0.1, 0.1]] * 3),
            "nbr": _make_array([[0.1, 0.1, 0.1]] * 3),
        }

        result = detect_deforestation(current, means, stds)
        assert result["is_alert"].sum().values == 0

    def test_drought_adjustment(self):
        """During drought, thresholds should be widened (fewer alerts)."""
        current = xr.Dataset({
            "ndmi": _make_array([[0.28, 0.5, 0.5]] * 3),
        })
        means = {"ndmi": _make_array([[0.5, 0.5, 0.5]] * 3)}
        stds = {"ndmi": _make_array([[0.1, 0.1, 0.1]] * 3)}

        # Without drought: z = -2.2, should trigger low confidence
        result_normal = detect_deforestation(current, means, stds, spi_3month=0.0)
        # With drought (SPI < -1): threshold widened by 0.5σ → z needs < -2.5
        result_drought = detect_deforestation(current, means, stds, spi_3month=-1.5)

        normal_alerts = int(result_normal["is_alert"].sum().values)
        drought_alerts = int(result_drought["is_alert"].sum().values)

        # Drought should produce fewer or equal alerts
        assert drought_alerts <= normal_alerts
