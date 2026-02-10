"""Tests for band grid alignment in load_bands().

Verifies that bands with slightly different pixel grids (from different
native resolutions) are properly aligned before being combined into a Dataset,
preventing the mask_sentinel2() .where() call from producing all-NaN results.
"""

import numpy as np
import pytest
import xarray as xr


class TestGridAlignment:
    """Verify that reindex_like with nearest-neighbor fixes sub-pixel offsets."""

    def test_aligned_bands_share_coordinates(self):
        """After alignment, all variables should have identical x/y coords."""
        # Simulate two bands with sub-pixel coordinate offsets
        # (as happens when reprojecting 10m and 20m bands to a common 20m grid)
        y_a = [100.0, 80.0, 60.0]
        x_a = [0.0, 20.0, 40.0]

        y_b = [100.05, 80.05, 60.05]  # 0.05m offset (sub-pixel at 20m)
        x_b = [0.05, 20.05, 40.05]

        band_a = xr.DataArray(
            np.ones((3, 3)),
            dims=["y", "x"],
            coords={"y": y_a, "x": x_a},
        )
        band_b = xr.DataArray(
            np.ones((3, 3)) * 2,
            dims=["y", "x"],
            coords={"y": y_b, "x": x_b},
        )

        # Align band_b to band_a's grid
        aligned_b = band_b.reindex_like(band_a, method="nearest", tolerance=20.0)

        # Coordinates should now match exactly
        np.testing.assert_array_equal(aligned_b.coords["y"].values, band_a.coords["y"].values)
        np.testing.assert_array_equal(aligned_b.coords["x"].values, band_a.coords["x"].values)

        # Values should be preserved
        np.testing.assert_array_equal(aligned_b.values, np.ones((3, 3)) * 2)

    def test_where_preserves_data_after_alignment(self):
        """The core bug scenario: SCL mask applied to aligned spectral bands."""
        # SCL grid (the reference)
        y_scl = [100.0, 80.0, 60.0]
        x_scl = [0.0, 20.0, 40.0]

        # Spectral band grid (sub-pixel offset from different native resolution)
        y_spec = [100.05, 80.05, 60.05]
        x_spec = [0.05, 20.05, 40.05]

        scl = xr.DataArray(
            np.array([[4, 4, 4], [4, 4, 8], [4, 4, 4]]),  # 4=veg, 8=cloud
            dims=["y", "x"],
            coords={"y": y_scl, "x": x_scl},
        )
        nir = xr.DataArray(
            np.ones((3, 3)) * 0.5,
            dims=["y", "x"],
            coords={"y": y_spec, "x": x_spec},
        )

        # Without alignment: .where() produces all NaN due to coordinate mismatch
        clear_mask = scl == 4
        result_unaligned = nir.where(clear_mask)
        assert result_unaligned.isnull().all(), "Unaligned .where() should produce all NaN"

        # With alignment: .where() preserves clear pixels
        nir_aligned = nir.reindex_like(scl, method="nearest", tolerance=20.0)
        result_aligned = nir_aligned.where(clear_mask)

        # 8 of 9 pixels should be valid (one is cloudy at position [1,2])
        assert int(result_aligned.notnull().sum()) == 8
        # The cloudy pixel should be NaN
        assert np.isnan(result_aligned.values[1, 2])

    def test_tolerance_rejects_large_offsets(self):
        """If coordinates differ by more than tolerance, result should be NaN."""
        band_a = xr.DataArray(
            np.ones((3, 3)),
            dims=["y", "x"],
            coords={"y": [100.0, 80.0, 60.0], "x": [0.0, 20.0, 40.0]},
        )
        # Band with coordinates far outside the tolerance
        band_b = xr.DataArray(
            np.ones((3, 3)) * 2,
            dims=["y", "x"],
            coords={"y": [200.0, 180.0, 160.0], "x": [100.0, 120.0, 140.0]},
        )

        # With tight tolerance, non-overlapping pixels become NaN
        aligned_b = band_b.reindex_like(band_a, method="nearest", tolerance=20.0)
        assert aligned_b.isnull().all()

    def test_alignment_with_many_bands(self):
        """Simulate the full Sentinel-2 scenario: SCL + 5 spectral bands."""
        # Reference grid (SCL, natively 20m)
        y_ref = np.arange(100, 0, -20, dtype=float)  # [100, 80, 60, 40, 20]
        x_ref = np.arange(0, 100, 20, dtype=float)     # [0, 20, 40, 60, 80]

        scl = xr.DataArray(
            np.full((5, 5), 4),  # all clear
            dims=["y", "x"],
            coords={"y": y_ref, "x": x_ref},
        )

        # 5 spectral bands with various sub-pixel offsets
        bands = {}
        bands["scl"] = scl
        for i, name in enumerate(["nir", "nir08", "red", "swir16", "swir22"]):
            offset = (i + 1) * 0.01  # increasingly different offsets
            bands[name] = xr.DataArray(
                np.random.rand(5, 5),
                dims=["y", "x"],
                coords={
                    "y": y_ref + offset,
                    "x": x_ref + offset,
                },
            )

        # Apply the same alignment logic as load_bands()
        ref_name = "scl"
        ref = bands[ref_name]
        for name in list(bands.keys()):
            if name != ref_name:
                bands[name] = bands[name].reindex_like(
                    ref, method="nearest", tolerance=20.0,
                )

        # Create dataset and apply mask
        ds = xr.Dataset(bands)
        clear_mask = ds["scl"] == 4
        masked = ds.drop_vars("scl").where(clear_mask)

        # All pixels should be valid (all SCL == 4)
        for var in masked.data_vars:
            assert masked[var].notnull().all(), f"Band {var} has unexpected NaN after alignment"


class TestCloudMaskAfterAlignment:
    """Integration-style test: simulate the full mask_sentinel2 flow."""

    def test_mask_preserves_clear_pixels_with_aligned_grids(self):
        """After alignment, mask_sentinel2 should not zero out all data."""
        # Build a dataset mimicking what load_bands() produces AFTER alignment
        y = [100.0, 80.0, 60.0]
        x = [0.0, 20.0, 40.0]

        ds = xr.Dataset(
            {
                "nir08": xr.DataArray(np.full((3, 3), 0.5), dims=["y", "x"], coords={"y": y, "x": x}),
                "swir16": xr.DataArray(np.full((3, 3), 0.2), dims=["y", "x"], coords={"y": y, "x": x}),
                "scl": xr.DataArray(
                    np.array([[4, 4, 8], [4, 4, 4], [8, 4, 4]]),  # 2 cloudy, 7 clear
                    dims=["y", "x"],
                    coords={"y": y, "x": x},
                ),
            }
        )

        # Replicate mask_sentinel2 logic
        from src.processing.cloud_mask import S2_CLEAR_CLASSES

        scl = ds["scl"]
        clear_mask = xr.zeros_like(scl, dtype=bool)
        for cls in S2_CLEAR_CLASSES:
            clear_mask = clear_mask | (scl == cls)

        masked = ds.drop_vars("scl").where(clear_mask)

        # 7 of 9 pixels should survive
        n_valid = int(masked["nir08"].notnull().sum())
        assert n_valid == 7, f"Expected 7 clear pixels, got {n_valid}"
