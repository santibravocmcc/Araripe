"""Headless GEE detection for CI (service account -> synchronous pull -> alerts).

The fully-automated sibling of the manual Cloud Shell flow
(build_detection_gee.py + run_detection_from_gee.py). Runs end-to-end inside
GitHub Actions with NO human and NO Google Drive:

  1. authenticate Earth Engine with a **service account** (JSON key from the
     GEE_SA_KEY secret) — see src/acquisition/gee_download.ee_initialize;
  2. for each acquisition date in the window, build the same reflectance
     composite as the baseline (NDMI/NBR/EVI2/BSI) server-side and **pull it
     down synchronously** in tiles (getDownloadURL) — no async Export tasks;
  3. run the EXISTING detection logic (run_detection_from_gee.run_detection_on_dir)
     against the reflectance baselines -> data/alerts/alerts_<date>.geojson.

Why this exists: it uses GEE's compute (no AWS S3 throttle, one clean AOI
composite per date so no same-date-tile overwrite) while remaining a single
unattended CI step. For ongoing twice-weekly runs the window is small (a few
dates), so the tiled pull is cheap.

Local/manual use is fine too (interactive EE creds):
    python scripts/run_detection_gee.py --project ee-araripe --start 2026-04-28 --end 2026-05-15

CI use: set the GEE_SA_KEY secret (full service-account JSON) and EE project.

NOTE: the EE-touching steps need live Earth Engine credentials and were not
exercised in this repo's offline tests — validate with your service account
before trusting the scheduled job. The pure helpers are unit-tested.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import click
from loguru import logger

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # repo root
sys.path.insert(0, str(_HERE))         # scripts/ (to import run_detection_from_gee)

from config.settings import ALERTS_DIR, DEFAULT_LANDCOVER_COLLECTION
from src.acquisition.aoi import get_aoi_bbox_wgs84
from src.acquisition.gee_download import download_image_tiled, ee_initialize

SCL_CLEAR = [2, 4, 5, 6, 7, 11]
TARGET_CRS = "EPSG:32724"
SCALE = 20
BANDS = ["ndmi", "nbr", "evi2", "bsi"]


def _prep(img, ee):
    """Cloud-mask + reflectance + indices — identical to build_baseline_gee.py
    and build_detection_gee.py, so baseline and observation share one scale."""
    scl = img.select("SCL")
    mask = scl.eq(SCL_CLEAR[0])
    for c in SCL_CLEAR[1:]:
        mask = mask.Or(scl.eq(c))
    r = img.select(["B2", "B4", "B8", "B8A", "B11", "B12"]).divide(10000).updateMask(mask)
    ndmi = r.normalizedDifference(["B8A", "B11"]).rename("ndmi")
    nbr = r.normalizedDifference(["B8A", "B12"]).rename("nbr")
    nir = r.select("B8"); red = r.select("B4"); blue = r.select("B2"); swir = r.select("B11")
    evi2 = (nir.subtract(red).multiply(2.5)
            .divide(nir.add(red.multiply(2.4)).add(1)).rename("evi2"))
    num = swir.add(red).subtract(nir.add(blue))
    den = swir.add(red).add(nir.add(blue))
    bsi = num.divide(den).rename("bsi")
    return (ndmi.addBands(nbr).addBands(evi2).addBands(bsi)
            .copyProperties(img, ["system:time_start"]))


@click.command()
@click.option("--project", default="ee-araripe", help="Earth Engine / Cloud project id.")
@click.option("--start", default=None, help="YYYY-MM-DD (default: today - days-back).")
@click.option("--end", default=None, help="YYYY-MM-DD exclusive (default: tomorrow).")
@click.option("--days-back", default=16, help="Window when --start omitted (bi-weekly default).")
@click.option("--max-cloud", default=60, help="Scene-level cloud filter %% (per-date mosaic is masked anyway).")
@click.option("--out-dir", default=str(ALERTS_DIR), help="Alerts output dir.")
@click.option("--work-dir", default=None, help="Where to keep downloaded composites (temp if unset).")
@click.option("--tile-px", default=1024, help="Max px/side per download tile (getDownloadURL 32MB cap).")
@click.option("--persistence/--no-persistence", default=True)
@click.option("--landcover-collection", default=DEFAULT_LANDCOVER_COLLECTION)
@click.option("--classify-clearing/--no-classify-clearing", default=True)
@click.option("--spi/--no-spi", default=True, help="CHIRPS SPI drought widening.")
def main(project, start, end, days_back, max_cloud, out_dir, work_dir, tile_px,
         persistence, landcover_collection, classify_clearing, spi):
    import ee

    # CI passes possibly-empty --start/--end; treat empty as "use default".
    start = start or None
    end = end or None

    ee_initialize(project)
    bbox = list(get_aoi_bbox_wgs84())  # [w, s, e, n]
    aoi = ee.Geometry.Rectangle(bbox, proj="EPSG:4326", geodesic=False)

    if end is None:
        end = (datetime.utcnow().date() + timedelta(days=1)).isoformat()
    if start is None:
        start = (datetime.utcnow().date() - timedelta(days=days_back)).isoformat()

    base = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi).filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud)))
    dates = (base.aggregate_array("system:time_start")
             .map(lambda t: ee.Date(t).format("YYYY-MM-dd")).distinct().sort().getInfo())
    logger.info("GEE detection {}..{}: {} distinct acquisition date(s)", start, end, len(dates))
    if not dates:
        logger.warning("No scenes in window; nothing to do."); return

    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="araripe_gee_"))
    work.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading composites to {}", work)

    got = 0
    for d in dates:
        day = ee.Date(d)
        comp = (base.filterDate(day, day.advance(1, "day"))
                .map(lambda im: _prep(im, ee)).mosaic()
                .select(BANDS).clip(aoi).unmask(-9999))
        out = work / f"araripe_detect_{d}.tif"
        try:
            download_image_tiled(comp, bbox, out, bands=BANDS, scale=SCALE,
                                 crs=TARGET_CRS, tile_px=tile_px)
            got += 1
        except Exception as e:
            logger.error("Composite download failed for {} ({}); skipping", d, e)
            continue
    logger.info("Downloaded {}/{} composites; running detection.", got, len(dates))

    from run_detection_from_gee import run_detection_on_dir

    run_detection_on_dir(
        work, out_dir, persistence=persistence,
        landcover_collection=landcover_collection,
        classify_clearing=classify_clearing, spi=spi,
    )


if __name__ == "__main__":
    main()
