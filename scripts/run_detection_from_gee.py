"""Run detection from GEE per-date composites (the local half of the GEE path).

Reads the per-date 4-band GeoTIFFs produced by scripts/build_detection_gee.py
(downloaded from Google Drive) and runs the EXISTING detection logic against the
reflectance baselines — no imagery streaming, so the AWS network bottleneck is
gone. Reuses the same functions as scripts/run_detection.py (z-score/delta ->
confidence -> scene-wide guard -> vectorize -> fire/mechanical -> land cover ->
temporal persistence -> alerts_<date>.geojson), so the science is identical.

Because GEE mosaics all of a date's tiles into ONE AOI-wide composite, this also
fixes the streaming path's latent bug where same-date tiles overwrote each
other's alert file.

Input bands per file: ndmi, nbr, evi2, bsi (bsi only for fire-vs-mechanical).
-9999 (export fill) is restored to NaN.

Usage:
    python scripts/run_detection_from_gee.py --in-dir ~/Downloads/araripe_detection
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click
import numpy as np
import rioxarray  # noqa: F401 (registers .rio)
import xarray as xr
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    ALERTS_DIR,
    DEFAULT_LANDCOVER_COLLECTION,
    LANDCOVER_RASTERS,
    SCENE_ANOMALY_REJECT_FRAC,
    TARGET_CRS,
)
from src.acquisition.aoi import get_aoi_bbox_wgs84
from src.detection.alerts import save_alerts, summarize_alerts, vectorize_alerts
from src.detection.baseline import load_baseline_pair
from src.detection.change_detect import classify_fire_vs_mechanical, detect_deforestation
from src.detection.landcover import annotate_alerts_with_landcover
from src.detection.persistence import DEFAULT_MIN_OVERLAP_FRAC, filter_alerts_by_persistence
from src.timeseries.builder import store_alert_stats, store_regional_stats

INDICES = ["ndmi", "nbr", "evi2"]     # detection channels
_BAND_ORDER = ["ndmi", "nbr", "evi2", "bsi"]  # export order in build_detection_gee.py
_CLEARING = {0: "none", 1: "fire", 2: "mechanical", 3: "uncertain"}
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _modal_class_per_polygon(gdf, class_da):
    """Modal (most frequent) raster value inside each polygon's exact geometry."""
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
            mask = geometry_mask([row.geometry.__geo_interface__], out_shape=(r1 - r0, c1 - c0),
                                 transform=window_transform(win, transform), invert=True, all_touched=True)
        except Exception:
            out.append(0); continue
        inside = vals[r0:r1, c0:c1][mask]
        inside = inside[np.isfinite(inside)]
        inside = inside[inside > 0]
        out.append(int(np.bincount(inside.astype(int)).argmax()) if inside.size else 0)
    return out


def _load_composite(path: Path) -> tuple[xr.Dataset, xr.DataArray]:
    """Load a per-date GEE composite -> (idx_ds[ndmi,nbr,evi2], bsi DataArray)."""
    da = rioxarray.open_rasterio(path)  # (band, y, x)
    da = da.where(da > -9990)           # restore -9999 export fill to NaN
    n = da.sizes["band"]
    names = _BAND_ORDER[:n]
    arrays = {}
    for i, nm in enumerate(names):
        arrays[nm] = da.isel(band=i, drop=True)
    ds = xr.Dataset({k: arrays[k] for k in names if k in INDICES})
    ds = ds.rio.write_crs(da.rio.crs or TARGET_CRS)
    bsi = arrays.get("bsi")
    if bsi is not None:
        bsi = bsi.rio.write_crs(da.rio.crs or TARGET_CRS)
    return ds, bsi


@click.command()
@click.option("--in-dir", required=True, type=click.Path(exists=True), help="Dir with araripe_detect_*.tif from Drive.")
@click.option("--out-dir", default=str(ALERTS_DIR), help="Output alerts dir.")
@click.option("--min-clear", default=20.0, help="Skip a date if valid AOI coverage %% is below this.")
@click.option("--persistence/--no-persistence", default=True, help="Require >=2 consecutive observations.")
@click.option("--min-overlap-frac", default=DEFAULT_MIN_OVERLAP_FRAC)
@click.option("--landcover-collection", default=DEFAULT_LANDCOVER_COLLECTION)
@click.option("--classify-clearing/--no-classify-clearing", default=True)
@click.option("--spi/--no-spi", default=True, help="Fetch CHIRPS SPI for drought "
              "widening. Use --no-spi to skip (offline, or when CHIRPS is slow).")
def main(in_dir, out_dir, min_clear, persistence, min_overlap_frac, landcover_collection, classify_clearing, spi):
    in_dir = Path(in_dir); out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted((f for f in in_dir.glob("*.tif") if _DATE_RE.search(f.stem)),
                   key=lambda f: _DATE_RE.search(f.stem).group(1))
    if not files:
        logger.error("No araripe_detect_*.tif (with a date) in {}", in_dir); raise SystemExit(1)
    logger.info("Found {} per-date composites in {}", len(files), in_dir)

    # SPI once (drought widening), like run_detection.py.
    spi_value = None
    if spi:
        try:
            from src.processing.spi import get_current_spi
            spi_value = get_current_spi(get_aoi_bbox_wgs84())
            logger.info("Current 3-month SPI: {:.2f}", spi_value)
        except Exception as e:
            logger.warning("SPI unavailable ({}); no drought adjustment.", e)
    else:
        logger.info("SPI skipped (--no-spi)")

    n_written = 0
    for f in files:
        date = _DATE_RE.search(f.stem).group(1)
        month = int(date[5:7])
        logger.info("=== {} (month {}) ===", date, month)
        try:
            idx_ds, bsi = _load_composite(f)
            ref = idx_ds[list(idx_ds.data_vars)[0]]
            cov = 100.0 * float(np.isfinite(ref.values).mean())
            if cov < min_clear:
                logger.info("{}: only {:.1f}% valid AOI coverage (< {}%), skipping", date, cov, min_clear)
                continue

            for idx_name in INDICES:
                if idx_name in idx_ds:
                    store_regional_stats(date, idx_name, idx_ds[idx_name])

            baseline_means, baseline_stds = {}, {}
            for idx_name in INDICES:
                try:
                    mean, std = load_baseline_pair(idx_name, month)
                    mean = mean.reindex_like(ref, method="nearest", tolerance=15)
                    std = std.reindex_like(ref, method="nearest", tolerance=15)
                    baseline_means[idx_name] = mean; baseline_stds[idx_name] = std
                except FileNotFoundError:
                    logger.warning("No baseline for {} month {}", idx_name, month)
            if not baseline_means:
                logger.warning("No baselines; skipping {}", date); continue

            detection = detect_deforestation(idx_ds, baseline_means, baseline_stds, spi_3month=spi_value)

            # Scene-wide anomaly guard (same as run_detection.py).
            conf = detection["confidence"]
            valid = ~np.isnan(conf.values)
            nv = int(valid.sum())
            if nv > 0 and int(((conf.values >= 1) & valid).sum()) / nv > SCENE_ANOMALY_REJECT_FRAC:
                logger.warning("{}: >{:.0%} flagged — scene-wide anomaly, rejecting", date, SCENE_ANOMALY_REJECT_FRAC)
                continue

            alerts = vectorize_alerts(detection["confidence"])
            if alerts.empty:
                logger.info("{}: no alerts", date); continue

            # Fire vs mechanical (bsi from the composite; nbr_pre from baseline).
            if classify_clearing and bsi is not None and "nbr" in baseline_means:
                try:
                    clearing = classify_fire_vs_mechanical(baseline_means["nbr"], idx_ds["nbr"], bsi)
                    codes = _modal_class_per_polygon(alerts, clearing)
                    alerts["clearing_type"] = [_CLEARING.get(c, "none") for c in codes]
                except Exception as ce:
                    logger.warning("clearing classification failed ({})", ce)

            # Land cover annotation.
            if landcover_collection in LANDCOVER_RASTERS and Path(LANDCOVER_RASTERS[landcover_collection]).exists():
                try:
                    alerts = annotate_alerts_with_landcover(alerts, LANDCOVER_RASTERS[landcover_collection],
                                                            collection=landcover_collection)
                except Exception as le:
                    logger.warning("land-cover annotation failed ({})", le)

            # Temporal persistence vs the previous processed date.
            if persistence:
                import geopandas as gpd
                prev = None
                for pf in sorted(out_dir.glob("alerts_*.geojson")):
                    d = pf.stem.replace("alerts_", "")
                    if d < date:
                        prev = pf
                if prev is None:
                    alerts["persistence_status"] = "first_observation"
                else:
                    confirmed = filter_alerts_by_persistence(alerts, gpd.read_file(str(prev)),
                                                             min_overlap_frac=min_overlap_frac)
                    ci = set(confirmed.index)
                    alerts["persistence_status"] = ["confirmed" if i in ci else "candidate" for i in alerts.index]
                    logger.info("persistence: {}/{} confirmed vs {}", len(confirmed), len(alerts), prev.name)

            save_alerts(alerts, date, alerts_dir=out_dir)
            store_alert_stats(date, summarize_alerts(alerts))
            n_written += 1
            s = summarize_alerts(alerts)
            logger.info("{}: {} alerts, {:.1f} ha", date, s["total_alerts"], s["total_area_ha"])
        except Exception as e:
            logger.error("Failed {}: {}", date, e); continue

    logger.info("=== Done. Wrote alerts for {} dates to {} ===", n_written, out_dir)


if __name__ == "__main__":
    main()
