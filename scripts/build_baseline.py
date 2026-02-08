"""One-time script: compute multi-year monthly baselines from historical imagery.

Usage:
    python scripts/build_baseline.py --years 5 --indices ndmi,nbr,evi2
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click
from loguru import logger

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import AOI_BBOX, BASELINES_DIR, BASELINE_YEARS, MAX_CLOUD_COVER
from src.acquisition.stac_client import search_element84
from src.acquisition.download import load_sentinel2_for_indices
from src.detection.baseline import build_baselines
from src.processing.cloud_mask import mask_sentinel2
from src.processing.indices import compute_all_indices


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
def main(years: int, indices: str, output_dir: str, max_cloud: int) -> None:
    """Build monthly baselines from historical Sentinel-2 imagery."""
    index_list = [idx.strip() for idx in indices.split(",")]
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    logger.info("Building baselines for indices: {}", index_list)
    logger.info("Using {} years of history", years)

    # Compute date range
    now = datetime.utcnow()
    start_year = now.year - years
    datetime_range = f"{start_year}-01-01/{now.strftime('%Y-%m-%d')}"

    logger.info("Querying imagery from {}", datetime_range)

    # Search for imagery
    items = search_element84(
        bbox=AOI_BBOX,
        datetime_range=datetime_range,
        max_cloud_cover=max_cloud,
        max_items=500,
    )

    if len(items) == 0:
        logger.error("No imagery found for the specified parameters")
        sys.exit(1)

    logger.info("Found {} scenes, processing...", len(items))

    # Process each scene
    all_index_arrays: dict[str, list] = {idx: [] for idx in index_list}
    all_dates: dict[str, list] = {idx: [] for idx in index_list}

    for i, item in enumerate(items):
        logger.info("Processing scene {}/{}: {}", i + 1, len(items), item.id)

        try:
            # Load bands
            ds = load_sentinel2_for_indices(item, index_list)

            # Apply cloud mask
            ds = mask_sentinel2(ds)

            # Compute indices
            idx_ds = compute_all_indices(ds, index_list, sensor="sentinel2")

            date_str = str(item.datetime)[:10]

            for idx_name in index_list:
                if idx_name in idx_ds:
                    all_index_arrays[idx_name].append(idx_ds[idx_name])
                    all_dates[idx_name].append(date_str)

        except Exception as e:
            logger.warning("Failed to process {}: {}", item.id, e)
            continue

    # Build baselines for each index
    for idx_name in index_list:
        arrays = all_index_arrays[idx_name]
        dates = all_dates[idx_name]

        if not arrays:
            logger.warning("No valid data for {}, skipping baseline", idx_name)
            continue

        logger.info("Building baselines for {} from {} scenes", idx_name, len(arrays))

        build_baselines(
            index_arrays=arrays,
            dates=dates,
            index_name=idx_name,
            baselines_dir=output_path,
        )

    logger.info("Baseline computation complete. Output: {}", output_path)


if __name__ == "__main__":
    main()
