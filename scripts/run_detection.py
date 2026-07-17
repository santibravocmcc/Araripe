"""Twice-weekly detection script: find recent imagery, detect changes, generate alerts.

This script is designed to run in GitHub Actions on a twice-weekly schedule.

Usage:
    python scripts/run_detection.py
    python scripts/run_detection.py --days-back 30 --indices ndmi,nbr
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click
import numpy as np
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    ALERTS_DIR,
    AOI_BBOX,
    BASELINES_DIR,
    DEFAULT_LANDCOVER_COLLECTION,
    MAX_CLOUD_COVER,
    SCENE_ANOMALY_REJECT_FRAC,
    SCENE_CACHE_DIR,
    SEARCH_DAYS_BACK,
)
from src.acquisition.aoi import clip_dataset_to_aoi, get_aoi_bbox_wgs84, load_aoi_polygon
from src.acquisition.stac_client import (
    search_landsat,
    search_nasa_hls,
    search_sentinel2_with_fallback,
)
from src.acquisition.download import (
    load_hls_for_indices,
    load_landsat_for_indices,
    load_sentinel2_for_indices,
)
from src.detection.alerts import save_alerts, summarize_alerts, vectorize_alerts
from src.detection.baseline import load_baseline_pair
from src.detection.change_detect import detect_deforestation
from src.detection.landcover import annotate_alerts_all_collections
from src.detection.persistence import DEFAULT_MIN_OVERLAP_FRAC, save_persistence_state, update_tracks
from src.processing.cloud_mask import (
    compute_clear_percentage,
    mask_hls,
    mask_landsat,
    mask_sentinel2,
)
from src.processing.indices import compute_all_indices
from src.timeseries.builder import (
    store_alert_stats,
    store_regional_stats_values,
)
from src.utils.logging_setup import configure_run_logging


# ─── Multi-sensor dispatch ───────────────────────────────────────────────────
# Each supported source: (search fn, band loader, cloud mask, grid tolerance m).
# NOTE: the on-disk baselines are Sentinel-2 (20 m). Landsat/HLS observations
# are 30 m and are compared against those S2 baselines after nearest-neighbour
# grid snapping — this raises observation density (helping the persistence
# filter) but is a cross-sensor approximation; ideally each sensor gets its own
# baseline (roadmap). Extra sources are therefore opt-in via --extra-sources.
def _load_and_mask(item, sensor, index_list):
    if sensor == "sentinel2":
        return mask_sentinel2(load_sentinel2_for_indices(item, index_list))
    if sensor == "landsat":
        return mask_landsat(load_landsat_for_indices(item, index_list))
    if sensor == "hls":
        return mask_hls(load_hls_for_indices(item, index_list))
    raise ValueError(f"Unknown sensor {sensor!r}")


_GRID_TOLERANCE_M = {"sentinel2": 10, "landsat": 35, "hls": 35}

_CLEARING_LABELS = {0: "none", 1: "fire", 2: "mechanical", 3: "uncertain"}


def _merge_and_confirm(scene_date, parts, persistence, min_overlap_frac, state):
    """Merge every tile's alerts for one acquisition date into a single
    GeoDataFrame and update the gap-tolerant persistence tracks.

    Fixes a latent data-loss bug: the streaming loop yields one GeoDataFrame per
    *tile*, and several tiles can share one ``scene_date``. The old code called
    ``save_alerts(gdf, scene_date)`` once per tile, so each tile overwrote the
    previous tile's ``alerts_<date>.geojson`` — only the last tile of a date
    survived on disk, silently dropping the rest of the AOI. Now all tiles of a
    date are concatenated into one file. (The GEE path never had this bug: it
    mosaics all tiles into one AOI composite per date before detection.)

    Persistence is evaluated here (not per-tile), over the full merged date,
    using the gap-tolerant tracker (``update_tracks``): each alert is chained to
    a running track by spatial overlap, tolerating gaps up to 180 days; tracks
    reaching the top tier become permanent. Returns ``(merged, new_state)`` so
    the caller can thread the state across dates. Nothing is dropped.
    """
    import geopandas as gpd

    merged = gpd.GeoDataFrame(
        gpd.pd.concat(parts, ignore_index=True),
        crs=parts[0].crs,
    )
    if persistence:
        try:
            merged, state = update_tracks(
                merged, state, scene_date, min_overlap_frac=min_overlap_frac,
            )
            vc = merged["persistence_status"].value_counts().to_dict()
            logger.info("Persistência {}: {} | estado={} tracks", scene_date, vc, len(state))
        except Exception as pe:
            logger.warning("Persistence step failed ({}); marking candidate", pe)
            merged["persistence_count"] = 1
            merged["persistence_status"] = "candidate"
    return merged, state


def _modal_class_per_polygon(gdf, class_da):
    """Modal (most frequent) raster value inside each polygon's exact geometry."""
    import numpy as np
    from rasterio.features import geometry_mask
    from rasterio.windows import Window
    from rasterio.windows import transform as window_transform

    vals = class_da.values
    transform = class_da.rio.transform()
    inv = ~transform
    out = []
    for _, row in gdf.to_crs(class_da.rio.crs).iterrows():
        b = row.geometry.bounds
        c0f, r0f = inv * (b[0], b[3])
        c1f, r1f = inv * (b[2], b[1])
        r0 = max(0, int(r0f)); r1 = min(vals.shape[0], int(r1f) + 1)
        c0 = max(0, int(c0f)); c1 = min(vals.shape[1], int(c1f) + 1)
        if r0 >= r1 or c0 >= c1:
            out.append(0); continue
        win = Window(c0, r0, c1 - c0, r1 - r0)
        try:
            mask = geometry_mask([row.geometry.__geo_interface__],
                                 out_shape=(r1 - r0, c1 - c0),
                                 transform=window_transform(win, transform),
                                 invert=True, all_touched=True)
        except Exception:
            out.append(0); continue
        inside = vals[r0:r1, c0:c1][mask]
        inside = inside[np.isfinite(inside)] if inside.dtype.kind == "f" else inside
        inside = inside[inside > 0]  # ignore 'none'
        if inside.size == 0:
            out.append(0); continue
        codes, counts = np.unique(inside.astype(int), return_counts=True)
        out.append(int(codes[counts.argmax()]))
    return out


@click.command()
@click.option("--days-back", default=SEARCH_DAYS_BACK, help="Days to look back.")
@click.option("--indices", default="ndmi,nbr,evi2", help="Comma-separated indices.")
@click.option("--max-cloud", default=MAX_CLOUD_COVER, help="Max cloud cover %.")
@click.option("--min-clear", default=50.0, help="Min clear pixel %% to process scene (default 50; lower values let in scenes with more residual cloud / cirrus).")
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
@click.option(
    "--max-scenes",
    default=20,
    help="Maximum number of scenes to process per run (sorted by lowest cloud).",
)
@click.option(
    "--extra-sources",
    default="",
    help="Comma-separated additional sensors to query for more valid "
         "observations (reinforces the persistence filter): 'landsat', 'hls'. "
         "Empty = Sentinel-2 only. NOTE: compared against S2 baselines "
         "(cross-sensor approximation); HLS requires Earthdata auth.",
)
@click.option(
    "--persistence/--no-persistence",
    default=True,
    help="Only report alerts confirmed in >=2 consecutive observations "
         "(compares against the most recent prior alert file). Non-destructive: "
         "all alerts are saved with a persistence_status column.",
)
@click.option(
    "--min-overlap-frac",
    default=DEFAULT_MIN_OVERLAP_FRAC,
    help="Min overlap with the previous observation to confirm an alert.",
)
@click.option(
    "--landcover-collection",
    default=DEFAULT_LANDCOVER_COLLECTION,
    help="MapBiomas collection for annotating alerts (mapbiomas10m|mapbiomas30m). "
         "Empty string disables land-cover annotation.",
)
@click.option(
    "--classify-clearing/--no-classify-clearing",
    default=True,
    help="Annotate each alert with a likely clearing type (fire vs mechanical).",
)
@click.option(
    "--log-level",
    default="INFO",
    help="Console log level (file always captures full DEBUG detail under logs/).",
)
def main(
    days_back: int,
    indices: str,
    max_cloud: int,
    min_clear: float,
    cache: bool,
    aoi: str | None,
    max_scenes: int,
    extra_sources: str,
    persistence: bool,
    min_overlap_frac: float,
    landcover_collection: str,
    classify_clearing: bool,
    log_level: str,
) -> None:
    """Run the twice-weekly deforestation detection pipeline."""
    configure_run_logging("run_detection", console_level=log_level)
    index_list = [idx.strip() for idx in indices.split(",")]
    extra = [s.strip() for s in extra_sources.split(",") if s.strip()]
    # BSI is needed only to classify fire vs mechanical clearing; it is loaded
    # and computed as an extra index but is NOT used for z-score detection.
    do_classify = classify_clearing and "nbr" in index_list
    compute_list = index_list + (["bsi"] if do_classify and "bsi" not in index_list else [])
    today = datetime.utcnow().strftime("%Y-%m-%d")

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
    from src.acquisition.stac_client import _build_datetime_range

    datetime_range = _build_datetime_range(days_back=days_back)
    logger.info("Search window: {}", datetime_range)

    # Tag each item with its sensor so the per-scene loop can dispatch to the
    # right loader / cloud mask. Sentinel-2 is always queried; Landsat/HLS are
    # added on request to raise the density of valid observations (which
    # directly strengthens the persistence filter during the cloudy wet season).
    tagged: list[tuple[object, str]] = []
    s2_items = search_sentinel2_with_fallback(
        bbox=aoi_bbox, datetime_range=datetime_range, max_cloud_cover=max_cloud,
    )
    tagged.extend((it, "sentinel2") for it in s2_items)
    logger.info("Sentinel-2: {} scenes", len(s2_items))

    if "landsat" in extra:
        try:
            ls_items = list(search_landsat(
                bbox=aoi_bbox, datetime_range=datetime_range, max_cloud_cover=max_cloud,
            ))
            tagged.extend((it, "landsat") for it in ls_items)
            logger.info("Landsat: {} scenes", len(ls_items))
        except Exception as e:
            logger.warning("Landsat search failed ({}); continuing without it.", e)
    if "hls" in extra:
        try:
            hls_items = list(search_nasa_hls(
                bbox=aoi_bbox, datetime_range=datetime_range,
            ))
            tagged.extend((it, "hls") for it in hls_items)
            logger.info("HLS: {} scenes", len(hls_items))
        except Exception as e:
            logger.warning("HLS search failed ({}); continuing without it.", e)

    if len(tagged) == 0:
        logger.warning("No cloud-free imagery found. Exiting.")
        return

    logger.info("Found {} candidate scenes across {} sensor(s)",
                len(tagged), 1 + len(extra))

    # Sort by cloud cover (process clearest first)
    items_sorted = sorted(
        tagged,
        key=lambda t: t[0].properties.get("eo:cloud_cover", 100),
    )

    # Stage 2-5: Process scenes. Collect alerts per acquisition DATE (a date can
    # span several UTM tiles) so they can be merged into one file per date below
    # — saving per tile here would overwrite the file (see _merge_and_confirm).
    alerts_by_date: dict[str, list] = {}
    # Valid index pixels + total pixel count per (date, index), pooled across all
    # UTM tiles of a date, so regional stats are written once over the full AOI
    # in Stage 6 (writing per tile collided on UNIQUE(date,index,'full_aoi') and
    # kept only the last tile). Memory is bounded by --max-scenes; for the
    # bi-weekly window this is a handful of scenes.
    regional_px: dict[str, dict[str, list]] = {}
    regional_total: dict[str, dict[str, int]] = {}

    for item, sensor in items_sorted[:max_scenes]:  # up to --max-scenes best scenes
        scene_date = str(item.datetime)[:10]
        scene_month = item.datetime.month
        cloud_pct = item.properties.get("eo:cloud_cover", "?")
        logger.info("Processing {} [{}] (cloud: {}%, month: {})",
                    item.id, sensor, cloud_pct, scene_month)

        try:
            # Stage 2: Load, mask, and clip to AOI
            import xarray as xr

            cache_file = cache_dir / f"{item.id.replace('/', '_')}.nc" if cache_dir else None

            if cache_file and cache_file.exists():
                logger.info("Cache hit: loading {} from disk", cache_file.name)
                ds = xr.open_dataset(str(cache_file))
                # Re-apply the clear-pixel filter on cached scenes too. The
                # cache was written after an earlier --min-clear pass, but
                # subsequent runs may use a stricter threshold and still
                # need to honour it.
                cached_clear_pct = compute_clear_percentage(ds)
                if cached_clear_pct < min_clear:
                    logger.info(
                        "Cached scene only {:.1f}% clear (< {}%), skipping",
                        cached_clear_pct, min_clear,
                    )
                    continue
            else:
                # Dispatch to the sensor-specific loader + cloud mask.
                ds = _load_and_mask(item, sensor, compute_list)

                # Check clear percentage BEFORE clipping (clipping can
                # reset NaN pixels and inflate the clear percentage).
                clear_pct = compute_clear_percentage(ds)
                if clear_pct < min_clear:
                    logger.info("Only {:.1f}% clear pixels, skipping", clear_pct)
                    continue

                # Clip to AOI polygon — skip tile if it doesn't overlap
                try:
                    ds = clip_dataset_to_aoi(ds, aoi_gdf=aoi_gdf)
                except Exception as clip_err:
                    logger.warning("Tile does not overlap AOI ({}), skipping", clip_err)
                    continue

                # Cache clipped scene for future reuse
                if cache_file:
                    try:
                        ds_computed = ds.compute()
                        ds_computed.to_netcdf(str(cache_file))
                        logger.info("Cached scene: {}", cache_file.name)
                        ds = ds_computed
                    except Exception as cache_err:
                        logger.warning("Failed to cache: {}", cache_err)

            # Stage 3: Compute indices (incl. BSI when classifying clearing).
            # Only compute indices whose required bands are actually present —
            # a cached scene written under a bsi-free band set lacks 'blue', so
            # requesting bsi would KeyError and drop the whole scene.
            from config.bands import INDEX_BANDS, LANDSAT_INDEX_BANDS

            _band_req = LANDSAT_INDEX_BANDS if sensor in ("landsat", "hls") else INDEX_BANDS
            _avail = set(ds.data_vars)
            usable = [ix for ix in compute_list if set(_band_req.get(ix, [])) <= _avail]
            if set(usable) != set(compute_list):
                logger.info("Bands available only for indices {} (requested {})",
                            usable, compute_list)
            idx_ds = compute_all_indices(ds, usable, sensor=sensor)

            # Accumulate valid pixels per (date, index) for a single full-AOI
            # regional-stats write in Stage 6 (see regional_px note above).
            for idx_name in index_list:
                if idx_name in idx_ds:
                    vals = idx_ds[idx_name].values.ravel()
                    finite = vals[np.isfinite(vals)]
                    regional_px.setdefault(scene_date, {}).setdefault(idx_name, [])
                    regional_total.setdefault(scene_date, {}).setdefault(idx_name, 0)
                    if finite.size:
                        regional_px[scene_date][idx_name].append(finite)
                    regional_total[scene_date][idx_name] += int(vals.size)

            # Stage 4: Load baselines and compare
            baseline_means = {}
            baseline_stds = {}
            # Grid snap tolerance: S2 baselines are 20 m; a coarser sensor
            # needs a wider nearest-neighbour tolerance to align.
            tol = _GRID_TOLERANCE_M.get(sensor, 10)

            for idx_name in index_list:
                try:
                    mean, std = load_baseline_pair(idx_name, scene_month)
                    # Align baseline grid to current scene grid.
                    ref_var = list(idx_ds.data_vars)[0]
                    mean = mean.reindex_like(idx_ds[ref_var], method="nearest", tolerance=tol)
                    std = std.reindex_like(idx_ds[ref_var], method="nearest", tolerance=tol)
                    baseline_means[idx_name] = mean
                    baseline_stds[idx_name] = std
                except FileNotFoundError:
                    logger.warning("No baseline for {} month {}", idx_name, scene_month)

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

            # Scene-wide anomaly guard. If a large fraction of the clipped
            # AOI pixels are flagged at any confidence level, the scene is
            # almost certainly a thin-cirrus / BRDF / mosaic-seam artefact
            # rather than a real deforestation event. Reject it wholesale.
            try:
                conf = detection["confidence"]
                valid_mask = ~np.isnan(conf.values)
                n_valid = int(valid_mask.sum())
                n_alert = int(((conf.values >= 1) & valid_mask).sum())
                if n_valid > 0:
                    alert_frac = n_alert / n_valid
                    if alert_frac > SCENE_ANOMALY_REJECT_FRAC:
                        logger.warning(
                            "Scene {}: {:.1%} of valid pixels flagged "
                            "(>{:.0%} threshold) — likely scene-wide "
                            "atmospheric anomaly, REJECTING this scene.",
                            scene_date, alert_frac, SCENE_ANOMALY_REJECT_FRAC,
                        )
                        continue
            except Exception as guard_err:
                logger.warning("Scene-wide guard failed ({}); proceeding", guard_err)

            # Vectorize alerts (drops both too-small and too-large polygons)
            alerts_gdf = vectorize_alerts(detection["confidence"])

            if not alerts_gdf.empty:
                # ─── Task 7.2: annotate clearing type (fire vs mechanical) ────
                if do_classify and "nbr" in baseline_means and "bsi" in idx_ds:
                    try:
                        from src.detection.change_detect import classify_fire_vs_mechanical

                        clearing = classify_fire_vs_mechanical(
                            nbr_pre=baseline_means["nbr"],
                            nbr_post=idx_ds["nbr"],
                            bsi_post=idx_ds["bsi"],
                        )
                        codes = _modal_class_per_polygon(alerts_gdf, clearing)
                        alerts_gdf["clearing_type"] = [_CLEARING_LABELS.get(c, "none") for c in codes]
                    except Exception as ce:
                        logger.warning("Clearing classification failed ({}); skipping", ce)

                # ─── Task 8: annotate with land-cover context (BOTH collections)
                # Suffixed columns lc_group_10m / lc_group_30m … so the FE can
                # characterise/filter by either collection. Nothing is dropped.
                try:
                    alerts_gdf = annotate_alerts_all_collections(
                        alerts_gdf, default_collection=landcover_collection,
                    )
                except Exception as le:
                    logger.warning("Land-cover annotation failed ({}); skipping", le)

                # Persistence + save are deferred to a per-DATE phase after the
                # loop (see _merge_and_confirm): several tiles can share one
                # scene_date, and saving here would make each tile overwrite the
                # previous tile's file. Collect this tile's alerts under its date.
                alerts_by_date.setdefault(scene_date, []).append(alerts_gdf)
                logger.info(
                    "Scene {} [{}]: {} candidate polygon(s) (pre-merge)",
                    scene_date, sensor, len(alerts_gdf),
                )
            else:
                logger.info("Scene {}: no alerts", scene_date)

        except Exception as e:  # keep per-scene failures isolated
            logger.error("Failed to process {}: {}", item.id, e)
            continue

    # ─── Stage 6a: regional stats, once per date over the full merged AOI ─────
    # (Includes dates with no alerts, matching the old per-scene behavior.)
    for scene_date in sorted(regional_px):
        for idx_name, arrs in regional_px[scene_date].items():
            if not arrs:
                continue
            try:
                store_regional_stats_values(
                    scene_date, idx_name, np.concatenate(arrs),
                    total_pixels=regional_total[scene_date][idx_name],
                )
            except Exception as rse:
                logger.warning("Regional stats {} {} failed ({})", scene_date, idx_name, rse)

    # ─── Stage 6b: merge tiles per date, confirm persistence, save once ───────
    # Process dates chronologically so persistence chains correctly: each date's
    # file is saved before the next date's previous-file lookup runs, so one run
    # confirms its own consecutive dates as well as against prior history.
    all_alerts = []
    import geopandas as gpd
    state_path = ALERTS_DIR.parent / "persistence_state.geojson"
    state = None
    if persistence and state_path.exists():
        try:
            state = gpd.read_file(str(state_path))
            logger.info("Persistência: estado carregado ({} tracks)", len(state))
        except Exception as e:
            logger.warning("Não foi possível ler o estado de persistência ({}); do zero", e)
    for scene_date in sorted(alerts_by_date):
        parts = alerts_by_date[scene_date]
        merged, state = _merge_and_confirm(
            scene_date, parts, persistence, min_overlap_frac, state,
        )
        save_alerts(merged, scene_date)
        summary = summarize_alerts(merged)
        store_alert_stats(scene_date, summary)
        all_alerts.append(merged)
        logger.info(
            "Date {}: {} alert(s) merged from {} tile(s), {:.1f} ha",
            scene_date, summary["total_alerts"], len(parts), summary["total_area_ha"],
        )
    if persistence and state is not None:
        try:
            save_persistence_state(state, state_path)
            logger.info("Persistência: estado salvo ({} tracks) -> {}", len(state), state_path)
        except Exception as e:
            logger.warning("Falha ao salvar o estado de persistência ({})", e)

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
