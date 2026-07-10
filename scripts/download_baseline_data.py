#!/usr/bin/env python3
"""Robust, resumable downloader for the CHIRPS climate baseline.

Why this exists
---------------
The original CHIRPS fetch (src/acquisition/chirps.py) used a bare
`urllib.request.urlretrieve` with no timeout, no retry, no resume and no
integrity check. On a flaky connection that fails silently or hangs, and every
restart begins from zero — the instability reported by the team. It also stored
the full ~57 MB global raster per month, so building a multi-year rainfall
normal (needed to pick low-anomaly baseline years, see select_baseline_years.py)
could accumulate many gigabytes on a machine with only 15–20 GB free.

What this script does
---------------------
For each requested (year, month) it:
  1. Streams the gzipped global CHIRPS file in chunks with an HTTP **Range**
     header so an interrupted download **resumes** from the byte it stopped at
     (the UCSB server advertises `Accept-Ranges: bytes`).
  2. Retries on network/5xx/timeout errors with **exponential backoff + jitter**.
  3. Verifies **integrity**: the finished `.gz` must match the server
     `Content-Length`, and it must gunzip + open as a valid raster (else it is
     discarded and re-fetched).
  4. Processes **incrementally**: it crops the global raster to the AOI window
     (a few KB), appends the AOI-mean precipitation to a CSV, and then — unless
     `--keep-global` — **deletes the big global file immediately**, so peak disk
     use stays at one file, never the whole archive.
  5. Guards **free disk space** before each download and aborts cleanly if below
     `--min-free-gb`.
  6. Logs clear progress and errors to console and to logs/download_baseline_*.log.

Optional OneDrive sink (`--onedrive-dir`) is documented in ONEDRIVE_NOTES below;
it needs external credentials and is therefore left as a clearly-marked opt-in.

Usage
-----
    # Download 2017–2025 (all months), cropping + deleting globals as it goes:
    python scripts/download_baseline_data.py --start 2017-01 --end 2025-12

    # Keep the full global rasters too (needs more disk):
    python scripts/download_baseline_data.py --start 2024-01 --end 2024-12 --keep-global

    # Just (re)build the AOI-mean CSV from files already in data/chirps/:
    python scripts/download_baseline_data.py --start 2021-01 --end 2025-12 --no-download
"""

from __future__ import annotations

import gzip
import random
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import click
import numpy as np
import rasterio
import requests
from loguru import logger
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import AOI_BBOX, CHIRPS_BASE_URL, CHIRPS_CACHE_DIR

AOI_DIR = CHIRPS_CACHE_DIR.parent / "chirps_aoi"
CSV_PATH = AOI_DIR / "chirps_aoi_monthly.csv"
CHUNK = 1 << 20  # 1 MiB

ONEDRIVE_NOTES = """
OneDrive as an intermediate sink (optional, needs external setup):
  1. Register an app in Azure AD (portal.azure.com → App registrations) and grant
     the delegated Microsoft Graph scope `Files.ReadWrite`.
  2. Authenticate with the OAuth 2.0 device-code flow (library: `msal`) to obtain
     an access token without embedding a secret.
  3. Upload each cropped file with a Graph upload session:
       PUT https://graph.microsoft.com/v1.0/me/drive/root:/<path>:/content
     (use an upload session for files > 4 MB).
  Alternatively, configure `rclone` with a `onedrive:` remote and run
     rclone copy data/chirps_aoi onedrive:araripe/chirps_aoi
  after this script finishes. Because it requires interactive tenant consent,
  this path is intentionally left as a manual/opt-in step rather than automated.
"""


def month_range(start: str, end: str):
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


def download_resumable(url: str, dest: Path, retries: int = 6, timeout: int = 60) -> Path:
    """Download `url` to `dest` with Range-resume and exponential backoff.

    Returns the path on success; raises RuntimeError after exhausting retries.
    """
    part = dest.with_suffix(dest.suffix + ".part")
    # Expected total size (for integrity + resume math).
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
                if have and r.status_code == 200:
                    # Server ignored Range → restart from scratch.
                    have = 0
                    part.unlink(missing_ok=True)
                elif have and r.status_code == 416:
                    # Already have the whole file.
                    break
                r.raise_for_status()
                mode = "ab" if have else "wb"
                with open(part, mode) as f:
                    for chunk in r.iter_content(CHUNK):
                        if chunk:
                            f.write(chunk)
            got = part.stat().st_size
            if total is None or got >= total:
                break
            logger.warning("Short read ({}/{} bytes), resuming (attempt {}/{})",
                           got, total, attempt, retries)
        except (requests.RequestException, OSError) as e:
            wait = min(60, 2 ** attempt) + random.uniform(0, 1.5)
            logger.warning("Download error ({}); retry {}/{} in {:.1f}s",
                           e, attempt, retries, wait)
            time.sleep(wait)
    else:
        raise RuntimeError(f"Failed to download {url} after {retries} attempts")

    if total is not None and part.stat().st_size != total:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Size mismatch for {url}: got {part.stat().st_size}, expected {total}")
    part.replace(dest)
    return dest


def gunzip(gz_path: Path, out_path: Path) -> Path:
    with gzip.open(gz_path, "rb") as fi, open(out_path, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    return out_path


def crop_aoi(global_tif: Path, out_tif: Path, bbox) -> float:
    """Crop the global raster to `bbox`, save a tiny GeoTIFF, return AOI-mean (mm)."""
    with rasterio.open(global_tif) as src:
        win = from_bounds(*bbox, src.transform)
        data = src.read(1, window=win)
        transform = src.window_transform(win)
        prof = src.profile.copy()
        prof.update(width=data.shape[1], height=data.shape[0], transform=transform,
                    compress="deflate", tiled=True, blockxsize=256, blockysize=256)
        out_tif.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_tif, "w", **prof) as dst:
            dst.write(data, 1)
    a = np.where(data < 0, np.nan, data.astype("float64"))
    return float(np.nanmean(a))


@click.command()
@click.option("--start", required=True, help="First month, YYYY-MM.")
@click.option("--end", required=True, help="Last month, YYYY-MM.")
@click.option("--keep-global/--drop-global", default=False,
              help="Keep the ~57 MB global rasters (default: delete after cropping).")
@click.option("--no-download", is_flag=True, help="Skip downloading; only (re)crop local globals.")
@click.option("--min-free-gb", default=2.0, type=float, help="Abort if free disk < this.")
@click.option("--onedrive-dir", default=None, help="(Opt-in) copy cropped files here; see ONEDRIVE_NOTES.")
def main(start, end, keep_global, no_download, min_free_gb, onedrive_dir):
    """Robustly download + crop CHIRPS monthly precipitation for the AOI."""
    CHIRPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    AOI_DIR.mkdir(parents=True, exist_ok=True)
    logs = Path("logs"); logs.mkdir(exist_ok=True)
    logger.add(str(logs / f"download_baseline_{datetime.utcnow():%Y%m%d_%H%M%S}.log"), level="DEBUG")

    rows = []
    for y, m in month_range(start, end):
        gtif = CHIRPS_CACHE_DIR / f"chirps-v2.0.{y}.{m:02d}.tif"
        atif = AOI_DIR / f"chirps-v2.0.{y}.{m:02d}.aoi.tif"
        try:
            if not gtif.exists() and not no_download:
                if free_gb(CHIRPS_CACHE_DIR) < min_free_gb:
                    logger.error("Free disk {:.1f} GB < {:.1f} GB — aborting.",
                                 free_gb(CHIRPS_CACHE_DIR), min_free_gb)
                    sys.exit(2)
                url = f"{CHIRPS_BASE_URL}/chirps-v2.0.{y}.{m:02d}.tif.gz"
                gz = gtif.with_suffix(".tif.gz")
                logger.info("[{}-{:02d}] downloading {}", y, m, url)
                download_resumable(url, gz)
                gunzip(gz, gtif)
                gz.unlink(missing_ok=True)
                # Integrity: must open as a valid raster.
                with rasterio.open(gtif) as _:
                    pass
                logger.info("[{}-{:02d}] downloaded + verified", y, m)
            if not gtif.exists():
                logger.warning("[{}-{:02d}] no global file and --no-download; skipping", y, m)
                continue
            mean_mm = crop_aoi(gtif, atif, AOI_BBOX)
            rows.append((y, m, round(mean_mm, 2)))
            logger.info("[{}-{:02d}] AOI-mean precip = {:.1f} mm → {}", y, m, mean_mm, atif.name)
            if onedrive_dir:
                dst = Path(onedrive_dir) / atif.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(atif, dst)
            if not keep_global:
                gtif.unlink(missing_ok=True)  # incremental: never accumulate globals
        except Exception as e:
            logger.error("[{}-{:02d}] FAILED: {}", y, m, e)
            continue

    # Append/refresh the AOI CSV.
    if rows:
        header = "year,month,aoi_mean_precip_mm\n"
        existing = CSV_PATH.read_text() if CSV_PATH.exists() else header
        lines = {ln for ln in existing.splitlines() if ln and not ln.startswith("year")}
        for y, m, v in rows:
            lines.add(f"{y},{m},{v}")
        CSV_PATH.write_text(header + "\n".join(sorted(lines)) + "\n")
        logger.info("Wrote {} ({} months total)", CSV_PATH, len(lines))
    logger.info("Done. Peak disk kept to one global file at a time (keep_global={}).", keep_global)
    if onedrive_dir:
        logger.info(ONEDRIVE_NOTES)


if __name__ == "__main__":
    main()
