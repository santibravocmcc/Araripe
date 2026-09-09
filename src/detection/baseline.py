"""Build and manage seasonal baselines for change detection.

Baselines consist of per-pixel mean and standard deviation for each calendar
month, computed from 3–5 years of historical imagery. These are stored as
Cloud Optimized GeoTIFFs for efficient loading.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
import xarray as xr
from loguru import logger
from rasterio.transform import from_bounds

from config.settings import (
    BASELINES_DIR,
    BASELINE_MANIFEST_PATH,
    BASELINE_MONTHS,
    TARGET_CRS,
)
from src.detection.baseline_selection import (
    MANIFEST_SCHEMA_V1,
    BaselineGeneration,
    verify_baseline_object,
    verify_object_against_manifest,
)


@lru_cache(maxsize=72)
def _verify_authoritative_file(path_text: str) -> None:
    """Bind a production-path raster to the accepted manifest once per process.

    The frozen blue default, kept on its own cache and reading its manifest
    path from this module's globals — which is how
    ``test_production_loader_rejects_unmanifested_bytes`` redirects it. The
    check itself lives in one place (``verify_object_against_manifest``) so
    the default path and a named generation cannot drift apart.
    """
    verify_object_against_manifest(
        Path(BASELINE_MANIFEST_PATH), MANIFEST_SCHEMA_V1, Path(path_text)
    )


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

    # Explicit NaN nodata so out-of-AOI pixels and zero-scene pixels are not
    # silently encoded as 0.0 (which the colormap would render as a real value).
    data = data.rio.write_nodata(np.nan, inplace=False)
    data.rio.to_raster(
        str(path),
        driver="COG",
        compress=compress,
        nodata=np.nan,
    )
    logger.info("Saved baseline COG: {}", path)
    return path


def load_baseline(
    index_name: str,
    month: int,
    stat: str = "mean",
    baselines_dir: Path | None = None,
    *,
    generation: BaselineGeneration | None = None,
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
    baselines_dir : Path, optional
        Directory containing baseline COGs. Defaults to ``BASELINES_DIR``, the
        frozen v1 production directory, which is also the only directory whose
        rasters are bound to the accepted manifest when no generation is named.
    generation : BaselineGeneration, optional
        A registered baseline generation (Phase 3). When given, its own
        directory is read and every raster is bound to *its* manifest, so a
        v2 raster can never be accepted against the v1 inventory or the other
        way round. Mutually exclusive with ``baselines_dir``: the two would be
        two answers to one question.

    Returns
    -------
    xr.DataArray
        Baseline raster.
    """
    import rioxarray  # noqa: F401

    if generation is not None and baselines_dir is not None:
        raise ValueError(
            "name a baseline generation or a directory, never both"
        )
    if generation is not None:
        directory = Path(generation.directory)
    else:
        directory = Path(BASELINES_DIR if baselines_dir is None else baselines_dir)

    filename = f"{index_name}_month{month:02d}_{stat}.tif"
    path = directory / filename

    if not path.exists():
        raise FileNotFoundError(f"Baseline not found: {path}")
    if generation is not None:
        verify_baseline_object(generation, path)
    elif directory.resolve() == Path(BASELINES_DIR).resolve():
        _verify_authoritative_file(str(path.resolve()))

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
    baselines_dir: Path | None = None,
    *,
    generation: BaselineGeneration | None = None,
) -> tuple[xr.DataArray, xr.DataArray]:
    """Load both mean and std baselines for a given index and month.

    Returns
    -------
    tuple[xr.DataArray, xr.DataArray]
        (mean baseline, std baseline)
    """
    mean = load_baseline(
        index_name, month, "mean", baselines_dir, generation=generation
    )
    std = load_baseline(
        index_name, month, "std", baselines_dir, generation=generation
    )
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
