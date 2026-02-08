"""Build and manage seasonal baselines for change detection.

Baselines consist of per-pixel mean and standard deviation for each calendar
month, computed from 3–5 years of historical imagery. These are stored as
Cloud Optimized GeoTIFFs for efficient loading.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
import xarray as xr
from loguru import logger
from rasterio.transform import from_bounds

from config.settings import BASELINES_DIR, BASELINE_MONTHS, TARGET_CRS


def save_baseline_cog(
    data: xr.DataArray,
    path: Path,
    compress: str = "deflate",
) -> Path:
    """Save a baseline array as a Cloud Optimized GeoTIFF.

    Parameters
    ----------
    data : xr.DataArray
        2D array with spatial coordinates and CRS.
    path : Path
        Output file path.
    compress : str
        Compression algorithm.

    Returns
    -------
    Path
        Path to the created COG.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    data.rio.to_raster(
        str(path),
        driver="COG",
        compress=compress,
    )
    logger.info("Saved baseline COG: {}", path)
    return path


def load_baseline(
    index_name: str,
    month: int,
    stat: str = "mean",
    baselines_dir: Path = BASELINES_DIR,
) -> xr.DataArray:
    """Load a pre-computed baseline COG.

    Parameters
    ----------
    index_name : str
        Vegetation index name (e.g., "ndmi", "nbr").
    month : int
        Calendar month (1–12).
    stat : str
        Statistic type: "mean" or "std".
    baselines_dir : Path
        Directory containing baseline COGs.

    Returns
    -------
    xr.DataArray
        Baseline raster.
    """
    import rioxarray  # noqa: F401

    filename = f"{index_name}_month{month:02d}_{stat}.tif"
    path = baselines_dir / filename

    if not path.exists():
        raise FileNotFoundError(f"Baseline not found: {path}")

    da = rioxarray.open_rasterio(str(path))
    if "band" in da.dims and da.sizes["band"] == 1:
        da = da.squeeze("band", drop=True)

    da.attrs["index"] = index_name
    da.attrs["month"] = month
    da.attrs["stat"] = stat
    logger.debug("Loaded baseline: {}", filename)
    return da


def load_baseline_pair(
    index_name: str,
    month: int,
    baselines_dir: Path = BASELINES_DIR,
) -> tuple[xr.DataArray, xr.DataArray]:
    """Load both mean and std baselines for a given index and month.

    Returns
    -------
    tuple[xr.DataArray, xr.DataArray]
        (mean baseline, std baseline)
    """
    mean = load_baseline(index_name, month, "mean", baselines_dir)
    std = load_baseline(index_name, month, "std", baselines_dir)
    return mean, std


def build_baselines(
    index_arrays: list[xr.DataArray],
    dates: list[str],
    index_name: str,
    baselines_dir: Path = BASELINES_DIR,
    months: list[int] = BASELINE_MONTHS,
) -> dict[int, tuple[Path, Path]]:
    """Build and save monthly baselines from historical data.

    For each month, computes pixel-wise mean and standard deviation from
    all available scenes in that month across multiple years.

    Parameters
    ----------
    index_arrays : list[xr.DataArray]
        Historical index values, one per scene.
    dates : list[str]
        ISO date strings corresponding to each array.
    index_name : str
        Name of the index (used in filenames).
    baselines_dir : Path
        Output directory.
    months : list[int]
        Months to build baselines for.

    Returns
    -------
    dict[int, tuple[Path, Path]]
        Mapping of month → (mean_path, std_path).
    """
    from src.processing.composite import monthly_composite

    results = {}
    for month in months:
        try:
            mean_arr, std_arr = monthly_composite(index_arrays, dates, month)
        except ValueError:
            logger.warning("No data for {} month {}, skipping", index_name, month)
            continue

        mean_path = baselines_dir / f"{index_name}_month{month:02d}_mean.tif"
        std_path = baselines_dir / f"{index_name}_month{month:02d}_std.tif"

        save_baseline_cog(mean_arr, mean_path)
        save_baseline_cog(std_arr, std_path)

        results[month] = (mean_path, std_path)
        logger.info("Built baseline for {} month {:02d}", index_name, month)

    return results


def compute_zscore(
    current: xr.DataArray,
    mean: xr.DataArray,
    std: xr.DataArray,
    min_std: float = 0.01,
) -> xr.DataArray:
    """Compute per-pixel z-score against baseline.

    z = (current - mean) / std

    Parameters
    ----------
    current : xr.DataArray
        Current observation.
    mean : xr.DataArray
        Baseline mean for the corresponding month.
    std : xr.DataArray
        Baseline standard deviation.
    min_std : float
        Minimum std to avoid division by zero in stable areas.

    Returns
    -------
    xr.DataArray
        Z-score values. Negative values indicate below-normal conditions.
    """
    # Clamp std to avoid division by near-zero
    safe_std = std.where(std > min_std, other=min_std)
    zscore = (current - mean) / safe_std
    zscore.name = "zscore"
    return zscore


def compute_delta(current: xr.DataArray, mean: xr.DataArray) -> xr.DataArray:
    """Compute absolute difference from baseline mean.

    delta = current - mean

    Negative values indicate current is below the historical average.
    """
    delta = current - mean
    delta.name = "delta"
    return delta
