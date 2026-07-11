/*
 * Araripe baseline — Google Earth Engine Code Editor version.
 * Paste this into https://code.earthengine.google.com and click "Run".
 * Then open the "Tasks" tab (top-right) and click RUN on each of the 12 export
 * tasks. They export to your Google Drive folder 'araripe_baselines'.
 *
 * Mirrors scripts/build_baseline_gee.py exactly:
 *   - Collection COPERNICUS/S2_SR_HARMONIZED (reflectance = DN/10000; the 2022
 *     processing-baseline offset is already harmonized).
 *   - Years pooled: 2017, 2019, 2021, 2022, 2025.
 *   - Cloud mask via SCL clear classes {2,4,5,6,7,11}.
 *   - Per month: pixel-wise MEDIAN (-> _mean bands) and stdDev (-> _std bands)
 *     of NDMI/NBR/EVI2, exported as one 6-band GeoTIFF, EPSG:32724 @ 20 m.
 *   - Masked/out-of-AOI pixels filled with -9999 (restored to NaN by
 *     scripts/split_gee_baselines.py after you download the files).
 *
 * After downloading the 12 files from Drive:
 *   python scripts/split_gee_baselines.py --in-dir <downloaded_dir> --out-dir data/baselines
 *   # then set REFLECTANCE_SCALING = True in config/settings.py
 */

var YEARS      = [2017, 2019, 2021, 2022, 2025];
var SCL_CLEAR  = [2, 4, 5, 6, 7, 11];
var TARGET_CRS = 'EPSG:32724';
var SCALE      = 20;
var MAX_CLOUD  = 40;                       // scene CLOUDY_PIXEL_PERCENTAGE cutoff
var DRIVE_FOLDER = 'araripe_baselines';

// AOI bbox from data/aoi/APA_chapada_araripe.gpkg (WGS84), rounded out slightly.
var aoi = ee.Geometry.Rectangle([-40.90, -7.85, -38.95, -6.95]);
Map.centerObject(aoi, 8);
Map.addLayer(aoi, {color: 'red'}, 'AOI');

// Cloud-mask + reflectance + indices for one image.
function prep(img) {
  var scl = img.select('SCL');
  var mask = scl.eq(SCL_CLEAR[0]);
  for (var i = 1; i < SCL_CLEAR.length; i++) {
    mask = mask.or(scl.eq(SCL_CLEAR[i]));
  }
  var r = img.select(['B4', 'B8', 'B8A', 'B11', 'B12']).divide(10000).updateMask(mask);
  var ndmi = r.normalizedDifference(['B8A', 'B11']).rename('ndmi');   // (nir08-swir16)/(...)
  var nbr  = r.normalizedDifference(['B8A', 'B12']).rename('nbr');    // (nir08-swir22)/(...)
  var nir  = r.select('B8');
  var red  = r.select('B4');
  var evi2 = nir.subtract(red).multiply(2.5)
               .divide(nir.add(red.multiply(2.4)).add(1)).rename('evi2');
  return ndmi.addBands(nbr).addBands(evi2)
             .copyProperties(img, ['system:time_start']);
}

// OR of the target years (non-contiguous set).
var yearFilter = ee.Filter.calendarRange(YEARS[0], YEARS[0], 'year');
for (var y = 1; y < YEARS.length; y++) {
  yearFilter = ee.Filter.or(yearFilter, ee.Filter.calendarRange(YEARS[y], YEARS[y], 'year'));
}

for (var m = 1; m <= 12; m++) {
  var coll = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(aoi)
    .filter(yearFilter)
    .filter(ee.Filter.calendarRange(m, m, 'month'))
    .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', MAX_CLOUD))
    .map(prep);

  print('month ' + m + ' scenes pooled:', coll.size());

  var meanImg = coll.median().rename(['ndmi_mean', 'nbr_mean', 'evi2_mean']);
  var stdImg  = coll.reduce(ee.Reducer.stdDev()).rename(['ndmi_std', 'nbr_std', 'evi2_std']);
  var combined = meanImg.addBands(stdImg).clip(aoi).unmask(-9999).toFloat();

  var mm = (m < 10 ? '0' : '') + m;
  Export.image.toDrive({
    image: combined,
    description: 'araripe_baseline_month' + mm,
    folder: DRIVE_FOLDER,
    fileNamePrefix: 'araripe_baseline_month' + mm,
    region: aoi,
    scale: SCALE,
    crs: TARGET_CRS,
    maxPixels: 1e10,
    fileFormat: 'GeoTIFF'
  });
}

print('Created 12 export tasks. Open the "Tasks" tab (top-right) and click RUN on each.');
