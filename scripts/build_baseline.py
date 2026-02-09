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
import sys
import time
from datetime import datetime
from pathlib import Path

import click
from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import AOI_BBOX, BASELINES_DIR, BASELINE_YEARS, MAX_CLOUD_COVER


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
    help="Number of years of history to use.",
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
    "--force",
    is_flag=True,
    default=False,
    help="Rebuild all baselines even if they exist on disk.",
)
def main(years: int, indices: str, output_dir: str, max_cloud: int, force: bool) -> None:
    """Build monthly baselines from historical Sentinel-2 imagery."""
    from src.acquisition.download import load_sentinel2_for_indices
    from src.acquisition.stac_client import search_element84
    from src.detection.baseline import build_baselines, save_baseline_cog
    from src.processing.cloud_mask import mask_sentinel2
    from src.processing.composite import monthly_composite
    from src.processing.indices import compute_all_indices

    index_list = [idx.strip() for idx in indices.split(",")]
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    log_path = setup_logging(output_path)

    # ─── Check what still needs to be built ───────────────────────────────
    if force:
        needed = {idx: list(range(1, 13)) for idx in index_list}
        logger.info("Force mode: rebuilding all baselines")
    else:
        needed = check_existing_baselines(index_list, output_path)

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
    logger.info("Using {} years of history, max cloud cover {}%", years, max_cloud)

    # ─── Query imagery ────────────────────────────────────────────────────
    now = datetime.utcnow()
    start_year = now.year - years
    datetime_range = f"{start_year}-01-01/{now.strftime('%Y-%m-%d')}"

    logger.info("Querying imagery from {}", datetime_range)

    items = search_element84(
        bbox=AOI_BBOX,
        datetime_range=datetime_range,
        max_cloud_cover=max_cloud,
        max_items=500,
    )

    if len(items) == 0:
        logger.error("No imagery found for the specified parameters")
        sys.exit(1)

    logger.info("Found {} scenes to process", len(items))

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
            # Load bands ONCE for all indices
            ds = load_sentinel2_for_indices(item, index_list)

            # Apply cloud mask
            ds = mask_sentinel2(ds)

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
    for idx_name in index_list:
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

            try:
                import numpy as np
                import xarray as xr

                stacked = xr.concat(arrays, dim="time", join="outer")
                mean_arr = stacked.mean(dim="time", skipna=True)
                std_arr = stacked.std(dim="time", skipna=True)

                mean_path = output_path / f"{idx_name}_month{month:02d}_mean.tif"
                std_path = output_path / f"{idx_name}_month{month:02d}_std.tif"

                save_baseline_cog(mean_arr, mean_path)
                save_baseline_cog(std_arr, std_path)

                built_count += 1
                logger.info(
                    "Built {}_month{:02d} ({}/{})",
                    idx_name, month, built_count, total_needed,
                )

                # Free memory after saving
                del stacked, mean_arr, std_arr, arrays
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
