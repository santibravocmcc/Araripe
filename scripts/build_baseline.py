"""One-time script: compute multi-year monthly baselines from historical imagery.

Features:
    - File logging to logs/build_baseline_YYYYMMDD_HHMMSS.log
    - Resumability: skips months/indices that already have COGs on disk
    - Single-pass: loads bands once, computes ALL indices per scene
    - Progress tracking with scene count and ETA

Usage:
    python scripts/build_baseline.py --years 5 --indices ndmi,nbr,evi2
    python scripts/build_baseline.py --years 3 --indices nbr,evi2   # resume after ndmi done
"""

from __future__ import annotations

import concurrent.futures
import gc
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# ─── GDAL/CURL resilience for COG streaming over flaky networks ───────────────
# Set BEFORE rasterio/GDAL initialises. These make a stalled HTTP read fail
# (and retry) instead of hanging indefinitely — the core fix for the S3
# throttling that blocked earlier rebuilds. Values are overridable from the
# environment (setdefault), so the launcher can tune them.
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "60")          # per-request wall clock
os.environ.setdefault("GDAL_HTTP_CONNECTTIMEOUT", "20")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "3")
os.environ.setdefault("GDAL_HTTP_MULTIPLEX", "YES")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("VSI_CACHE_SIZE", "268435456")      # 256 MB
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF,.jp2")

import click
from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _SkipScene(Exception):
    """Raised for a legitimate skip (too cloudy / no AOI overlap) — not retried."""


_SCENE_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None


def _run_with_timeout(fn, timeout: float):
    """Run *fn* in a worker thread, raising TimeoutError if it exceeds *timeout*.

    On timeout the worker thread is abandoned (a stalled GDAL read cannot be
    killed from Python), and the executor is recreated so the next scene gets a
    fresh worker instead of queueing behind the hung one. The abandoned thread
    should die on its own once GDAL_HTTP_TIMEOUT trips.
    """
    global _SCENE_EXECUTOR
    if _SCENE_EXECUTOR is None:
        _SCENE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = _SCENE_EXECUTOR.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        try:
            _SCENE_EXECUTOR.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        _SCENE_EXECUTOR = None
        raise TimeoutError(f"scene exceeded {timeout:.0f}s")

from config.settings import (
    AOI_BBOX,
    BASELINES_DIR,
    BASELINE_YEARS,
    CAATINGA_LEAFOFF_MONTHS,
    MAX_CLOUD_COVER,
    MIN_CLEAR_PERCENTAGE_BASELINE,
    SCENE_CACHE_DIR,
    TARGET_CRS,
)

BASELINE_RESOLUTION = 20.0  # metres — matches load_sentinel2_for_indices default


def setup_logging(output_dir: Path) -> Path:
    """Configure loguru to write to both console and a log file.

    Returns the path to the log file.
    """
    logs_dir = output_dir.parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"build_baseline_{timestamp}.log"

    # Remove default handler and re-add with custom format
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    )
    logger.add(
        str(log_path),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation="100 MB",
    )

    logger.info("Log file: {}", log_path)
    return log_path


def free_gb(path: Path) -> float:
    """Free disk space (GB) on the filesystem containing *path*."""
    try:
        return shutil.disk_usage(str(path)).free / 1e9
    except Exception:
        return float("inf")


def build_template(aoi_gdf, resolution: float, crs: str):
    """A fixed AOI-covering grid (NaN-filled) in *crs* at *resolution* metres.

    Every scene's index array is reproject_match'd onto this common grid before
    compositing. Without a common grid, xr.concat(join="outer") on per-scene
    reprojected arrays (each landing on a slightly different origin) fragments
    coverage — the cause of the near-empty first rebuild attempt.
    """
    import math

    import numpy as np
    import xarray as xr
    from rasterio.transform import from_origin

    aoi = aoi_gdf.to_crs(crs)
    minx, miny, maxx, maxy = aoi.total_bounds
    # Snap bounds to the resolution grid for stable, reproducible pixels.
    minx = math.floor(minx / resolution) * resolution
    maxy = math.ceil(maxy / resolution) * resolution
    maxx = math.ceil(maxx / resolution) * resolution
    miny = math.floor(miny / resolution) * resolution
    width = int(round((maxx - minx) / resolution))
    height = int(round((maxy - miny) / resolution))
    transform = from_origin(minx, maxy, resolution, resolution)
    xs = minx + (np.arange(width) + 0.5) * resolution
    ys = maxy - (np.arange(height) + 0.5) * resolution
    tmpl = xr.DataArray(
        np.full((height, width), np.nan, dtype="float32"),
        dims=("y", "x"), coords={"y": ys, "x": xs},
    )
    tmpl.rio.write_crs(crs, inplace=True)
    tmpl.rio.write_transform(transform, inplace=True)
    tmpl.rio.write_nodata(np.nan, inplace=True)
    logger.info("Common template grid: {}x{} px @ {} m in {}", width, height, resolution, crs)
    return tmpl


def check_existing_baselines(
    index_list: list[str],
    baselines_dir: Path,
) -> dict[str, list[int]]:
    """Check which monthly baselines already exist on disk.

    Returns a dict mapping index_name → list of months still needed.
    """
    needed = {}
    for idx_name in index_list:
        missing_months = []
        for month in range(1, 13):
            mean_path = baselines_dir / f"{idx_name}_month{month:02d}_mean.tif"
            std_path = baselines_dir / f"{idx_name}_month{month:02d}_std.tif"
            if not mean_path.exists() or not std_path.exists():
                missing_months.append(month)
        needed[idx_name] = missing_months

    return needed


@click.command()
@click.option(
    "--years",
    default=BASELINE_YEARS,
    help="Number of years of history to use (only if --year-set is not given).",
)
@click.option(
    "--year-set",
    default="",
    help="Explicit comma-separated calendar years to pool into the baseline "
         "(e.g. '2017,2019,2021,2022,2025'). Overrides --years. Each year is "
         "queried separately to avoid the 500-item cap and to skip excluded years.",
)
@click.option(
    "--months",
    default="",
    help="Comma-separated months (1-12) to build. Empty = all needed months. "
         "Useful for memory-bounded, one-month-at-a-time rebuilds.",
)
@click.option(
    "--min-free-gb",
    default=3.0,
    help="Abort if free disk space drops below this (GB) before a query or write.",
)
@click.option(
    "--reflectance/--no-reflectance",
    default=True,
    help="Convert DN to surface reflectance [0,1] (EVI2 fix). Default True so "
         "rebuilt baselines are in reflectance. After rebuilding, set "
         "REFLECTANCE_SCALING=True in config/settings.py for detection to match.",
)
@click.option(
    "--scene-timeout",
    default=240.0,
    help="Per-scene hard timeout (s). A scene whose streaming stalls beyond this "
         "is abandoned and skipped (resilience against S3 throttling).",
)
@click.option(
    "--scene-retries",
    default=2,
    help="Retries per scene on error/timeout before skipping it.",
)
@click.option(
    "--indices",
    default="ndmi,nbr,evi2",
    help="Comma-separated list of indices to compute.",
)
@click.option(
    "--output-dir",
    default=str(BASELINES_DIR),
    type=click.Path(),
    help="Output directory for baseline COGs.",
)
@click.option(
    "--max-cloud",
    default=MAX_CLOUD_COVER,
    help="Maximum cloud cover percentage.",
)
@click.option(
    "--min-clear",
    default=MIN_CLEAR_PERCENTAGE_BASELINE,
    help="Minimum clear pixel % to include a scene (default 10%).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Rebuild all baselines even if they exist on disk.",
)
@click.option(
    "--cache/--no-cache",
    default=False,
    help="Cache clipped scenes to disk for reuse in future runs.",
)
@click.option(
    "--aoi",
    default=None,
    type=click.Path(exists=False),
    help="Path to AOI polygon (GeoJSON or GeoPackage). Uses default if not set.",
)
def main(
    years: int,
    year_set: str,
    months: str,
    min_free_gb: float,
    reflectance: bool,
    scene_timeout: float,
    scene_retries: int,
    indices: str,
    output_dir: str,
    max_cloud: int,
    min_clear: float,
    force: bool,
    cache: bool,
    aoi: str | None,
) -> None:
    """Build monthly baselines from historical Sentinel-2 imagery."""
    # Force the reflectance scaling for this build so baselines are physically
    # scaled (EVI2 fix). This is set on the settings module *before* load_band
    # is used, so the whole build honours it regardless of the global default.
    import config.settings as _settings
    _settings.REFLECTANCE_SCALING = reflectance
    from src.acquisition.aoi import clip_dataset_to_aoi, get_aoi_bbox_wgs84, load_aoi_polygon
    from src.acquisition.download import load_sentinel2_for_indices
    from src.acquisition.stac_client import search_element84
    from src.detection.baseline import save_baseline_cog
    from src.processing.cloud_mask import compute_clear_percentage, mask_sentinel2
    from src.processing.indices import compute_all_indices

    index_list = [idx.strip() for idx in indices.split(",")]
    requested_months = (
        {int(m) for m in months.split(",") if m.strip()} if months.strip() else None
    )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    log_path = setup_logging(output_path)

    # ─── AOI polygon for clipping ─────────────────────────────────────────
    aoi_path = Path(aoi) if aoi else None
    aoi_gdf = load_aoi_polygon(path=aoi_path)
    aoi_bbox = get_aoi_bbox_wgs84(path=aoi_path)
    logger.info("AOI bbox for STAC query: {}", aoi_bbox)

    # Common grid every scene is snapped to before compositing (fixes coverage
    # fragmentation of the join="outer" concat).
    template = build_template(aoi_gdf, BASELINE_RESOLUTION, TARGET_CRS)

    # ─── Scene cache setup ────────────────────────────────────────────────
    cache_dir = None
    if cache:
        cache_dir = SCENE_CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Scene caching enabled: {}", cache_dir)

    # ─── Check what still needs to be built ───────────────────────────────
    if force:
        needed = {idx: list(range(1, 13)) for idx in index_list}
        logger.info("Force mode: rebuilding all baselines")
    else:
        needed = check_existing_baselines(index_list, output_path)

    # Restrict to explicitly requested months (memory-bounded rebuilds)
    if requested_months is not None:
        needed = {idx: [m for m in months_ if m in requested_months]
                  for idx, months_ in needed.items()}
        logger.info("Restricting to months {}", sorted(requested_months))

    # ─── Disk-space pre-flight ────────────────────────────────────────────
    avail = free_gb(output_path)
    if avail < min_free_gb:
        logger.error(
            "Only {:.1f} GB free at {} (< --min-free-gb {:.1f}). Aborting before "
            "download. Free space or move the existing baselines aside first.",
            avail, output_path, min_free_gb,
        )
        sys.exit(2)
    logger.info("Disk pre-flight OK: {:.1f} GB free (min {:.1f})", avail, min_free_gb)

    # Report what's already done vs what remains
    total_needed = sum(len(months) for months in needed.values())
    total_possible = len(index_list) * 12

    for idx_name, months in needed.items():
        done = 12 - len(months)
        if done > 0:
            logger.info(
                "Index {}: {}/12 months already built, {} remaining (months: {})",
                idx_name, done, len(months), months,
            )
        else:
            logger.info("Index {}: 0/12 months built, starting fresh", idx_name)

    if total_needed == 0:
        logger.info("All baselines already exist! Use --force to rebuild.")
        return

    logger.info(
        "Building {}/{} month-index baselines for indices: {}",
        total_needed, total_possible, index_list,
    )
    # ─── Resolve the set of calendar years to pool ────────────────────────
    if year_set.strip():
        years_list = sorted({int(y) for y in year_set.split(",") if y.strip()})
        logger.info("Explicit year set: {}", years_list)
    else:
        now = datetime.utcnow()
        years_list = list(range(now.year - years, now.year + 1))
        logger.info("Using {} years of history: {}", years, years_list)
    logger.info("Max cloud cover {}%", max_cloud)

    # ─── Query imagery (one query PER YEAR) ───────────────────────────────
    # Per-year querying avoids the 500-item truncation of a single multi-year
    # query and lets a discrete, non-contiguous year set (e.g. skipping the
    # El-Nino years 2023/2024) be expressed directly.
    items = []
    for yr in years_list:
        yr_items = search_element84(
            bbox=aoi_bbox,
            datetime_range=f"{yr}-01-01/{yr}-12-31",
            max_cloud_cover=max_cloud,
            max_items=500,
        )
        yr_items = list(yr_items)
        logger.info("Year {}: {} scenes", yr, len(yr_items))
        items.extend(yr_items)

    if len(items) == 0:
        logger.error("No imagery found for the specified parameters")
        sys.exit(1)

    logger.info("Found {} scenes across {} years to process", len(items), len(years_list))

    # ─── Single pass: stream each scene, fold into running mean/std ───────
    # Memory-bounded compositing (Welford) on the common template grid: one
    # scene is materialized at a time and folded in, so peak memory is ~the
    # accumulators (a few GB) rather than every scene at once. A true median
    # would need all scenes resident (>20 GB/month at full AOI on this RAM) —
    # tiled-median is a roadmap refinement (see ROADMAP.md). All baselines are
    # replaced together, so the reflectance set is internally consistent (mean).
    import numpy as np
    import xarray as xr

    tmpl_shape = (template.sizes["y"], template.sizes["x"])
    # acc[(idx, month)] = {"count": int32, "mean": float32, "M2": float32}
    acc: dict[tuple[str, int], dict] = {}

    def _fold(key, x):
        a = acc.get(key)
        if a is None:
            a = {
                "count": np.zeros(tmpl_shape, dtype=np.int32),
                "mean": np.zeros(tmpl_shape, dtype=np.float32),
                "M2": np.zeros(tmpl_shape, dtype=np.float32),
            }
            acc[key] = a
        v = np.isfinite(x)
        if not v.any():
            return
        c = a["count"]; mean = a["mean"]; m2 = a["M2"]
        c[v] += 1
        delta = x[v] - mean[v]
        mean[v] += delta / c[v]
        m2[v] += delta * (x[v] - mean[v])

    def _load_scene(item, cache_file):
        """Stream+mask+clip a scene and return a dict {idx_name: computed array}.

        Raises _SkipScene for legitimate skips (too cloudy / no overlap). All
        network/materialization work happens here so it can run under a timeout.
        """
        if cache_file and cache_file.exists():
            logger.info("Cache hit: loading {} from disk", cache_file.name)
            ds = xr.open_dataset(str(cache_file))
        else:
            ds = load_sentinel2_for_indices(item, index_list)
            ds = mask_sentinel2(ds)
            try:
                ds = clip_dataset_to_aoi(ds, aoi_gdf=aoi_gdf)
            except Exception as clip_err:
                raise _SkipScene(f"no AOI overlap ({clip_err})")
            if cache_file:
                try:
                    ds_computed = ds.compute()
                    ds_computed.to_netcdf(str(cache_file))
                    ds = ds_computed
                except Exception as cache_err:
                    logger.warning("Failed to cache {}: {}", item.id, cache_err)

        clear_pct = compute_clear_percentage(ds)
        if clear_pct < min_clear:
            raise _SkipScene(f"only {clear_pct:.1f}% clear (< {min_clear}%)")

        idx_ds = compute_all_indices(ds, index_list, sensor="sentinel2")
        # Snap each index to the common template grid so all scenes share
        # identical coordinates (clean concat/median with full coverage), then
        # materialize (forces the streamed reads to complete inside the
        # timeout-guarded worker).
        out = {}
        for idx_name in index_list:
            if idx_name in idx_ds and scene_month_ref[0] in needed[idx_name]:
                arr = idx_ds[idx_name]
                if arr.rio.crs is None:
                    arr = arr.rio.write_crs(TARGET_CRS)
                # Materialize and declare nodata=NaN BEFORE reproject_match:
                # otherwise it fills the (large) out-of-footprint region of the
                # template with 0 instead of NaN, which Welford then folds as
                # real zeros and collapses the composite.
                arr = arr.compute()
                arr.rio.write_nodata(np.nan, inplace=True)
                arr = arr.rio.reproject_match(template)
                out[idx_name] = arr.compute()
        del ds, idx_ds
        gc.collect()
        return out

    scene_times = []
    scene_month_ref = [0]  # mutable holder so the closure sees the current month
    n_ok = n_skip = n_fail = 0
    for i, item in enumerate(items):
        scene_start = time.time()
        scene_date = str(item.datetime)[:10]
        scene_month = int(scene_date[5:7])
        scene_month_ref[0] = scene_month

        # Skip scene if no index needs this month (fast, no network)
        if not any(scene_month in needed[idx_name] for idx_name in index_list):
            continue

        logger.info(
            "Processing scene {}/{}: {} (month {})",
            i + 1, len(items), item.id, scene_month,
        )

        cache_file = cache_dir / f"{item.id.replace('/', '_')}.nc" if cache_dir else None

        scene_arrays = None
        for attempt in range(scene_retries + 1):
            try:
                scene_arrays = _run_with_timeout(
                    lambda: _load_scene(item, cache_file), scene_timeout
                )
                break
            except _SkipScene as sk:
                logger.info("Scene {}: skipping — {}", item.id, sk)
                n_skip += 1
                scene_arrays = None
                break
            except Exception as e:
                if attempt < scene_retries:
                    delay = 5 * (attempt + 1)
                    logger.warning(
                        "Scene {} attempt {}/{} failed ({}); retrying in {}s",
                        item.id, attempt + 1, scene_retries + 1, e, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.warning(
                        "Scene {} SKIPPED after {} attempts ({})",
                        item.id, scene_retries + 1, e,
                    )
                    n_fail += 1
                    scene_arrays = None

        if not scene_arrays:
            continue

        for idx_name, arr in scene_arrays.items():
            _fold((idx_name, scene_month), np.asarray(arr.values, dtype=np.float32))
        del scene_arrays
        gc.collect()
        n_ok += 1

        elapsed = time.time() - scene_start
        scene_times.append(elapsed)
        avg_time = sum(scene_times) / len(scene_times)
        logger.info(
            "Scene done in {:.0f}s | ok={} skip={} fail={} | avg {:.0f}s/scene",
            elapsed, n_ok, n_skip, n_fail, avg_time,
        )

    logger.info("Scene loading: {} used, {} skipped (cloud/overlap), {} failed after retries",
                n_ok, n_skip, n_fail)

    # ─── Build composites and save ────────────────────────────────────────
    logger.info("=== Scene loading complete. Building monthly composites... ===")

    built_count = 0
    stop_writing = False
    for idx_name in index_list:
        if stop_writing:
            break
        for month in needed[idx_name]:
            key = (idx_name, month)
            a = acc.get(key)
            if a is None or int(a["count"].max()) == 0:
                logger.warning("No data for {} month {}, skipping", idx_name, month)
                continue

            max_obs = int(a["count"].max())
            cov = 100.0 * float((a["count"] > 0).mean())
            logger.info(
                "Building {}_month{:02d}: up to {} obs/pixel, {:.1f}% AOI covered",
                idx_name, month, max_obs, cov,
            )

            if month in CAATINGA_LEAFOFF_MONTHS:
                logger.warning(
                    "Month {} baselines may be less reliable for deciduous "
                    "Caatinga (leaf-off period, Aug-Oct).", month,
                )

            avail = free_gb(output_path)
            if avail < min_free_gb:
                logger.error(
                    "Only {:.1f} GB free (< --min-free-gb {:.1f}); stopping before "
                    "writing {}_month{:02d}. {} baselines written so far.",
                    avail, min_free_gb, idx_name, month, built_count,
                )
                stop_writing = True
                break

            try:
                count = a["count"]
                mean = a["mean"]
                m2 = a["M2"]
                out_mean = np.where(count > 0, mean, np.nan).astype("float32")
                # Population std (ddof=0), matching build_baseline_from_downloads;
                # NaN where fewer than 2 observations.
                with np.errstate(invalid="ignore", divide="ignore"):
                    std = np.sqrt(m2 / np.where(count > 0, count, 1))
                out_std = np.where(count >= 2, std, np.nan).astype("float32")

                mean_da = template.copy(data=out_mean)
                std_da = template.copy(data=out_std)
                mean_path = output_path / f"{idx_name}_month{month:02d}_mean.tif"
                std_path = output_path / f"{idx_name}_month{month:02d}_std.tif"
                save_baseline_cog(mean_da, mean_path)
                save_baseline_cog(std_da, std_path)

                built_count += 1
                logger.info("Built {}_month{:02d} ({}/{})",
                            idx_name, month, built_count, total_needed)

                del out_mean, out_std, std, mean_da, std_da
                acc.pop(key, None)
                gc.collect()

            except Exception as e:
                logger.error("Failed to build {}_month{:02d}: {}", idx_name, month, e)
                continue

    # ─── Summary ──────────────────────────────────────────────────────────
    logger.info("=== Baseline computation complete ===")
    logger.info("Built {}/{} month-index baselines", built_count, total_needed)
    logger.info("Output directory: {}", output_path)
    logger.info("Log file: {}", log_path)

    # List what's now on disk
    existing = sorted(output_path.glob("*.tif"))
    logger.info("Total COG files on disk: {}", len(existing))
    for f in existing:
        logger.debug("  {}", f.name)


if __name__ == "__main__":
    main()
