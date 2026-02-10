"""Tests for SPI (Standardized Precipitation Index) computation."""

import numpy as np
import pytest

from src.processing.spi import compute_spi, compute_spi_3month


class TestComputeSPI:
    def test_average_rainfall_near_zero(self):
        """Average rainfall should produce SPI near 0."""
        # Generate synthetic precipitation from a gamma distribution
        np.random.seed(42)
        ref = np.random.gamma(shape=2, scale=50, size=100)
        # Target value = mean of the reference → SPI should be near 0
        target_val = np.mean(ref)
        data = np.append(ref, target_val)
        spi = compute_spi(data)
        assert -0.5 < spi < 0.5, f"SPI for mean rainfall should be near 0, got {spi}"

    def test_drought_negative_spi(self):
        """Well-below-average rainfall should produce negative SPI."""
        np.random.seed(42)
        ref = np.random.gamma(shape=2, scale=50, size=100)
        # Target value = very low (10th percentile)
        target_val = np.percentile(ref, 5)
        data = np.append(ref, target_val)
        spi = compute_spi(data)
        assert spi < -1.0, f"SPI for drought should be < -1.0, got {spi}"

    def test_wet_positive_spi(self):
        """Well-above-average rainfall should produce positive SPI."""
        np.random.seed(42)
        ref = np.random.gamma(shape=2, scale=50, size=100)
        # Target value = 95th percentile
        target_val = np.percentile(ref, 95)
        data = np.append(ref, target_val)
        spi = compute_spi(data)
        assert spi > 1.0, f"SPI for wet conditions should be > 1.0, got {spi}"

    def test_zero_rainfall(self):
        """Zero rainfall should produce a negative SPI."""
        np.random.seed(42)
        ref = np.random.gamma(shape=2, scale=50, size=100)
        data = np.append(ref, 0.0)
        spi = compute_spi(data)
        assert spi < 0, f"SPI for zero rainfall should be negative, got {spi}"

    def test_handles_nan(self):
        """NaN target should return 0."""
        data = np.array([50.0, 60.0, 70.0, np.nan])
        spi = compute_spi(data)
        assert spi == 0.0

    def test_few_values_fallback(self):
        """With very few values, should fall back to z-score."""
        data = np.array([50.0, 60.0, 70.0, 20.0])
        spi = compute_spi(data)
        # Should not raise, even with < 10 non-zero values
        assert isinstance(spi, float)


class TestComputeSPI3Month:
    def test_basic_computation(self):
        """SPI-3 should work with sufficient monthly data."""
        np.random.seed(42)
        # 5 years of monthly data (60 months)
        monthly = list(np.random.gamma(shape=2, scale=50, size=60))
        spi = compute_spi_3month(monthly)
        assert isinstance(spi, float)
        assert -4 < spi < 4  # SPI rarely exceeds ±3

    def test_drought_signal(self):
        """Three very dry months after wet history should give negative SPI."""
        np.random.seed(42)
        # Normal rainfall for 57 months
        normal = list(np.random.gamma(shape=2, scale=50, size=57))
        # Then 3 very dry months
        drought = [5.0, 3.0, 2.0]
        monthly = normal + drought
        spi = compute_spi_3month(monthly)
        assert spi < -1.0, f"SPI-3 after drought should be < -1.0, got {spi}"

    def test_too_few_months(self):
        """Less than 3 months should return 0."""
        spi = compute_spi_3month([50.0, 60.0])
        assert spi == 0.0

    def test_returns_float(self):
        """Result should always be a float."""
        monthly = [50.0] * 36
        spi = compute_spi_3month(monthly)
        assert isinstance(spi, float)
