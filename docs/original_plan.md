# Zero-cost deforestation monitoring system for Chapada do Araripe

**A fully free, publicly accessible system can be built to detect deforestation across Chapada do Araripe (7–8°S, 39–40°W) by combining Sentinel-2 and Landsat imagery accessed through open STAC APIs, processed weekly via GitHub Actions, and visualized through a Streamlit dashboard hosted on Hugging Face Spaces.** This plan covers every component—from satellite data ingestion to interactive map deployment—using exclusively zero-cost tools. The region sits at the transition between Cerrado and Caatinga biomes, creating unique challenges: Caatinga's deciduous trees shed leaves for eight months annually, making seasonal variation easily confused with deforestation unless moisture-based indices (NDMI, NBR) are prioritized over greenness indices (NDVI). The architecture below pre-computes all heavy processing on GitHub Actions runners (7 GB RAM, unlimited minutes for public repos) and serves lightweight pre-computed results through a web dashboard, keeping hosting costs at exactly $0/month.

---

## 1. Satellite data access: five free APIs with full programmatic access

Three STAC-compliant APIs provide the most practical free access to Sentinel-2 and Landsat imagery, supplemented by Google Earth Engine for server-side computation and NASA's Harmonized Landsat Sentinel dataset for cross-sensor analysis.

### Element84 Earth Search — simplest entry point, no authentication

| Resource | URL |
|---|---|
| STAC API endpoint | `https://earth-search.aws.element84.com/v1` |
| API documentation | `https://earth-search.aws.element84.com/v1/api.html` |
| Project page | `https://element84.com/earth-search` |

**Collections:** `sentinel-2-l2a` (free, no auth), `sentinel-2-c1-l2a` (Collection 1, baseline 5.0+), `landsat-c2-l2` (requester-pays AWS bucket). Sentinel-2 data is stored as Cloud Optimized GeoTIFFs, enabling band-level streaming without downloading full scenes. **No authentication required** for Sentinel-2 access.

```python
from pystac_client import Client
import rioxarray

catalog = Client.open("https://earth-search.aws.element84.com/v1")
search = catalog.search(
    collections=["sentinel-2-l2a"],
    bbox=[-40, -8, -39, -7],
    datetime="2025-01-01/2025-12-31",
    query={"eo:cloud_cover": {"lt": 20}},
    max_items=50
)
items = search.item_collection()
# Stream a single band directly (no download needed)
nir = rioxarray.open_rasterio(items[0].assets["nir"].href)
```

### Microsoft Planetary Computer — best multi-dataset platform

| Resource | URL |
|---|---|
| STAC API endpoint | `https://planetarycomputer.microsoft.com/api/stac/v1` |
| Documentation | `https://planetarycomputer.microsoft.com/docs/quickstarts/reading-stac/` |
| Account request | `https://planetarycomputer.microsoft.com/account/request` |
| Sentinel-2 L2A dataset | `https://planetarycomputer.microsoft.com/dataset/sentinel-2-l2a` |
| Landsat C2 L2 dataset | `https://planetarycomputer.microsoft.com/dataset/landsat-c2-l2` |

**Collections:** `sentinel-2-l2a` and `landsat-c2-l2` (covers Landsat 4–9). Metadata search is fully open; data access requires free SAS token signing via the `planetary-computer` Python package. An API key is optional but recommended for higher rate limits.

```python
from pystac_client import Client
import planetary_computer

catalog = Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1",
    modifier=planetary_computer.sign_inplace
)
# Both sensors from one platform
s2 = catalog.search(collections=["sentinel-2-l2a"], bbox=[-40,-8,-39,-7],
                     datetime="2025-01-01/2025-06-30", query={"eo:cloud_cover": {"lt": 20}})
ls = catalog.search(collections=["landsat-c2-l2"], bbox=[-40,-8,-39,-7],
                     datetime="2025-01-01/2025-06-30", query={"eo:cloud_cover": {"lt": 20}})
```

### Copernicus Data Space Ecosystem — official ESA source

| Resource | URL |
|---|---|
| Main portal | `https://dataspace.copernicus.eu/` |
| Registration | `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/login-actions/registration` |
| STAC API (v1.1.0) | `https://stac.dataspace.copernicus.eu/v1` |
| OData catalog | `https://catalogue.dataspace.copernicus.eu/odata/v1/Products` |
| OAuth2 token endpoint | `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token` |
| API documentation | `https://documentation.dataspace.copernicus.eu/APIs.html` |
| S3 access docs | `https://documentation.dataspace.copernicus.eu/APIs/S3.html` |

Free registration required. Authentication uses OAuth2 with `client_id: "cdse-public"`. The new STAC API (v1.1.0) supports `pystac-client` queries with CQL2 filtering. Collection ID: `sentinel-2-l2a`.

### Google Earth Engine — server-side computation powerhouse

| Resource | URL |
|---|---|
| Signup | `https://code.earthengine.google.com/register` |
| Python API guide | `https://developers.google.com/earth-engine/guides/python_install` |
| Data catalog | `https://developers.google.com/earth-engine/datasets/catalog` |

Free for noncommercial use. **Key advantage: all computation runs on Google's servers**, meaning zero local RAM usage. Collection IDs: `COPERNICUS/S2_SR_HARMONIZED` (Sentinel-2), `LANDSAT/LC08/C02/T1_L2` (Landsat 8), `LANDSAT/LC09/C02/T1_L2` (Landsat 9). Cloud masking uses `GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED` for Sentinel-2 and QA_PIXEL bitmask for Landsat.

### NASA HLS — the cross-sensor solution

| Resource | URL |
|---|---|
| STAC catalog | `https://cmr.earthdata.nasa.gov/stac/LPCLOUD` |
| Earthdata login (free) | `https://urs.earthdata.nasa.gov/` |
| HLS project page | `https://hls.gsfc.nasa.gov/` |
| GitHub resources | `https://github.com/nasa/HLS-Data-Resources` |

**Collections:** `HLSL30.v2.0` (Landsat 30 m) and `HLSS30.v2.0` (Sentinel-2 harmonized to 30 m). The Harmonized Landsat Sentinel dataset solves the cross-sensor problem by applying BRDF normalization, bandpass adjustment, and spatial co-registration to both sensors on the same **30 m MGRS grid**. This yields observations every **2–3 days**, dramatically improving cloud-free coverage. Use the `earthaccess` Python package for seamless authentication.

### Can Sentinel-2 and Landsat be analyzed together?

**Yes, and NASA HLS is purpose-built for this.** Without HLS, combining the sensors requires resampling Sentinel-2 from 10 m to 30 m (or vice versa), aligning spectral bands (Landsat OLI B5 NIR ≈ Sentinel-2 B8A, not B8), and applying cross-calibration coefficients. **HLS eliminates all of these steps.** For independent analysis, keep sensors separate and compare derived indices rather than raw reflectance. The recommended approach: use HLS for time series analysis (harmonized, consistent), and native Sentinel-2 at 10 m for the alert system (maximum spatial detail).

---

## 2. Vegetation indices: moisture beats greenness for detecting clearing

### Band comparison between Sentinel-2 and Landsat 8/9

| Purpose | Sentinel-2 | λ (nm) | Resolution | Landsat 8/9 | λ (nm) | Resolution |
|---|---|---|---|---|---|---|
| Blue | B2 | 490 | 10 m | B2 | 482 | 30 m |
| Green | B3 | 560 | 10 m | B3 | 562 | 30 m |
| Red | B4 | 665 | 10 m | B4 | 655 | 30 m |
| Red Edge 1 | B5 | 705 | 20 m | — | — | — |
| Red Edge 2 | B6 | 740 | 20 m | — | — | — |
| Red Edge 3 | B7 | 783 | 20 m | — | — | — |
| NIR (broad) | B8 | 842 | 10 m | — | — | — |
| NIR (narrow) | B8A | 865 | 20 m | B5 | 865 | 30 m |
| SWIR 1 | B11 | 1610 | 20 m | B6 | 1610 | 30 m |
| SWIR 2 | B12 | 2190 | 20 m | B7 | 2200 | 30 m |

Landsat B5 aligns spectrally with Sentinel-2 **B8A** (narrow NIR), not B8 (broad NIR). Sentinel-2's three red-edge bands (B5/B6/B7) have no Landsat equivalent.

### Complete index reference

**NDVI** = (NIR − RED) / (NIR + RED)
- S2: (B8 − B4) / (B8 + B4) at 10 m | Landsat: (B5 − B4) / (B5 + B4) at 30 m
- Most widely used but **least reliable for deforestation** in seasonally deciduous biomes — Caatinga NDVI drops 0.30–0.50 during normal dry season

**EVI2** = 2.5 × (NIR − RED) / (NIR + 2.4 × RED + 1)
- S2: 2.5 × (B8 − B4) / (B8 + 2.4 × B4 + 1) | Landsat: 2.5 × (B5 − B4) / (B5 + 2.4 × B4 + 1)
- Preferred over EVI (no blue band needed, avoids atmospheric noise); better sensitivity in dense canopy

**NDMI** = (NIR − SWIR1) / (NIR + SWIR1)
- S2: (B8A − B11) / (B8A + B11) at 20 m | Landsat: (B5 − B6) / (B5 + B6) at 30 m
- **Best single index for deforestation detection** — canopy moisture loss persists even when deciduous trees drop leaves naturally (roots retain moisture)

**NBR** = (NIR − SWIR2) / (NIR + SWIR2)
- S2: (B8A − B12) / (B8A + B12) at 20 m | Landsat: (B5 − B7) / (B5 + B7) at 30 m
- Excellent for fire-related clearing; dNBR = NBR_pre − NBR_post quantifies burn severity (>0.27 = low severity, >0.66 = high severity)

**SAVI** = 1.5 × (NIR − RED) / (NIR + RED + 0.5)
- S2: 1.5 × (B8 − B4) / (B8 + B4 + 0.5) | Landsat: 1.5 × (B5 − B4) / (B5 + B4 + 0.5)
- Soil-adjusted; useful in sparse Caatinga where bare soil contributes significantly to pixel reflectance

**BSI** = ((SWIR1 + RED) − (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))
- S2: ((B11 + B4) − (B8 + B2)) / ((B11 + B4) + (B8 + B2)) | Landsat: ((B6 + B4) − (B5 + B2)) / ((B6 + B4) + (B5 + B2))
- High values indicate exposed soil; confirms clearing when combined with vegetation index drops

**NDFI** = (GV_shade − (NPV + Soil)) / (GV_shade + NPV + Soil) where GV_shade = GV / (1 − Shade)
- Requires spectral mixture analysis using all optical bands (B2–B7 for Landsat, B2/B3/B4/B8A/B11/B12 for Sentinel-2)
- **Gold standard used by Brazil's INPE** — intact forest NDFI > 0.75, degraded 0–0.75, deforested < 0

### Recommended index strategy for Chapada do Araripe

The optimal combination for this Cerrado/Caatinga transition zone uses **NDMI as the primary detection index** (least affected by seasonal leaf drop), **NBR as fire-clearing detector**, **BSI as clearing confirmation**, and **EVI2 for long-term monitoring**. Avoid relying solely on NDVI — its seasonal amplitude in Caatinga (0.15 dry to 0.70 wet) overlaps heavily with deforestation signals.

---

## 3. Seasonal dynamics that determine system design

The Chapada do Araripe's climate creates the system's central technical challenge. **The rainy season runs from November/December through March/April** (peak January–April), with a prolonged dry season from May through October. Annual rainfall varies from ~600 mm in Caatinga lowlands to ~1000 mm on the Araripe plateau due to orographic lift.

### NDVI ranges by land cover and season

| Land cover | Wet season NDVI | Dry season NDVI |
|---|---|---|
| Dense cerradão | 0.65–0.85 | 0.40–0.60 |
| Cerrado sensu stricto | 0.55–0.70 | 0.30–0.50 |
| Intact Caatinga | 0.50–0.70 | 0.15–0.30 |
| Degraded Caatinga | 0.30–0.50 | 0.10–0.20 |
| Recently deforested | 0.10–0.25 | 0.05–0.15 |
| Bare soil | 0.00–0.15 | 0.00–0.10 |

**Best baseline acquisition window:** February–April for Caatinga (maximum vegetation contrast), May–June for Cerrado (still partly green, fewer clouds). Avoid August–October entirely for Caatinga analysis — leafless trees are indistinguishable from cleared land using greenness indices.

### Drought year handling

El Niño events cause severe rainfall deficits across northeastern Brazil (documented: 1997–98, 2012–16, 2023–24). NDVI drops dramatically during drought, mimicking degradation. The system must cross-reference **CHIRPS rainfall data** (`https://data.chc.ucsb.edu/products/CHIRPS-2.0/`, also via GEE as `UCSB-CHG/CHIRPS/DAILY`) to compute a Standardized Precipitation Index (SPI). When 3-month SPI falls below −1.0, the system should **widen z-score thresholds by 0.5σ** to avoid false positives. Building 12 monthly baselines from 3–5 years of data, each storing per-pixel mean and standard deviation, enables the system to compare new imagery against the matching month's historical norm.

---

## 4. Repository structure and Python dependencies

```
deforestation-monitor/
├── app.py                          # Streamlit entry point
├── requirements.txt
├── .env.example
├── .github/workflows/
│   └── update_data.yml             # Weekly cron job
├── config/
│   ├── settings.py                 # AOI bounds, thresholds, paths
│   └── bands.py                    # Band mappings S2/Landsat/HLS
├── src/
│   ├── acquisition/
│   │   ├── stac_client.py          # Query STAC APIs (Element84, PC, NASA)
│   │   └── download.py             # Stream/download COG bands
│   ├── processing/
│   │   ├── cloud_mask.py           # SCL (S2) / QA_PIXEL (Landsat) masking
│   │   ├── indices.py              # NDVI, NDMI, NBR, EVI2, BSI computation
│   │   └── composite.py            # Monthly/seasonal median composites
│   ├── detection/
│   │   ├── baseline.py             # Build/load seasonal baselines (mean+std)
│   │   ├── change_detect.py        # Z-score + delta thresholding
│   │   └── alerts.py               # Vectorize alerts, classify confidence
│   ├── timeseries/
│   │   ├── builder.py              # Multi-year pixel/regional time series
│   │   ├── seasonal.py             # STL decomposition, harmonic fitting
│   │   └── trends.py               # Mann-Kendall, breakpoint detection
│   └── visualization/
│       ├── maps.py                 # Leafmap/Folium interactive maps
│       ├── charts.py               # Plotly time series, seasonal charts
│       └── dashboard.py            # Streamlit layout components
├── data/
│   ├── aoi/                        # Study area shapefiles (GeoJSON)
│   ├── baselines/                  # Monthly baseline COGs (12 months × indices)
│   ├── alerts/                     # Alert GeoJSONs (timestamped)
│   └── timeseries/                 # SQLite database for time series stats
├── scripts/
│   ├── build_baseline.py           # One-time: compute multi-year baselines
│   ├── run_detection.py            # Weekly: detect changes, generate alerts
│   └── upload_to_r2.py             # Upload COGs to Cloudflare R2
├── tests/
│   ├── test_indices.py
│   ├── test_detection.py
│   └── test_acquisition.py
├── notebooks/
│   └── exploration.ipynb
└── docs/
    └── methodology.md
```

### Core Python dependencies

```
# requirements.txt
pystac-client>=0.8.0        # https://pypi.org/project/pystac-client/
planetary-computer>=1.0.0   # https://pypi.org/project/planetary-computer/
earthaccess>=0.12.0         # https://pypi.org/project/earthaccess/
rasterio>=1.3.10            # https://pypi.org/project/rasterio/
rioxarray>=0.17.0           # https://pypi.org/project/rioxarray/
xarray>=2024.1.0            # https://pypi.org/project/xarray/
geopandas>=1.0.0            # https://pypi.org/project/geopandas/
shapely>=2.0.0              # https://pypi.org/project/shapely/
numpy>=1.26.0               # https://pypi.org/project/numpy/
scipy>=1.14.0               # https://pypi.org/project/scipy/
dask[complete]>=2024.1.0    # https://pypi.org/project/dask/
scikit-learn>=1.5.0         # https://pypi.org/project/scikit-learn/
statsmodels>=0.14.0         # https://pypi.org/project/statsmodels/
streamlit>=1.40.0           # https://pypi.org/project/streamlit/
folium>=0.18.0              # https://pypi.org/project/folium/
leafmap>=0.40.0             # https://pypi.org/project/leafmap/
streamlit-folium>=0.23.0    # https://pypi.org/project/streamlit-folium/
plotly>=5.24.0              # https://pypi.org/project/plotly/
altair>=5.4.0               # https://pypi.org/project/altair/
stackstac>=0.5.1            # https://pypi.org/project/stackstac/
odc-stac>=0.3.10            # https://pypi.org/project/odc-stac/
rio-tiler>=7.0.0            # https://pypi.org/project/rio-tiler/
duckdb>=1.1.0               # https://pypi.org/project/duckdb/
python-dotenv>=1.0.0        # https://pypi.org/project/python-dotenv/
loguru>=0.7.0               # https://pypi.org/project/loguru/
tqdm>=4.66.0                # https://pypi.org/project/tqdm/
click>=8.1.0                # https://pypi.org/project/click/
```

---

## 5. Alert system architecture: from satellite to dashboard in six stages

The alert pipeline runs weekly on GitHub Actions, processing the most recent cloud-free imagery against seasonal baselines.

**Stage 1 — Query recent imagery.** `stac_client.py` queries Element84 Earth Search for Sentinel-2 L2A scenes from the past 16 days with < 20% cloud cover over the bounding box `[-40, -8, -39, -7]`. Fallback queries Planetary Computer if Element84 returns no results.

**Stage 2 — Stream and mask.** `cloud_mask.py` reads only the required bands via HTTP range requests from COGs (no full download). For Sentinel-2, the SCL (Scene Classification Layer) band masks clouds (class 8–9), cloud shadows (class 3), and cirrus (class 10). For Landsat, QA_PIXEL bit 3 (cloud) and bit 4 (shadow) are used.

**Stage 3 — Compute indices.** `indices.py` calculates NDMI, NBR, EVI2, and BSI from the masked reflectance bands. All computations use `xarray` with dask-backed lazy evaluation to manage memory.

**Stage 4 — Compare against baseline.** `baseline.py` loads the pre-computed monthly baseline (mean μ and standard deviation σ) matching the current calendar month. The z-score is computed per pixel: `z = (current - μ) / σ`. Delta values are also computed: `Δ = current - μ`.

**Stage 5 — Detect and vectorize.** `change_detect.py` flags pixels where z < −2.0 AND Δ < −0.15 for NDMI. `alerts.py` vectorizes flagged pixels into polygons using `rasterio.features.shapes()`, filters patches smaller than 1 hectare, and classifies confidence:

- **High confidence:** z < −3.0 AND Δ < −0.20 in both NDMI and NBR
- **Medium confidence:** z < −2.5 OR Δ < −0.15 in at least one moisture index
- **Low confidence:** z < −2.0 in any single index

**Stage 6 — Store and publish.** Alert polygons are saved as GeoJSON in `data/alerts/`, time series statistics are appended to the SQLite database, and COG outputs are uploaded to Cloudflare R2. The Streamlit app reads these pre-computed assets on each page load.

### Long-term time series analysis

The time series module builds multi-year NDVI/NDMI/EVI2 trajectories per pixel or region using HLS data (2–3 day revisit). Gap-filling uses linear interpolation for gaps under 30 days and same-DOY seasonal mean replacement for longer gaps. **STL decomposition** separates trend, seasonal, and residual components. **Mann-Kendall tests** with Sen's slope detect statistically significant trends. For breakpoint detection, the system implements a simplified BFAST Monitor approach: fit a harmonic model (two harmonics) to the historical period, then flag observations exceeding 3× RMSE of the fitted model on three consecutive dates.

---

## 6. Interactive maps and visualization approach

### Mapping stack

**Leafmap** (`https://leafmap.org/`) is the primary mapping library — it unifies Folium, ipyleaflet, kepler.gl, and pydeck backends while providing native Streamlit support, STAC layer integration (`m.add_stac_layer()`), COG streaming (`m.add_cog_layer(url, colormap="RdYlGn")`), split-panel before/after comparison (`m.split_map()`), and time slider animations. **Folium** (`https://python-visualization.github.io/folium/latest/`) handles GeoJSON polygon overlays with style functions for color-coding alert confidence. Integration with Streamlit uses **streamlit-folium** (`https://pypi.org/project/streamlit-folium/`).

### Free basemap tiles

| Provider | Tile URL |
|---|---|
| OpenStreetMap | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` |
| Esri World Imagery | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` |
| CartoDB Positron | `https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png` |
| CartoDB Dark Matter | `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png` |

A complete browsable catalog of free tile providers is available at `https://leaflet-extras.github.io/leaflet-providers/preview/`.

### Time series visualization

**Plotly** (`https://plotly.com/python/time-series/`) renders interactive time series with hover tooltips, range sliders, and animation frames via `st.plotly_chart()`. Seasonal patterns display as mean lines with `fill='tonexty'` confidence bands showing ±1σ and ±2σ ranges. Before/after satellite views use Leafmap's split-panel maps with a draggable divider.

### Dashboard layout

The Streamlit app uses tabs: Overview (key metrics via `st.metric()` — total hectares deforested, alert count, trend direction), Map (interactive Leafmap with alert polygons and COG overlays), Time Series (Plotly charts of vegetation indices with seasonal decomposition), and Settings (date range, index selection, confidence filter). Sidebar filters control all views simultaneously.

---

## 7. Hosting and storage at zero cost

### Primary hosting: Hugging Face Spaces

| Resource | URL |
|---|---|
| Spaces hub | `https://huggingface.co/spaces` |
| Pricing | `https://huggingface.co/pricing` |

The free tier provides **2 vCPU, 16 GB RAM, and 50 GB disk** — vastly more generous than Streamlit Community Cloud's 1 GB RAM. Supports Streamlit SDK natively. Spaces sleep after 48 hours of inactivity but wake on access. This is the recommended primary host because 16 GB RAM comfortably handles loading pre-computed GeoJSON alerts and streaming COG tiles.

### Secondary hosting: Streamlit Community Cloud

| Resource | URL |
|---|---|
| Deploy page | `https://share.streamlit.io/` |
| Documentation | `https://docs.streamlit.io/deploy/streamlit-community-cloud` |

Free for up to 3 apps from public GitHub repos. **1 GB RAM limit** is tight but workable if all processing is pre-computed. Apps sleep after ~7 days of inactivity.

### Static content: GitHub Pages

For hosting exported Folium HTML maps or project documentation at `https://pages.github.com/`.

### Storage architecture (total: $0/month)

| Data type | Storage solution | Limits |
|---|---|---|
| Alert GeoJSONs (< 50 MB) | GitHub repository | 5 GB repo recommended max |
| Time series SQLite DB (< 100 MB) | GitHub repository | Committed directly |
| Processed COGs (< 10 GB) | Cloudflare R2 | **10 GB free, zero egress** (`https://www.cloudflare.com/developer-platform/products/r2/`) |
| Large versioned assets | GitHub Releases | 2 GB per file (`https://docs.github.com/en/repositories/releasing-projects-on-github`) |
| Backup rasters | Backblaze B2 | 10 GB free (`https://www.backblaze.com/cloud-storage`) |

**Cloudflare R2 is the critical enabler** — its S3-compatible API with zero egress fees means COGs can be streamed directly to Leafmap without bandwidth costs.

---

## 8. Automated weekly processing via GitHub Actions

```yaml
name: Weekly Deforestation Detection
on:
  schedule:
    - cron: '0 6 * * 1'  # Every Monday 6:00 UTC
  workflow_dispatch:       # Manual trigger

jobs:
  detect:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
      - run: pip install -r requirements.txt
      - name: Run detection pipeline
        env:
          CDSE_USERNAME: ${{ secrets.CDSE_USERNAME }}
          CDSE_PASSWORD: ${{ secrets.CDSE_PASSWORD }}
        run: python scripts/run_detection.py
      - name: Upload COGs to Cloudflare R2
        env:
          R2_ACCESS_KEY: ${{ secrets.R2_ACCESS_KEY }}
          R2_SECRET_KEY: ${{ secrets.R2_SECRET_KEY }}
        run: python scripts/upload_to_r2.py
      - name: Commit alerts and time series
        run: |
          git config user.name "github-actions[bot]"
          git add data/alerts/ data/timeseries/
          git diff --staged --quiet || git commit -m "Update $(date +%Y-%m-%d)"
          git push
```

GitHub Actions documentation: `https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule`

**Free tier for public repos: unlimited minutes.** Runners provide ~7 GB RAM and 2-core CPU with a 6-hour job timeout — more than sufficient for processing a single Sentinel-2 tile covering the AOI. For private repos, the limit is 2,000 minutes/month. **Important:** workflows auto-disable after 60 days of repo inactivity — ensure periodic commits or use a keep-alive action.

### Change detection algorithms implemented in the pipeline

The primary algorithm combines **z-score anomaly detection** with **multi-index confirmation**. For each new image, per-pixel z-scores are computed against the matching monthly baseline for NDMI, NBR, and EVI2. Pixels flagged by at least two indices (z < −2.0) are classified as potential deforestation. A secondary **simple differencing** approach compares the current image against the most recent cloud-free image from the same season in the previous year, using ΔNDMI < −0.15 as the threshold.

For distinguishing fire from mechanical clearing: dNBR > 0.27 with NBR post-event < 0.1 indicates fire; mechanical clearing shows higher SWIR reflectance (higher BSI) without the characteristic charcoal signature.

---

## 9. Performance optimization for free-tier constraints

The fundamental design principle: **never process raw satellite imagery in the web application**. All heavy computation happens on GitHub Actions; the Streamlit app only visualizes pre-computed results.

**COG streaming** is the key enabler. Cloud Optimized GeoTIFFs support HTTP range requests, so Leafmap's `add_cog_layer()` downloads only the tiles visible at the current zoom level — a 500 MB GeoTIFF might consume only 2–5 MB of RAM. Create COGs with: `gdal_translate -of COG -co COMPRESS=DEFLATE input.tif output_cog.tif`. COG specification: `https://cogeo.org/`.

**Windowed raster processing** on GitHub Actions prevents memory spikes. Instead of loading entire scenes (~5 GB uncompressed), process in 512×512 pixel blocks using `rasterio`'s windowed reading:

```python
import rasterio
from rasterio.windows import Window

with rasterio.open(src_path) as src:
    for ji, window in src.block_windows(1):
        data = src.read(window=window)
        # Process block...
```

**Dask lazy evaluation** enables out-of-core computation when building multi-year composites:

```python
import xarray as xr
ds = xr.open_dataset("large.tif", engine="rasterio", chunks={"x": 512, "y": 512})
ndmi = (ds.nir - ds.swir1) / (ds.nir + ds.swir1)
result = ndmi.compute()  # Processes chunk by chunk
```

**Streamlit caching** is essential — `@st.cache_data(ttl=3600)` for data loading functions and `@st.cache_resource` for database connections and map objects. Keep total committed data under 500 MB; use GitHub Releases or Cloudflare R2 for anything larger.

---

## Conclusion: a practical zero-cost monitoring architecture

This system achieves continuous deforestation monitoring without spending a single dollar by exploiting three key free resources: **Element84/Planetary Computer STAC APIs** for satellite data, **GitHub Actions** for weekly computation, and **Hugging Face Spaces** for hosting. The technical design separates heavy processing (offline, on GitHub runners) from lightweight visualization (online, on the dashboard), making the 16 GB RAM ceiling on HF Spaces more than sufficient.

The most important design decision is choosing **NDMI and NBR over NDVI** as primary detection indices. In the Cerrado/Caatinga transition of Chapada do Araripe, seasonal NDVI variation (amplitude 0.30–0.50) frequently exceeds deforestation signals, while moisture-based indices maintain a clearer separation between natural phenology and actual clearing. Building season-aware baselines (12 monthly composites from 3–5 years of history) and implementing z-score anomaly detection with drought-year SPI adjustments addresses the region's extreme seasonality. The system detects clearings as small as ~1 hectare at Sentinel-2's 10–20 m resolution, with confidence classification that enables prioritized field verification—matching the approach of Brazil's own DETER near-real-time alert system but at a completely open and reproducible scale.