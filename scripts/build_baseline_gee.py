"""Build the monthly baseline in Google Earth Engine (server-side) — no bulk download.

Motivation: streaming hundreds of Sentinel-2 scenes from AWS us-west-2 over a
home connection in Brazil is the bottleneck (~1 MB/s, intermittently throttled).
Earth Engine computes the monthly median composites ON GOOGLE'S SERVERS and you
download only the small results (12 GeoTIFFs, one per month), which is orders of
magnitude less data.

What it produces (matching the local pipeline exactly):
  * Collection: COPERNICUS/S2_SR_HARMONIZED (surface reflectance, DN 0-10000,
    already offset-harmonized across the 2022 processing-baseline change — so no
    per-scene offset juggling needed; reflectance = DN / 10000).
  * Years pooled: 2017, 2019, 2021, 2022, 2025 (the quiet-ENSO set; excludes the
    strong El-Nino 2023/2024).
  * Per calendar month (1-12): cloud-mask via SCL (clear classes {2,4,5,6,7,11},
    matching src/processing/cloud_mask.py), compute NDMI/NBR/EVI2 on reflectance,
    then the pixel-wise MEDIAN (the documented central statistic) and stdDev
    across all pooled scenes of that month.
  * Exports ONE 6-band GeoTIFF per month to Google Drive folder
    (bands: ndmi_mean, nbr_mean, evi2_mean, ndmi_std, nbr_std, evi2_std), in
    EPSG:32724 at 20 m over the AOI. 12 export tasks total.

Then run scripts/split_gee_baselines.py locally on the 12 downloaded files to
produce the 72 <index>_month<NN>_{mean,std}.tif COGs the detector reads, and set
REFLECTANCE_SCALING=True in config/settings.py (the reflectance baselines require
the detection side to also produce reflectance — the Task 1 coupling).

Prerequisites (one-time, ~5 min, all in the browser — see docs/BASELINE_GEE.md):
  1. A Google account registered for Earth Engine (https://earthengine.google.com,
     "Get Started" — free for research/non-commercial) with a Cloud project.
  2. pip install earthengine-api   (already in this repo's env)
  3. earthengine authenticate      (opens a browser once; stores a token)

Usage:
    python scripts/build_baseline_gee.py --project YOUR_GCP_PROJECT_ID
    python scripts/build_baseline_gee.py --project my-proj --max-cloud 40 --drive-folder araripe_baselines

Note: this script only QUEUES the export tasks (they run on Google's side, minutes
to ~1 h). Watch them in the Earth Engine Code Editor "Tasks" tab or with
`earthengine task list`. When done, download the GeoTIFFs from your Drive folder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Match the local pipeline exactly.
YEARS = [2017, 2019, 2021, 2022, 2025]
SCL_CLEAR = [2, 4, 5, 6, 7, 11]           # src/processing/cloud_mask.py S2_CLEAR_CLASSES
TARGET_CRS = "EPSG:32724"                  # config/settings.py TARGET_CRS
SCALE_M = 20                               # BASELINE_RESOLUTION
# AOI bbox from data/aoi/APA_chapada_araripe.gpkg (WGS84), rounded out slightly.
AOI_BOUNDS = [-40.90, -7.85, -38.95, -6.95]  # [west, south, east, north]


def _build_prep_fn(ee):
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
    return prep


@click.command()
@click.option("--project", required=True, help="Your Google Cloud project ID registered with Earth Engine.")
@click.option("--max-cloud", default=40, help="Max scene CLOUDY_PIXEL_PERCENTAGE to include.")
@click.option("--drive-folder", default="araripe_baselines", help="Google Drive folder for exports.")
@click.option("--months", default="1,2,3,4,5,6,7,8,9,10,11,12", help="Months to build.")
@click.option("--dry-run", is_flag=True, help="Print what would be exported without starting tasks.")
def main(project, max_cloud, drive_folder, months, dry_run):
    import ee

    try:
        ee.Initialize(project=project)
    except Exception:
        # First run may need auth; guide the user rather than crash cryptically.
        print("Earth Engine not initialized. Run `earthengine authenticate` first, "
              "then re-run. (See docs/BASELINE_GEE.md.)")
        raise

    aoi = ee.Geometry.Rectangle(AOI_BOUNDS)
    prep = _build_prep_fn(ee)
    month_list = [int(m) for m in months.split(",") if m.strip()]
    year_filter = ee.Filter.Or([ee.Filter.calendarRange(y, y, "year") for y in YEARS])

    print(f"Earth Engine baseline: years={YEARS} months={month_list} "
          f"max_cloud={max_cloud} crs={TARGET_CRS} scale={SCALE_M}m")
    print(f"AOI bbox {AOI_BOUNDS} -> Drive folder '{drive_folder}'")

    tasks = []
    for m in month_list:
        coll = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(aoi)
                .filter(year_filter)
                .filter(ee.Filter.calendarRange(m, m, "month"))
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", max_cloud))
                .map(prep))

        n = coll.size().getInfo()
        mean_img = coll.median().rename(["ndmi_mean", "nbr_mean", "evi2_mean"])
        std_img = coll.reduce(ee.Reducer.stdDev()).rename(["ndmi_std", "nbr_std", "evi2_std"])
        # unmask(-9999): GeoTIFF export writes masked pixels as 0 by default,
        # which is a VALID index value — so we fill masked/out-of-AOI pixels with
        # a clear sentinel (-9999, far outside the [-1,1] index range) that
        # split_gee_baselines.py restores to NaN.
        combined = mean_img.addBands(std_img).clip(aoi).unmask(-9999).toFloat()

        desc = f"araripe_baseline_month{m:02d}"
        print(f"  month {m:02d}: {n} scenes pooled -> {desc}")
        if dry_run:
            continue
        task = ee.batch.Export.image.toDrive(
            image=combined,
            description=desc,
            folder=drive_folder,
            fileNamePrefix=desc,
            region=aoi,
            scale=SCALE_M,
            crs=TARGET_CRS,
            maxPixels=int(1e10),
            fileFormat="GeoTIFF",
        )
        task.start()
        tasks.append((desc, task.id))

    if dry_run:
        print("\nDry run — no tasks started.")
        return
    print(f"\nStarted {len(tasks)} export tasks. Watch them at "
          "https://code.earthengine.google.com (Tasks tab) or `earthengine task list`.")
    for desc, tid in tasks:
        print(f"  {desc}: {tid}")
    print("\nWhen all tasks finish, download the 12 GeoTIFFs from your Drive folder, then:")
    print("  python scripts/split_gee_baselines.py --in-dir <downloaded_dir> --out-dir data/baselines")
    print("  # then set REFLECTANCE_SCALING = True in config/settings.py")


if __name__ == "__main__":
    main()
