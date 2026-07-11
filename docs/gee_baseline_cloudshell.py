"""Araripe baseline via Earth Engine — standalone, for Google Cloud Shell.

Self-contained (only needs `earthengine-api`; no repo imports, no click). Run it
in Cloud Shell (already authenticated to your Google account). It QUEUES 12
export tasks (one per month) that run on Google's servers and write GeoTIFFs to
your Google Drive folder 'araripe_baselines'.

Setup in Cloud Shell terminal (once):
    pip install --user earthengine-api
    earthengine authenticate       # follow the URL, paste the code back

Run:
    python3 gee_baseline_cloudshell.py            # uses project ee-araripe
    python3 gee_baseline_cloudshell.py MY_PROJECT # or pass your project id

Watch:  earthengine task list      (or your Drive folder)
"""

import sys
import ee

PROJECT = sys.argv[1] if len(sys.argv) > 1 else "ee-araripe"

YEARS = [2017, 2019, 2021, 2022, 2025]
SCL_CLEAR = [2, 4, 5, 6, 7, 11]
TARGET_CRS = "EPSG:32724"
SCALE = 20
MAX_CLOUD = 40
DRIVE_FOLDER = "araripe_baselines"
AOI_BOUNDS = [-40.90, -7.85, -38.95, -6.95]  # west, south, east, north (WGS84)

try:
    ee.Initialize(project=PROJECT)
except Exception:
    print("Earth Engine not initialized. In Cloud Shell run:\n"
          "  pip install --user earthengine-api\n"
          "  earthengine authenticate\n"
          "then re-run this script.")
    raise

aoi = ee.Geometry.Rectangle(AOI_BOUNDS)


def prep(img):
    scl = img.select("SCL")
    mask = scl.eq(SCL_CLEAR[0])
    for c in SCL_CLEAR[1:]:
        mask = mask.Or(scl.eq(c))
    r = img.select(["B4", "B8", "B8A", "B11", "B12"]).divide(10000).updateMask(mask)
    ndmi = r.normalizedDifference(["B8A", "B11"]).rename("ndmi")
    nbr = r.normalizedDifference(["B8A", "B12"]).rename("nbr")
    nir = r.select("B8")
    red = r.select("B4")
    evi2 = (nir.subtract(red).multiply(2.5)
            .divide(nir.add(red.multiply(2.4)).add(1)).rename("evi2"))
    return ndmi.addBands(nbr).addBands(evi2).copyProperties(img, ["system:time_start"])


year_filter = ee.Filter.calendarRange(YEARS[0], YEARS[0], "year")
for y in YEARS[1:]:
    year_filter = ee.Filter.Or(year_filter, ee.Filter.calendarRange(y, y, "year"))

print("Project %s | years %s | crs %s @ %dm | Drive folder '%s'"
      % (PROJECT, YEARS, TARGET_CRS, SCALE, DRIVE_FOLDER))

n_tasks = 0
for m in range(1, 13):
    coll = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi)
            .filter(year_filter)
            .filter(ee.Filter.calendarRange(m, m, "month"))
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", MAX_CLOUD))
            .map(prep))
    mean_img = coll.median().rename(["ndmi_mean", "nbr_mean", "evi2_mean"])
    std_img = coll.reduce(ee.Reducer.stdDev()).rename(["ndmi_std", "nbr_std", "evi2_std"])
    combined = mean_img.addBands(std_img).clip(aoi).unmask(-9999).toFloat()
    desc = "araripe_baseline_month%02d" % m
    task = ee.batch.Export.image.toDrive(
        image=combined, description=desc, folder=DRIVE_FOLDER,
        fileNamePrefix=desc, region=aoi, scale=SCALE, crs=TARGET_CRS,
        maxPixels=int(1e10), fileFormat="GeoTIFF",
    )
    task.start()
    n_tasks += 1
    print("  queued %s (task %s)" % (desc, task.id))

print("\nStarted %d export tasks. Monitor with:  earthengine task list" % n_tasks)
print("When done, download the 12 GeoTIFFs from Google Drive folder '%s'," % DRIVE_FOLDER)
print("then on your Mac run: python scripts/split_gee_baselines.py --in-dir <dir> --out-dir data/baselines")
