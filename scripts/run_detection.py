"""Weekly detection script: find recent imagery, detect changes, generate alerts.

This script is designed to run in GitHub Actions on a weekly schedule.

Usage:
    python scripts/run_detection.py
    python scripts/run_detection.py --days-back 30 --indices ndmi,nbr
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    ALERTS_DIR,
    AOI_BBOX,
    BASELINES_DIR,
    MAX_CLOUD_COVER,
    SCENE_CACHE_DIR,
    SEARCH_DAYS_BACK,
)
from src.acquisition.aoi import clip_dataset_to_aoi, get_aoi_bbox_wgs84, load_aoi_polygon
from src.acquisition.stac_client import search_sentinel2_with_fallback
from src.acquisition.download import load_sentinel2_for_indices
from src.detection.alerts import save_alerts, summarize_alerts, vectorize_alerts
from src.detection.baseline import load_baseline_pair
from src.detection.change_detect import detect_deforestation
from src.processing.cloud_mask import compute_clear_percentage, mask_sentinel2
from src.processing.indices import compute_all_indices
from src.timeseries.builder import store_alert_stats, store_regional_stats


@click.command()
@click.option("--days-back", default=SEARCH_DAYS_BACK, help="Days to look back.")
@click.option("--indices", default="ndmi,nbr,evi2", help="Comma-separated indices.")
@click.option("--max-cloud", default=MAX_CLOUD_COVER, help="Max cloud cover %.")
@click.option("--min-clear", default=50.0, help="Min clear pixel % to process scene.")
@click.option(
    "--cache/--no-cache",
    default=False,
    help="Cache clipped scenes to disk for reuse.",
)
@click.option(
    "--aoi",
    default=None,
    type=click.Path(exists=False),
    help="Path to AOI polygon (GeoJSON or GeoPackage).",
)
def main(
    days_back: int,
    indices: str,
    max_cloud: int,
    min_clear: float,
    cache: bool,
    aoi: str | None,
) -> None:
    """Run the weekly deforestation detection pipeline."""
    index_list = [idx.strip() for idx in indices.split(",")]
    today = datetime.utcnow().strftime("%Y-%m-%d")
    current_month = datetime.utcnow().month

    logger.info("=== Araripe Deforestation Detection ===")
    logger.info("Date: {}, Looking back {} days", today, days_back)
    logger.info("Indices: {}", index_list)

    # ─── AOI polygon for clipping ─────────────────────────────────────────
    aoi_path = Path(aoi) if aoi else None
    aoi_gdf = load_aoi_polygon(path=aoi_path)
    aoi_bbox = get_aoi_bbox_wgs84(path=aoi_path)
    logger.info("AOI bbox: {}", aoi_bbox)

    # ─── Scene cache setup ────────────────────────────────────────────────
    cache_dir = None
    if cache:
        cache_dir = SCENE_CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Scene caching enabled: {}", cache_dir)

    # Fetch current drought status via CHIRPS/SPI
    spi_value = None
    try:
        from src.processing.spi import get_current_spi

        spi_value = get_current_spi(aoi_bbox)
        logger.info("Current 3-month SPI: {:.2f}", spi_value)
        if spi_value < -1.0:
            logger.warning(
                "Drought conditions detected (SPI={:.2f}). "
                "Z-score thresholds will be widened to reduce false positives.",
                spi_value,
            )
    except Exception as e:
        logger.warning("Could not compute SPI (CHIRPS unavailable): {}. Proceeding without drought adjustment.", e)

    # Stage 1: Query recent imagery
    logger.info("Stage 1: Querying recent imagery...")
    items = search_sentinel2_with_fallback(
        bbox=aoi_bbox,
        max_cloud_cover=max_cloud,
    )

    if len(items) == 0:
        logger.warning("No cloud-free imagery found. Exiting.")
        return

    logger.info("Found {} candidate scenes", len(items))

    # Sort by cloud cover (process clearest first)
    items_sorted = sorted(
        items,
        key=lambda x: x.properties.get("eo:cloud_cover", 100),
    )

    # Stage 2-5: Process scenes
    all_alerts = []

    for item in items_sorted[:5]:  # Process up to 5 best scenes
        scene_date = str(item.datetime)[:10]
        cloud_pct = item.properties.get("eo:cloud_cover", "?")
        logger.info("Processing {} (cloud: {}%)", item.id, cloud_pct)

        try:
            # Stage 2: Load, mask, and clip to AOI
            import xarray as xr

            cache_file = cache_dir / f"{item.id.replace('/', '_')}.nc" if cache_dir else None

            if cache_file and cache_file.exists():
                logger.info("Cache hit: loading {} from disk", cache_file.name)
                ds = xr.open_dataset(str(cache_file))
            else:
                ds = load_sentinel2_for_indices(item, index_list)
                ds = mask_sentinel2(ds)

                # Clip to AOI polygon
                try:
                    ds = clip_dataset_to_aoi(ds, aoi_gdf=aoi_gdf)
                except Exception as clip_err:
                    logger.warning("Clipping failed: {}, using unclipped", clip_err)

                # Cache clipped scene for future reuse
                if cache_file:
                    try:
                        ds_computed = ds.compute()
                        ds_computed.to_netcdf(str(cache_file))
                        logger.info("Cached scene: {}", cache_file.name)
                        ds = ds_computed
                    except Exception as cache_err:
                        logger.warning("Failed to cache: {}", cache_err)

            clear_pct = compute_clear_percentage(ds)
            if clear_pct < min_clear:
                logger.info("Only {:.1f}% clear, skipping", clear_pct)
                continue

            # Stage 3: Compute indices
            idx_ds = compute_all_indices(ds, index_list, sensor="sentinel2")

            # Store regional stats
            for idx_name in index_list:
                if idx_name in idx_ds:
                    store_regional_stats(scene_date, idx_name, idx_ds[idx_name])

            # Stage 4: Load baselines and compare
            baseline_means = {}
            baseline_stds = {}

            for idx_name in index_list:
                try:
                    mean, std = load_baseline_pair(idx_name, current_month)
                    baseline_means[idx_name] = mean
                    baseline_stds[idx_name] = std
                except FileNotFoundError:
                    logger.warning("No baseline for {} month {}", idx_name, current_month)

            if not baseline_means:
                logger.warning("No baselines available, skipping detection")
                continue

            # Stage 5: Detect changes (with drought adjustment if SPI available)
            detection = detect_deforestation(
                current_indices=idx_ds,
                baseline_means=baseline_means,
                baseline_stds=baseline_stds,
                spi_3month=spi_value,
            )

            # Vectorize alerts
            alerts_gdf = vectorize_alerts(detection["confidence"])

            if not alerts_gdf.empty:
                # Save alerts
                alert_path = save_alerts(alerts_gdf, scene_date)
                all_alerts.append(alerts_gdf)

                # Store alert stats
                summary = summarize_alerts(alerts_gdf)
                store_alert_stats(scene_date, summary)

                logger.info(
                    "Scene {}: {} alerts, {:.1f} ha",
                    scene_date,
                    summary["total_alerts"],
                    summary["total_area_ha"],
                )
            else:
                logger.info("Scene {}: no alerts", scene_date)

        except Exception as e:
            logger.error("Failed to process {}: {}", item.id, e)
            continue

    # Summary
    if all_alerts:
        import geopandas as gpd

        combined = gpd.pd.concat(all_alerts, ignore_index=True)
        total_summary = summarize_alerts(gpd.GeoDataFrame(combined))
        logger.info("=== Detection Complete ===")
        logger.info("Total alerts: {}", total_summary["total_alerts"])
        logger.info("Total area: {:.1f} ha", total_summary["total_area_ha"])
        logger.info(
            "By confidence: high={}, medium={}, low={}",
            total_summary["by_confidence"]["high"],
            total_summary["by_confidence"]["medium"],
            total_summary["by_confidence"]["low"],
        )
    else:
        logger.info("=== No deforestation alerts detected ===")


if __name__ == "__main__":
    main()
