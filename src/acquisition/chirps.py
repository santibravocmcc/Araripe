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


def _download_resumable(url: str, dest: Path, retries: int = 6, timeout: int = 60) -> Path:
    """Download `url` to `dest` with HTTP Range resume + exponential backoff.

    The UCSB CHIRPS server advertises ``Accept-Ranges: bytes``, so an
    interrupted transfer resumes from the last byte instead of restarting.
    Raises RuntimeError if all attempts fail or the final size is wrong.
    """
    import random
    import time

    import requests

    part = dest.with_suffix(dest.suffix + ".part")
    total = None
    try:
        h = requests.head(url, timeout=timeout, allow_redirects=True)
        if h.ok and "Content-Length" in h.headers:
            total = int(h.headers["Content-Length"])
    except requests.RequestException:
        pass

    for attempt in range(1, retries + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=timeout) as r:
                if have and r.status_code == 200:  # server ignored Range → restart
                    have = 0
                    part.unlink(missing_ok=True)
                elif have and r.status_code == 416:  # already complete
                    break
                r.raise_for_status()
                with open(part, "ab" if have else "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            f.write(chunk)
            if total is None or part.stat().st_size >= total:
                break
            logger.warning("CHIRPS short read ({}/{} bytes), attempt {}/{}",
                           part.stat().st_size, total, attempt, retries)
        except (requests.RequestException, OSError) as e:
            wait = min(60, 2 ** attempt) + random.uniform(0, 1.5)
            logger.warning("CHIRPS download error ({}); retry {}/{} in {:.1f}s",
                           e, attempt, retries, wait)
            time.sleep(wait)
    else:
        raise RuntimeError(f"Failed to download {url} after {retries} attempts")

    if total is not None and part.stat().st_size != total:
        part.unlink(missing_ok=True)
        raise RuntimeError(
            f"CHIRPS size mismatch for {url}: got {part.stat().st_size}, expected {total}")
    part.replace(dest)
    return dest


def _download_chirps_month(year: int, month: int) -> Path:
    """Download a single CHIRPS monthly precipitation GeoTIFF.

    Robust replacement for the old bare ``urlretrieve``: streams the gzipped
    file with resume + exponential-backoff retry, verifies the download against
    the server ``Content-Length``, then decompresses and confirms the result
    opens as a valid raster (a corrupt/partial file is discarded rather than
    cached). Parameters as before (year 1981–present, month 1–12); returns the
    local cache path.
    """
    cache_path = _get_cache_path(year, month)

    if cache_path.exists():
        logger.debug("CHIRPS cache hit: {}", cache_path.name)
        return cache_path

    filename = f"chirps-v2.0.{year}.{month:02d}.tif.gz"
    url = f"{CHIRPS_BASE_URL}/{filename}"
    gz_path = cache_path.with_suffix(".tif.gz")

    logger.info("Downloading CHIRPS: {}", url)
    _download_resumable(url, gz_path)

    # Decompress
    logger.debug("Decompressing {}", gz_path.name)
    try:
        with gzip.open(str(gz_path), "rb") as f_in, open(str(cache_path), "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        # Integrity: the decompressed file must open as a valid raster.
        with rasterio.open(str(cache_path)):
            pass
    except Exception as e:
        cache_path.unlink(missing_ok=True)
        gz_path.unlink(missing_ok=True)
        raise RuntimeError(f"Corrupt CHIRPS download for {year}-{month:02d}: {e}")
    finally:
        gz_path.unlink(missing_ok=True)

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
