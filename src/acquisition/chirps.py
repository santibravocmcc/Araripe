"""Fetch CHIRPS 2.0 monthly precipitation data for SPI computation.

CHIRPS (Climate Hazards Group InfraRed Precipitation with Station data)
provides global rainfall estimates at 0.05° resolution from 1981–present.

Data is accessed as GeoTIFFs via HTTP from the UCSB data server.
Files are cached locally to avoid re-downloading.
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from loguru import logger

from config.settings import AOI_BBOX, CHIRPS_BASE_URL, CHIRPS_CACHE_DIR


def _get_cache_path(year: int, month: int) -> Path:
    """Return the local cache path for a CHIRPS monthly file."""
    CHIRPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CHIRPS_CACHE_DIR / f"chirps-v2.0.{year}.{month:02d}.tif"


def _download_chirps_month(year: int, month: int) -> Path:
    """Download a single CHIRPS monthly precipitation GeoTIFF.

    Downloads the gzipped file from UCSB, decompresses it, and caches
    the result locally.

    Parameters
    ----------
    year : int
        Year (1981–present).
    month : int
        Month (1–12).

    Returns
    -------
    Path
        Local path to the cached GeoTIFF.
    """
    import urllib.request

    cache_path = _get_cache_path(year, month)

    if cache_path.exists():
        logger.debug("CHIRPS cache hit: {}", cache_path.name)
        return cache_path

    filename = f"chirps-v2.0.{year}.{month:02d}.tif.gz"
    url = f"{CHIRPS_BASE_URL}/{filename}"

    gz_path = cache_path.with_suffix(".tif.gz")

    logger.info("Downloading CHIRPS: {}", url)
    try:
        urllib.request.urlretrieve(url, str(gz_path))
    except Exception as e:
        raise RuntimeError(f"Failed to download CHIRPS data for {year}-{month:02d}: {e}")

    # Decompress
    logger.debug("Decompressing {}", gz_path.name)
    with gzip.open(str(gz_path), "rb") as f_in:
        with open(str(cache_path), "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    # Remove gzip file
    gz_path.unlink()

    logger.info("Cached CHIRPS: {}", cache_path.name)
    return cache_path


def fetch_chirps_monthly(
    year: int,
    month: int,
    bbox: list[float] = AOI_BBOX,
) -> float:
    """Fetch CHIRPS monthly precipitation and compute the regional mean.

    Downloads the global GeoTIFF (if not cached), extracts the AOI window,
    and returns the mean precipitation in mm/month.

    Parameters
    ----------
    year : int
        Year.
    month : int
        Month (1–12).
    bbox : list[float]
        Bounding box [west, south, east, north] in EPSG:4326.

    Returns
    -------
    float
        Mean precipitation over the AOI in mm/month.
    """
    tif_path = _download_chirps_month(year, month)

    with rasterio.open(str(tif_path)) as src:
        # Extract only the AOI window from the global file
        window = from_bounds(bbox[0], bbox[1], bbox[2], bbox[3], src.transform)
        data = src.read(1, window=window)

        # CHIRPS uses -9999 as nodata
        data = np.where(data < 0, np.nan, data)

        mean_precip = float(np.nanmean(data))

    logger.debug(
        "CHIRPS {}-{:02d}: mean precip = {:.1f} mm",
        year, month, mean_precip,
    )
    return mean_precip


def fetch_chirps_range(
    months: list[tuple[int, int]],
    bbox: list[float] = AOI_BBOX,
) -> list[float]:
    """Fetch CHIRPS precipitation for a list of (year, month) tuples.

    Parameters
    ----------
    months : list[tuple[int, int]]
        List of (year, month) pairs.
    bbox : list[float]
        Bounding box.

    Returns
    -------
    list[float]
        Precipitation values in mm/month for each requested month.
    """
    values = []
    for year, month in months:
        try:
            val = fetch_chirps_monthly(year, month, bbox)
            values.append(val)
        except Exception as e:
            logger.warning("Failed to fetch CHIRPS {}-{:02d}: {}", year, month, e)
            values.append(np.nan)
    return values
