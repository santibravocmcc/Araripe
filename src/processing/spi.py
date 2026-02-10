"""Standardized Precipitation Index (SPI) computation.

SPI transforms precipitation data into a standardized scale where:
- SPI > 0: wetter than normal
- SPI < 0: drier than normal
- SPI < -1.0: moderate drought
- SPI < -1.5: severe drought
- SPI < -2.0: extreme drought

The 3-month SPI (SPI-3) is used to detect seasonal drought conditions
that can cause false positive deforestation alerts in Caatinga vegetation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
from loguru import logger
from scipy import stats

from config.settings import AOI_BBOX


def compute_spi(
    precipitation: np.ndarray,
    reference_period: Optional[np.ndarray] = None,
) -> float:
    """Compute the Standardized Precipitation Index for a single value.

    Fits a gamma distribution to the reference precipitation data,
    then transforms the target value to a standard normal deviate.

    Parameters
    ----------
    precipitation : np.ndarray
        Precipitation values to standardize. The LAST value is the
        target; all values are used as the reference if reference_period
        is not provided.
    reference_period : np.ndarray, optional
        Historical precipitation data for fitting the distribution.
        If None, uses all of `precipitation`.

    Returns
    -------
    float
        SPI value. Negative = drought, positive = wet.
    """
    if reference_period is None:
        reference_period = precipitation

    # Check if the target value is NaN first
    target = precipitation[-1] if len(precipitation) > 0 else 0
    if np.isnan(target):
        return 0.0

    # Remove zeros and NaN for gamma fitting
    ref_clean = reference_period[~np.isnan(reference_period)]
    ref_nonzero = ref_clean[ref_clean > 0]

    if len(ref_nonzero) < 10:
        logger.warning(
            "Too few non-zero precipitation values ({}) for reliable SPI",
            len(ref_nonzero),
        )
        # Fallback: use z-score instead of gamma-based SPI
        mean = np.nanmean(ref_clean) if len(ref_clean) > 0 else 0
        std = np.nanstd(ref_clean) if len(ref_clean) > 1 else 1
        return float((target - mean) / std) if std > 0 else 0.0

    # Check for zero variance (constant values) — gamma fit requires variance
    if np.std(ref_nonzero) < 1e-10:
        logger.warning("Near-zero variance in reference data, returning SPI=0.0")
        return 0.0

    # Fit gamma distribution to reference data
    # Probability of zero precipitation
    q = np.sum(ref_clean == 0) / len(ref_clean)

    # Fit gamma to non-zero values
    try:
        shape, loc, scale = stats.gamma.fit(ref_nonzero, floc=0)
    except Exception as e:
        logger.warning("Gamma fit failed: {}. Falling back to z-score.", e)
        mean = np.nanmean(ref_clean)
        std = np.nanstd(ref_clean)
        return float((target - mean) / std) if std > 0 else 0.0

    # Transform the target value (already extracted above)
    if target == 0:
        # CDF at zero = probability of zero
        cdf_val = q
    else:
        # Mixed distribution: P(X=0) + P(X>0) * gamma_CDF
        gamma_cdf = stats.gamma.cdf(target, shape, loc=0, scale=scale)
        cdf_val = q + (1 - q) * gamma_cdf

    # Clamp to avoid infinite values at the tails
    cdf_val = np.clip(cdf_val, 0.001, 0.999)

    # Transform to standard normal
    spi = float(stats.norm.ppf(cdf_val))

    return spi


def compute_spi_3month(monthly_precip: list[float]) -> float:
    """Compute 3-month SPI from a series of monthly precipitation values.

    Sums the last 3 months of precipitation and compares against
    the historical distribution of 3-month sums.

    Parameters
    ----------
    monthly_precip : list[float]
        Monthly precipitation values (mm). Must have at least 15 values
        for reliable gamma fitting. The last 3 values are the target period.

    Returns
    -------
    float
        SPI-3 value for the most recent 3-month period.
    """
    arr = np.array(monthly_precip, dtype=np.float64)

    if len(arr) < 3:
        logger.warning("Need at least 3 months for SPI-3, got {}", len(arr))
        return 0.0

    # Compute rolling 3-month sums
    sums_3m = np.convolve(arr, np.ones(3), mode="valid")

    if len(sums_3m) < 2:
        logger.warning("Not enough data for SPI-3 reference period")
        return 0.0

    spi = compute_spi(sums_3m)

    logger.info(
        "SPI-3 = {:.2f} (3-month precip sum: {:.1f} mm, ref mean: {:.1f} mm)",
        spi,
        sums_3m[-1],
        np.nanmean(sums_3m),
    )

    return spi


def get_current_spi(
    bbox: list[float] = AOI_BBOX,
    reference_years: int = 5,
) -> float:
    """Fetch CHIRPS data and compute the current 3-month SPI.

    Downloads the last `reference_years` of monthly precipitation for the AOI,
    then computes SPI-3 for the most recent 3-month window.

    Parameters
    ----------
    bbox : list[float]
        AOI bounding box [west, south, east, north].
    reference_years : int
        Years of history for the reference distribution.

    Returns
    -------
    float
        Current SPI-3 value.
    """
    from src.acquisition.chirps import fetch_chirps_range

    now = datetime.utcnow()

    # Build list of (year, month) for the reference period + current
    # Go back reference_years from current month
    months = []
    year = now.year - reference_years
    month = now.month

    while (year, month) <= (now.year, now.month - 1):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1

    if not months:
        logger.warning("No months to fetch for SPI computation")
        return 0.0

    logger.info(
        "Fetching CHIRPS data: {}-{:02d} to {}-{:02d} ({} months)",
        months[0][0], months[0][1],
        months[-1][0], months[-1][1],
        len(months),
    )

    # Fetch precipitation data
    precip_values = fetch_chirps_range(months, bbox)

    # Compute SPI-3
    spi = compute_spi_3month(precip_values)

    return spi
