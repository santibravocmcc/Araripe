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

import gc
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import click
from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    AOI_BBOX,
    BASELINES_DIR,
    BASELINE_YEARS,
    CAATINGA_LEAFOFF_MONTHS,
    MAX_CLOUD_COVER,
    MIN_CLEAR_PERCENTAGE_BASELINE,
    SCENE_CACHE_DIR,
)


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
    from src.processing.composite import median_composite, std_composite
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

    # ─── Single pass: load bands once, compute ALL indices per scene ──────
    # Store index arrays grouped by (index_name, month) for direct compositing
    arrays_by_idx_month: dict[tuple[str, int], list] = {}

    scene_times = []
    for i, item in enumerate(items):
        scene_start = time.time()
        scene_date = str(item.datetime)[:10]
        scene_month = int(scene_date[5:7])

        logger.info(
            "Processing scene {}/{}: {} (month {})",
            i + 1, len(items), item.id, scene_month,
        )

        # Skip scene if no index needs this month
        month_needed_by_any = False
        for idx_name in index_list:
            if scene_month in needed[idx_name]:
                month_needed_by_any = True
                break

        if not month_needed_by_any:
            logger.debug("Month {} not needed by any index, skipping scene", scene_month)
            continue

        try:
            # ─── Try loading from cache first ─────────────────────────
            import xarray as xr

            cache_file = cache_dir / f"{item.id.replace('/', '_')}.nc" if cache_dir else None
            loaded_from_cache = False

            if cache_file and cache_file.exists():
                logger.info("Cache hit: loading {} from disk", cache_file.name)
                ds = xr.open_dataset(str(cache_file))
                loaded_from_cache = True
            else:
                # Load bands ONCE for all indices (streams from cloud)
                ds = load_sentinel2_for_indices(item, index_list)

                # Apply cloud mask
                ds = mask_sentinel2(ds)

                # Clip to AOI polygon (reduces data size dramatically)
                try:
                    ds = clip_dataset_to_aoi(ds, aoi_gdf=aoi_gdf)
                except Exception as clip_err:
                    logger.warning("Clipping failed for {}: {}, using unclipped", item.id, clip_err)

                # Save clipped scene to cache for future reuse
                if cache_file:
                    try:
                        ds_computed = ds.compute()
                        ds_computed.to_netcdf(str(cache_file))
                        logger.info("Cached clipped scene: {} ({:.1f} MB)",
                                    cache_file.name, cache_file.stat().st_size / 1e6)
                        ds = ds_computed
                    except Exception as cache_err:
                        logger.warning("Failed to cache {}: {}", item.id, cache_err)

            # Skip scenes with too few clear pixels
            clear_pct = compute_clear_percentage(ds)
            if clear_pct < min_clear:
                logger.info(
                    "Scene {}: only {:.1f}% clear, skipping (threshold: {}%)",
                    item.id, clear_pct, min_clear,
                )
                continue

            # Compute ALL indices from the same loaded bands
            idx_ds = compute_all_indices(ds, index_list, sensor="sentinel2")

            # Store each index result keyed by (index, month)
            for idx_name in index_list:
                if idx_name in idx_ds and scene_month in needed[idx_name]:
                    key = (idx_name, scene_month)
                    if key not in arrays_by_idx_month:
                        arrays_by_idx_month[key] = []
                    # Compute immediately to release dask graph and free memory
                    arrays_by_idx_month[key].append(idx_ds[idx_name].compute())

            # Free memory
            del ds, idx_ds
            gc.collect()

        except Exception as e:
            logger.warning("Failed to process {}: {}", item.id, e)
            continue

        elapsed = time.time() - scene_start
        scene_times.append(elapsed)

        # ETA calculation
        avg_time = sum(scene_times) / len(scene_times)
        remaining = len(items) - (i + 1)
        eta_seconds = avg_time * remaining
        eta_hours = eta_seconds / 3600

        logger.info(
            "Scene done in {:.0f}s | Avg {:.0f}s/scene | ~{:.1f}h remaining for scene loading",
            elapsed, avg_time, eta_hours,
        )

    # ─── Build composites and save ────────────────────────────────────────
    logger.info("=== Scene loading complete. Building monthly composites... ===")

    built_count = 0
    stop_writing = False
    for idx_name in index_list:
        if stop_writing:
            break
        for month in needed[idx_name]:
            key = (idx_name, month)
            if key not in arrays_by_idx_month or not arrays_by_idx_month[key]:
                logger.warning("No data for {} month {}, skipping", idx_name, month)
                continue

            arrays = arrays_by_idx_month[key]
            n_scenes = len(arrays)
            logger.info(
                "Building {}_month{:02d} from {} scenes...",
                idx_name, month, n_scenes,
            )

            # Seasonal quality warning for Caatinga leaf-off months
            if month in CAATINGA_LEAFOFF_MONTHS:
                logger.warning(
                    "Month {} baselines may be less reliable for deciduous "
                    "Caatinga (leaf-off period, Aug-Oct). Greenness indices "
                    "(NDVI, EVI2) are especially affected.",
                    month,
                )

            # Disk guard before writing each month-index pair
            avail = free_gb(output_path)
            if avail < min_free_gb:
                logger.error(
                    "Only {:.1f} GB free (< --min-free-gb {:.1f}); stopping before "
                    "writing {}_month{:02d}. {} baselines were written so far.",
                    avail, min_free_gb, idx_name, month, built_count,
                )
                stop_writing = True
                break

            try:
                # Central statistic is the MEDIAN (robust to residual cloud /
                # outliers), matching build_baseline_from_downloads.py and
                # composite.monthly_composite. The output suffix stays "_mean"
                # for backward compatibility with load_baseline_pair.
                center_arr = median_composite(arrays)
                std_arr = std_composite(arrays)

                mean_path = output_path / f"{idx_name}_month{month:02d}_mean.tif"
                std_path = output_path / f"{idx_name}_month{month:02d}_std.tif"

                save_baseline_cog(center_arr, mean_path)
                save_baseline_cog(std_arr, std_path)

                built_count += 1
                logger.info(
                    "Built {}_month{:02d} ({}/{})",
                    idx_name, month, built_count, total_needed,
                )

                # Free memory after saving
                del center_arr, std_arr, arrays
                arrays_by_idx_month[key] = []
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
