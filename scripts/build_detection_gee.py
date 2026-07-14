"""Per-date detection composites via Google Earth Engine (for Cloud Shell).

Companion to build_baseline_gee.py, but for DETECTION instead of the baseline:
instead of one median per calendar month over many years, this computes ONE
cloud-masked composite PER ACQUISITION DATE over the AOI, for a date range
(default: all of 2026). Each date's Sentinel-2 tiles are mosaicked into a single
AOI-wide image, and NDMI/NBR/EVI2/BSI are computed on surface reflectance — the
exact same prep as the baseline, so the two are on the same scale.

Output: one small 4-band GeoTIFF per date to Google Drive
    araripe_detect_YYYY-MM-DD.tif   (bands: ndmi, nbr, evi2, bsi)
Masked/out-of-AOI pixels are filled with -9999 (restored to NaN downstream).

Then, on your Mac, run scripts/run_detection_from_gee.py on the downloaded files
to produce data/alerts/alerts_YYYY-MM-DD.geojson via the EXISTING detection logic
(z-score vs the reflectance baselines -> vectorize -> land cover -> fire/mechanical
-> temporal persistence).

This sidesteps the AWS streaming bottleneck entirely (compute runs on Google's
servers; you download only small per-date results).

Cloud Shell setup (once): pip install --user earthengine-api; earthengine authenticate
Run:
    python3 build_detection_gee.py --project ee-araripe
    python3 build_detection_gee.py --project ee-araripe --start 2026-04-28 --end 2026-07-12
"""

import sys

try:
    import ee
except ImportError:
    print("Run: pip install --user earthengine-api"); raise

# ── args (simple, no click, for Cloud Shell) ──────────────────────────────────
def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default

PROJECT = _arg("--project", "ee-araripe")
START = _arg("--start", "2026-01-01")
END = _arg("--end", "2026-07-13")          # exclusive-ish upper bound; adjust to "today+1"
MAX_CLOUD = int(_arg("--max-cloud", "60"))  # scene-level; per-date mosaic is cloud-masked anyway
DRIVE_FOLDER = _arg("--drive-folder", "araripe_detection")

SCL_CLEAR = [2, 4, 5, 6, 7, 11]
TARGET_CRS = "EPSG:32724"
SCALE = 20
AOI_BOUNDS = [-40.90, -7.85, -38.95, -6.95]

ee.Initialize(project=PROJECT)
aoi = ee.Geometry.Rectangle(AOI_BOUNDS)


def prep(img):
    """Cloud-mask + reflectance + indices (matches build_baseline_gee.py + the
    local detector's band choices: ndmi/nbr use B8A; evi2/bsi use B8)."""
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
    # BSI = ((SWIR1+RED)-(NIR+BLUE))/((SWIR1+RED)+(NIR+BLUE))
    num = swir.add(red).subtract(nir.add(blue))
    den = swir.add(red).add(nir.add(blue))
    bsi = num.divide(den).rename("bsi")
    return (ndmi.addBands(nbr).addBands(evi2).addBands(bsi)
            .copyProperties(img, ["system:time_start"]))


base = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(START, END)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", MAX_CLOUD)))

# Distinct acquisition dates (YYYY-MM-DD), computed server-side then pulled (small).
dates = base.aggregate_array("system:time_start") \
    .map(lambda t: ee.Date(t).format("YYYY-MM-dd")).distinct().sort().getInfo()

print("Project %s | %s..%s | %d distinct dates | crs %s @ %dm | Drive '%s'"
      % (PROJECT, START, END, len(dates), TARGET_CRS, SCALE, DRIVE_FOLDER))

n = 0
for d in dates:
    day = ee.Date(d)
    # All tiles of this date -> masked+indexed -> mosaic into one AOI image.
    comp = base.filterDate(day, day.advance(1, "day")).map(prep).mosaic()
    comp = comp.select(["ndmi", "nbr", "evi2", "bsi"]).clip(aoi).unmask(-9999).toFloat()
    desc = "araripe_detect_%s" % d
    task = ee.batch.Export.image.toDrive(
        image=comp, description=desc, folder=DRIVE_FOLDER, fileNamePrefix=desc,
        region=aoi, scale=SCALE, crs=TARGET_CRS, maxPixels=int(1e10), fileFormat="GeoTIFF")
    task.start(); n += 1
    print("  queued %s (%s)" % (desc, task.id))

print("\n%d per-date export tasks started. Monitor: earthengine task list" % n)
print("When done, download the GeoTIFFs from Drive folder '%s', then on your Mac:" % DRIVE_FOLDER)
print("  python scripts/run_detection_from_gee.py --in-dir <downloaded_dir>")
