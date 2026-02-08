"""Tests for vegetation index computation."""

import numpy as np
import pytest
import xarray as xr

from src.processing.indices import (
    bsi,
    compute_all_indices,
    compute_index,
    evi2,
    nbr,
    ndmi,
    ndvi,
    savi,
)


def _make_dataset(**bands) -> xr.Dataset:
    """Create a simple 3x3 test dataset from band arrays."""
    data_vars = {}
    for name, values in bands.items():
        data_vars[name] = xr.DataArray(
            np.array(values, dtype=np.float64).reshape(3, 3),
            dims=["y", "x"],
        )
    return xr.Dataset(data_vars)


class TestNDVI:
    def test_basic(self):
        ds = _make_dataset(
            nir=[[0.4, 0.5, 0.6]] * 3,
            red=[[0.1, 0.1, 0.1]] * 3,
        )
        result = ndvi(ds)
        # NDVI = (0.4-0.1)/(0.4+0.1) = 0.6 for first pixel
        np.testing.assert_almost_equal(result.values[0, 0], 0.6)

    def test_range(self):
        ds = _make_dataset(
            nir=[[0.0, 0.5, 1.0]] * 3,
            red=[[0.5, 0.5, 0.0]] * 3,
        )
        result = ndvi(ds)
        assert result.values.min() >= -1.0
        assert result.values.max() <= 1.0

    def test_zero_division(self):
        ds = _make_dataset(
            nir=[[0.0, 0.5, 0.3]] * 3,
            red=[[0.0, 0.1, 0.1]] * 3,
        )
        result = ndvi(ds)
        assert np.isnan(result.values[0, 0])  # 0/0 → NaN

    def test_name(self):
        ds = _make_dataset(nir=[[0.5]] * 3, red=[[0.1]] * 3)
        result = ndvi(ds)
        assert result.name == "ndvi"


class TestNDMI:
    def test_basic(self):
        ds = _make_dataset(
            nir08=[[0.4, 0.5, 0.6]] * 3,
            swir16=[[0.2, 0.2, 0.2]] * 3,
        )
        result = ndmi(ds)
        # NDMI = (0.4-0.2)/(0.4+0.2) = 0.333...
        np.testing.assert_almost_equal(result.values[0, 0], 1 / 3)

    def test_name(self):
        ds = _make_dataset(nir08=[[0.5]] * 3, swir16=[[0.1]] * 3)
        result = ndmi(ds)
        assert result.name == "ndmi"


class TestNBR:
    def test_basic(self):
        ds = _make_dataset(
            nir08=[[0.5]] * 3,
            swir22=[[0.1]] * 3,
        )
        result = nbr(ds)
        expected = (0.5 - 0.1) / (0.5 + 0.1)
        np.testing.assert_almost_equal(result.values[0, 0], expected)


class TestEVI2:
    def test_basic(self):
        ds = _make_dataset(
            nir=[[0.5]] * 3,
            red=[[0.1]] * 3,
        )
        result = evi2(ds)
        expected = 2.5 * (0.5 - 0.1) / (0.5 + 2.4 * 0.1 + 1)
        np.testing.assert_almost_equal(result.values[0, 0], expected)


class TestSAVI:
    def test_basic(self):
        ds = _make_dataset(
            nir=[[0.5]] * 3,
            red=[[0.1]] * 3,
        )
        result = savi(ds)
        expected = 1.5 * (0.5 - 0.1) / (0.5 + 0.1 + 0.5)
        np.testing.assert_almost_equal(result.values[0, 0], expected)


class TestBSI:
    def test_basic(self):
        ds = _make_dataset(
            blue=[[0.1]] * 3,
            red=[[0.2]] * 3,
            nir=[[0.4]] * 3,
            swir16=[[0.3]] * 3,
        )
        result = bsi(ds)
        num = (0.3 + 0.2) - (0.4 + 0.1)
        den = (0.3 + 0.2) + (0.4 + 0.1)
        np.testing.assert_almost_equal(result.values[0, 0], num / den)


class TestComputeIndex:
    def test_dispatch_sentinel2(self):
        ds = _make_dataset(
            nir=[[0.5]] * 3,
            red=[[0.1]] * 3,
        )
        result = compute_index(ds, "ndvi", sensor="sentinel2")
        assert result.name == "ndvi"

    def test_dispatch_landsat(self):
        ds = _make_dataset(
            nir08=[[0.5]] * 3,
            red=[[0.1]] * 3,
        )
        result = compute_index(ds, "ndvi", sensor="landsat")
        assert result.name == "ndvi"

    def test_compute_all(self):
        ds = _make_dataset(
            nir=[[0.5]] * 3,
            nir08=[[0.5]] * 3,
            red=[[0.1]] * 3,
            blue=[[0.05]] * 3,
            swir16=[[0.2]] * 3,
            swir22=[[0.15]] * 3,
        )
        result = compute_all_indices(ds, ["ndvi", "ndmi", "nbr", "evi2"])
        assert "ndvi" in result
        assert "ndmi" in result
        assert "nbr" in result
        assert "evi2" in result
