"""Global settings for the Araripe deforestation monitoring system."""

from pathlib import Path

# ─── Project paths ────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
AOI_DIR = DATA_DIR / "aoi"
BASELINES_DIR = DATA_DIR / "baselines"
ALERTS_DIR = DATA_DIR / "alerts"
TIMESERIES_DIR = DATA_DIR / "timeseries"

# ─── Area of Interest ─────────────────────────────────────────────────────────
# Chapada do Araripe bounding box: ~7–8°S, 39–40°W
AOI_BBOX = [-40.0, -8.0, -39.0, -7.0]  # [west, south, east, north]
AOI_GEOJSON = AOI_DIR / "chapada_araripe.geojson"
AOI_GEOPACKAGE = AOI_DIR / "chapada_araripe.gpkg"

# ─── STAC API endpoints ──────────────────────────────────────────────────────
ELEMENT84_URL = "https://earth-search.aws.element84.com/v1"
PLANETARY_COMPUTER_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
NASA_STAC_URL = "https://cmr.earthdata.nasa.gov/stac/LPCLOUD"
COPERNICUS_STAC_URL = "https://stac.dataspace.copernicus.eu/v1"

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

# ─── Detection thresholds ────────────────────────────────────────────────────
# Z-score thresholds (number of standard deviations below mean)
Z_THRESHOLD_HIGH = -3.0
Z_THRESHOLD_MEDIUM = -2.5
Z_THRESHOLD_LOW = -2.0

# Delta thresholds (absolute change from baseline mean)
DELTA_THRESHOLD_HIGH = -0.20
DELTA_THRESHOLD_MEDIUM = -0.15
DELTA_THRESHOLD_LOW = -0.10

# Minimum alert area in hectares (patches smaller than this are filtered out)
MIN_ALERT_AREA_HA = 1.0

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
