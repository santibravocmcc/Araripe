"""Global settings for the Araripe deforestation monitoring system."""

from pathlib import Path

# ─── Project paths ────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent

# Load credentials from a local .env (gitignored) so R2/Earthdata secrets can
# live in a file instead of manual `export`s. Imported by nearly every script,
# so all of them get it. Does NOT override already-set env vars, so CI secrets
# injected via the environment always win. No-op if the file / python-dotenv is
# absent (e.g. a minimal CI image).
try:
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(ROOT_DIR / ".env")
except Exception:
    pass
DATA_DIR = ROOT_DIR / "data"
AOI_DIR = DATA_DIR / "aoi"
BASELINES_DIR = DATA_DIR / "baselines"
ALERTS_DIR = DATA_DIR / "alerts"
TIMESERIES_DIR = DATA_DIR / "timeseries"

# ─── Area of Interest ─────────────────────────────────────────────────────────
# Chapada do Araripe bounding box: ~7–8°S, 39–40°W
AOI_BBOX = [-40.0, -8.0, -39.0, -7.0]  # [west, south, east, north]
AOI_GEOJSON = AOI_DIR / "chapada_araripe.geojson"
AOI_GEOPACKAGE = AOI_DIR / "APA_chapada_araripe.gpkg"

# ─── STAC API endpoints ──────────────────────────────────────────────────────
ELEMENT84_URL = "https://earth-search.aws.element84.com/v1"
PLANETARY_COMPUTER_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
NASA_STAC_URL = "https://cmr.earthdata.nasa.gov/stac/LPCLOUD"
# NOTE: Copernicus/CDSE (stac.dataspace.copernicus.eu) was removed as dead
# config — no code consumed it and the workflow's CDSE_* secrets were unused.
# Sentinel-1 SAR via CDSE (wet-season cloud penetration) is a roadmap item; it
# needs its own preprocessing chain (calibration/speckle/terrain correction),
# not just an endpoint. See AUDITORIA_TECNICA.md Task 7.3 / roadmap.

# ─── Collection IDs ──────────────────────────────────────────────────────────
SENTINEL2_COLLECTION = "sentinel-2-l2a"
SENTINEL2_C1_COLLECTION = "sentinel-2-c1-l2a"
LANDSAT_COLLECTION = "landsat-c2-l2"
HLS_LANDSAT_COLLECTION = "HLSL30.v2.0"
HLS_SENTINEL_COLLECTION = "HLSS30.v2.0"

# ─── Processing parameters ───────────────────────────────────────────────────
MAX_CLOUD_COVER = 20  # percent
SEARCH_DAYS_BACK = 16  # days to look back for recent imagery
MAX_ITEMS_PER_SEARCH = 50
CHUNK_SIZE = 512  # pixels per side for windowed processing
TARGET_CRS = "EPSG:32724"  # UTM zone 24S (covers Chapada do Araripe)
SENTINEL2_RESOLUTION = 10  # meters (native for B2/B3/B4/B8)
SENTINEL2_20M_RESOLUTION = 20  # meters (B5/B6/B7/B8A/B11/B12)
LANDSAT_RESOLUTION = 30  # meters

# ─── Baseline parameters ─────────────────────────────────────────────────────
BASELINE_YEARS = 5  # number of years of history for baseline computation
BASELINE_MONTHS = list(range(1, 13))  # all 12 months

# ─── Reflectance scaling (COUPLED with the baseline scale — Task 1) ───────────
# When True, load_band converts DN → surface reflectance in [0,1] (per-scene
# STAC raster:bands scale/offset). This is physically correct and fixes the
# inflated/mis-scaled EVI2, BUT it MUST match the scale of the on-disk baselines:
#   * The current baselines in data/baselines/ are DN-scale (built by the old
#     offline path), so this defaults to False to keep detection self-consistent.
#   * scripts/build_baseline.py forces this True for its own run, so a rebuilt
#     baseline is always in reflectance.
# To activate the EVI2 fix in production: rebuild the baselines in reflectance,
# THEN set REFLECTANCE_SCALING = True here.
# Do NOT flip this without rebuilding — "don't change scaling on one side only".
#
# ACTIVATED 2026-07-11: the on-disk baselines in data/baselines/ were rebuilt in
# surface reflectance via Google Earth Engine (scripts/build_baseline_gee.py +
# split_gee_baselines.py; median composites over {2017,2019,2021,2022,2025},
# validated: EVI2 medians ~0.15-0.44 seasonal, coverage ~100%). Detection now
# produces reflectance to match them.
REFLECTANCE_SCALING = True

# ─── Detection thresholds ────────────────────────────────────────────────────
# Z-score thresholds (number of standard deviations below mean)
Z_THRESHOLD_HIGH = -3.0
Z_THRESHOLD_MEDIUM = -2.5
Z_THRESHOLD_LOW = -2.0

# Delta thresholds (absolute change from baseline mean)
DELTA_THRESHOLD_HIGH = -0.20
DELTA_THRESHOLD_MEDIUM = -0.15
DELTA_THRESHOLD_LOW = -0.15

# Minimum alert area in hectares (patches smaller than this are filtered out)
MIN_ALERT_AREA_HA = 1.0

# Maximum alert area in hectares (polygons larger than this are scene-wide
# atmospheric anomalies, not real deforestation events, and are dropped).
MAX_ALERT_AREA_HA = 1000.0

# Scene-wide anomaly guard: if more than this fraction of clipped-AOI pixels
# in a single scene are flagged at any confidence level, the entire scene is
# rejected as an atmospheric / sensor anomaly (thin cirrus, BRDF, etc.).
SCENE_ANOMALY_REJECT_FRAC = 0.30

# Fire detection thresholds
DNBR_LOW_SEVERITY = 0.27
DNBR_HIGH_SEVERITY = 0.66
NBR_POST_FIRE_THRESHOLD = 0.1

# ─── Drought adjustment ──────────────────────────────────────────────────────
# When 3-month SPI < SPI_DROUGHT_THRESHOLD, widen z-score thresholds
SPI_DROUGHT_THRESHOLD = -1.0
DROUGHT_Z_ADJUSTMENT = 0.5  # add this to z thresholds during drought

# ─── NDFI thresholds (INPE standard) ─────────────────────────────────────────
NDFI_INTACT_FOREST = 0.75
NDFI_DEGRADED_MIN = 0.0

# ─── CHIRPS precipitation data ────────────────────────────────────────────────
CHIRPS_BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs"
CHIRPS_CACHE_DIR = DATA_DIR / "chirps"

# ─── Land cover (MapBiomas) context layers ───────────────────────────────────
# Two selectable collections; their class taxonomies differ (see
# src/detection/landcover.py). Paths point at AOI crops under data/landcover/.
LANDCOVER_DIR = DATA_DIR / "landcover"
LANDCOVER_RASTERS = {
    # Collection 2 beta (10 m, Sentinel-2, 2016–2023)
    "mapbiomas10m": LANDCOVER_DIR / "mapbiomas10m_araripe_2023.tif",
    # Collection 10 (Landsat legend; territorio crop is ~300 m aggregated)
    "mapbiomas30m": LANDCOVER_DIR / "mapbiomas30m_araripe_2023.tif",
}
DEFAULT_LANDCOVER_COLLECTION = "mapbiomas10m"
NATURAL_VEG_MIN_FRAC = 0.5  # default threshold for the natural-vegetation filter

# ─── Baseline quality filters ────────────────────────────────────────────────
MIN_CLEAR_PERCENTAGE_BASELINE = 10.0  # skip scenes with <10% clear pixels

# Months where Caatinga deciduous trees are leafless (Aug-Oct)
# Baselines for these months are less reliable for greenness indices
CAATINGA_LEAFOFF_MONTHS = [8, 9, 10]

# ─── Scene cache (clipped scenes saved to disk for reuse) ───────────────────
SCENE_CACHE_DIR = DATA_DIR / "scene_cache"

# ─── Cloudflare R2 ───────────────────────────────────────────────────────────
R2_BUCKET_NAME = "araripe-cogs"
R2_ENDPOINT_URL = ""  # set via environment variable

# ─── Dashboard defaults ──────────────────────────────────────────────────────
DEFAULT_MAP_CENTER = [-7.5, -39.5]  # lat, lon
DEFAULT_MAP_ZOOM = 10
MAP_HEIGHT = 600  # pixels
