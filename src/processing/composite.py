"""Build temporal composites (monthly, seasonal) from multi-scene imagery."""

from __future__ import annotations

from typing import Optional

import numpy as np
import xarray as xr
from loguru import logger

from config.settings import AOI_BBOX, MAX_CLOUD_COVER


def median_composite(arrays: list[xr.DataArray], dim_name: str = "time") -> xr.DataArray:
    """Compute a pixel-wise median composite from a stack of arrays.

    NaN values (masked pixels) are ignored in the median calculation.

    Parameters
    ----------
    arrays : list[xr.DataArray]
        List of spatially aligned arrays (same CRS, resolution, extent).
    dim_name : str
        Name for the stacking dimension.

    Returns
    -------
    xr.DataArray
        Median composite.
    """
    if not arrays:
        raise ValueError("Cannot create composite from empty list")

    # Compute() each lazy array first to avoid chunk fragmentation,
    # then concat as in-memory arrays (much faster for compositing)
    computed = [arr.compute() for arr in arrays]

    stacked = xr.concat(computed, dim=dim_name, join="outer")
    composite = stacked.median(dim=dim_name, skipna=True)
    composite.attrs["composite_method"] = "median"
    composite.attrs["n_scenes"] = len(arrays)
    logger.info("Median composite from {} scenes", len(arrays))
    return composite


def mean_composite(arrays: list[xr.DataArray], dim_name: str = "time") -> xr.DataArray:
    """Compute a pixel-wise mean composite from a stack of arrays."""
    if not arrays:
        raise ValueError("Cannot create composite from empty list")

    computed = [arr.compute() for arr in arrays]

    stacked = xr.concat(computed, dim=dim_name, join="outer")
    composite = stacked.mean(dim=dim_name, skipna=True)
    composite.attrs["composite_method"] = "mean"
    composite.attrs["n_scenes"] = len(arrays)
    return composite


def std_composite(arrays: list[xr.DataArray], dim_name: str = "time") -> xr.DataArray:
    """Compute a pixel-wise standard deviation from a stack of arrays."""
    if not arrays:
        raise ValueError("Cannot create composite from empty list")

    computed = [arr.compute() for arr in arrays]

    stacked = xr.concat(computed, dim=dim_name, join="outer")
    composite = stacked.std(dim=dim_name, skipna=True)
    composite.attrs["composite_method"] = "std"
    composite.attrs["n_scenes"] = len(arrays)
    return composite


def monthly_composite(
    index_arrays: list[xr.DataArray],
    dates: list[str],
    month: int,
) -> tuple[xr.DataArray, xr.DataArray]:
    """Compute mean and standard deviation composites for a specific month.

    Used for building seasonal baselines.

    Parameters
    ----------
    index_arrays : list[xr.DataArray]
        All available index arrays across multiple years.
    dates : list[str]
        ISO date strings corresponding to each array.
    month : int
        Target month (1–12).

    Returns
    -------
    tuple[xr.DataArray, xr.DataArray]
        (mean composite, standard deviation composite) for the given month.
    """
    from datetime import datetime

    month_arrays = []
    for arr, date_str in zip(index_arrays, dates):
        dt = datetime.fromisoformat(date_str[:10])
        if dt.month == month:
            month_arrays.append(arr)

    if not month_arrays:
        raise ValueError(f"No data available for month {month}")

    logger.info("Building monthly composite for month {}: {} scenes", month, len(month_arrays))

    mean = mean_composite(month_arrays)
    std = std_composite(month_arrays)

    mean.attrs["month"] = month
    std.attrs["month"] = month

    return mean, std


def seasonal_composite(
    index_arrays: list[xr.DataArray],
    dates: list[str],
    season: str,
) -> xr.DataArray:
    """Compute a median composite for a season.

    Parameters
    ----------
    index_arrays : list[xr.DataArray]
        All available index arrays.
    dates : list[str]
        ISO date strings.
    season : str
        One of "wet" (Nov-Apr) or "dry" (May-Oct).

    Returns
    -------
    xr.DataArray
        Seasonal median composite.
    """
    from datetime import datetime

    wet_months = {11, 12, 1, 2, 3, 4}
    dry_months = {5, 6, 7, 8, 9, 10}

    target_months = wet_months if season == "wet" else dry_months

    season_arrays = []
    for arr, date_str in zip(index_arrays, dates):
        dt = datetime.fromisoformat(date_str[:10])
        if dt.month in target_months:
            season_arrays.append(arr)

    if not season_arrays:
        raise ValueError(f"No data available for {season} season")

    logger.info("Building {} season composite: {} scenes", season, len(season_arrays))
    composite = median_composite(season_arrays)
    composite.attrs["season"] = season
    return composite
