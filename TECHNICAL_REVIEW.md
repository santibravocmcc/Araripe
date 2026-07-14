# Technical Review: Chapada do Araripe Deforestation Monitoring System

**Version:** 2.0
**Date:** 2026-07-12
**Prepared for:** Specialist peer review (remote sensing, environmental monitoring)

---

## 0. What Changed in Version 2.0 (Following the Technical Audit)

This version incorporates the fixes and improvements from the technical audit (details and rationale in `AUDITORIA_TECNICA.md`; a plain-language explanation in `COMO_FUNCIONA.md`). The changes with the greatest scientific impact:

1. **Baseline rebuilt in reflectance, over 5 climatically "quiet" years {2017, 2019, 2021, 2022, 2025}** -- replacing the 2023--2025 window, which was contaminated by the two strongest El Nino events of the period (2023/2024). Computed on **Google Earth Engine** (true per-month median, `S2_SR_HARMONIZED` collection).
2. **EVI2 scale fix** (reflectance `DN·scale + offset`, per-scene/sensor) coupled to the baseline rebuild via the `REFLECTANCE_SCALING` flag (now `True`). Eliminates the ~45.7% of EVI2 values outside [-1, 1] that had motivated the artificial *cap* at 1.0.
3. **Temporal persistence filter** (>=2 consecutive observations with spatial overlap) -- reduces wet-season commission (~-87% over the historical record).
4. **Exact-geometry confidence mask** for each polygon (no longer the *bounding-box* window), preventing confidence from being inherited from neighboring polygons.
5. **Land-cover integration (MapBiomas)** into the analysis: each alert is annotated by dominant class/group, with **both collections selectable** (10 m Collection 2 and 30 m Collection 10), each with its own reclassification table.
6. **Drought adjustment (SPI/CHIRPS) confirmed active** by default and hardened (dropping not-yet-published months).
7. **Dead configuration removed** (Copernicus/CDSE) and **previously unexercised code wired in** (Landsat/HLS as optional extra sources; fire vs. mechanical discrimination).
8. **Production path via Google Earth Engine + Cloudflare R2**: baselines published to R2 and fetched on demand by CI; 2026 detection reprocessed via GEE (see §9.3). Public dashboard migrated from Streamlit to a **static site**.

The remainder of this document has been updated to reflect this state. Where a v1.1 statement became obsolete, the text was corrected in place.

---

## 1. Executive Summary

The Chapada do Araripe Deforestation Monitoring System is a near-real-time change detection pipeline designed to generate twice-weekly deforestation and degradation alerts for the Chapada do Araripe region in northeastern Brazil. The system ingests multispectral satellite imagery (Sentinel-2 L2A as the primary source; Landsat 8/9 Collection 2 and NASA HLS as optional extra sources) via open STAC APIs, computes moisture- and vegetation-sensitive spectral indices (NDMI, NBR, EVI2), and detects anomalous vegetation loss through z-score deviation from monthly baselines. The baselines are built from a reference window of **5 climatically "quiet" years -- {2017, 2019, 2021, 2022, 2025}** -- in **surface reflectance**. The 2026 calendar year onwards is reserved exclusively for the detection stage, ensuring a clean comparison against a frozen baseline.

The system is designed to operate at zero recurring cost. Twice-weekly automation uses **GitHub Actions**; baselines are stored as Cloud Optimized GeoTIFF (COG) files on **Cloudflare R2** and fetched on demand by CI before detection; the **public dashboard is a static site** (Cloudflare Pages), having replaced the original Streamlit/Hugging Face dashboard. Detection outputs are vectorized alert polygons in GeoJSON format, classified into three confidence tiers (high, medium, low) with a minimum mapping unit of 1 hectare, annotated with the land-cover class (MapBiomas) and a temporal-persistence status.

**Current operational status:** The full codebase is implemented and functional. The monthly baselines (**72 COG files, in reflectance**) were rebuilt via Google Earth Engine for all 12 months across three spectral indices and published to R2. The detection history had accumulated **7 alert files / 17,528 polygons** (Nov 2025 to Apr 2026); the **2026 detection is being reprocessed via GEE** with the new baseline (see §9.3). The CHIRPS precipitation data **is present** (2021-03 to 2026-03) and SPI-based drought adjustment **is active**. The twice-weekly automation pipeline has been hardened (it fetches baselines from R2, with the R2 gate fixed) and now depends only on enabling Actions and setting the repository *secrets*.

---

## 2. Study Area

### 2.1 Geographic Context

The Chapada do Araripe is a sedimentary plateau in northeastern Brazil, straddling the borders of Ceara, Pernambuco, and Piaui states. It rises to approximately 800--1,000 m elevation above the surrounding semi-arid lowlands of the Sertao. The area of interest (AOI) is defined by the bounding box:

- **West:** -40.0 deg
- **South:** -8.0 deg
- **East:** -39.0 deg
- **North:** -7.0 deg

This corresponds to an area of approximately 111 km x 111 km (roughly 12,321 km^2), projected in **EPSG:32724** (WGS 84 / UTM zone 24S). The AOI polygon is stored in `data/aoi/chapada_araripe.gpkg`.

### 2.2 Ecological Significance

The Chapada do Araripe occupies a biogeographic transition zone where three major Brazilian biomes converge:

- **Cerrado** (Brazilian savanna) on the plateau top, with dense cerrado sensu stricto and campo cerrado formations.
- **Caatinga** (seasonally dry tropical forest/shrubland) on the lower slopes and surrounding lowlands, characterized by deciduous and semi-deciduous vegetation with extreme seasonal leaf-off behavior.
- **Atlantic Forest** relicts in humid enclaves on the eastern slopes, sustained by orographic rainfall.

The region hosts two major conservation units:

- **FLONA Araripe** (Floresta Nacional do Araripe) -- one of the first national forests established in Brazil (1946), covering approximately 38,600 ha.
- **APA Chapada do Araripe** (Area de Protecao Ambiental) -- an environmental protection area of approximately 1,063,000 ha encompassing the broader plateau and surroundings.

### 2.3 Monitoring Rationale

The Chapada do Araripe faces multiple threats that justify continuous satellite-based monitoring:

1. **Deforestation for agriculture and pasture expansion**, particularly along the plateau edges and in the Caatinga lowlands.
2. **Illegal selective logging** for charcoal production and construction materials.
3. **Wildfires**, which are frequent during the dry season (August--October) and exacerbated by El Nino events.
4. **Urban encroachment**, particularly near the cities of Crato, Juazeiro do Norte, and Barbalha.
5. **Water resource degradation** -- the Araripe plateau is a critical recharge zone for springs that supply over 1 million people.

The deciduous phenology of Caatinga vegetation poses a particular challenge for optical remote sensing: natural seasonal leaf-off can mimic deforestation signals when using greenness-based indices such as NDVI. This was a primary design consideration for the monitoring system.

---

## 3. Data Sources and Acquisition

### 3.1 Satellite Imagery

The system is designed to ingest imagery from three complementary satellite programs, providing spatial and temporal redundancy.

#### 3.1.1 Sentinel-2 L2A (Primary Source)

- **Satellites:** Sentinel-2A, 2B, and 2C (ESA Copernicus)
- **Processing level:** Level-2A (bottom-of-atmosphere / surface reflectance)
- **Spatial resolution:** 10 m (B2, B3, B4, B8), 20 m (B5, B6, B7, B8A, B11, B12)
- **Revisit time:** ~5 days at the equator (with 3 satellites)
- **Bands used for index computation:**
  - B4 (Red, 665 nm) -- for EVI2
  - B8 (NIR broad, 842 nm) -- for EVI2
  - B8A (NIR narrow, 865 nm) -- for NDMI, NBR
  - B11 (SWIR1, 1610 nm) -- for NDMI
  - B12 (SWIR2, 2190 nm) -- for NBR
  - SCL (Scene Classification Layer) -- for cloud masking
- **Collection ID:** `sentinel-2-l2a` (Element84), `sentinel-2-c1-l2a` (Copernicus)

The system operates at 20 m resolution for the detection pipeline, matching the native resolution of the SWIR bands used by the primary indices (NDMI, NBR).

#### 3.1.2 Landsat 8/9 Collection 2

- **Processing level:** Collection 2, Level 2 (surface reflectance)
- **Spatial resolution:** 30 m (all reflectance bands)
- **Revisit time:** ~8 days (combined Landsat 8 + 9)
- **Cloud masking:** QA_PIXEL band (bitwise flags, Bit 3 = cloud, Bit 4 = cloud shadow)
- **Collection ID:** `landsat-c2-l2`

#### 3.1.3 NASA HLS (Harmonized Landsat Sentinel)

- **Products:** HLSL30 v2.0 (Landsat-derived) and HLSS30 v2.0 (Sentinel-2-derived)
- **Spatial resolution:** 30 m (harmonized to common grid)
- **Cloud masking:** Fmask band (Bit 1 = cloud, Bit 2 = adjacent cloud/shadow, Bit 3 = cloud shadow)
- **Authentication:** Requires NASA Earthdata credentials (via `earthaccess` library)

### 3.2 STAC API Endpoints and Fallback Chain

Data acquisition is implemented in `src/acquisition/stac_client.py` using the `pystac-client` library. The system queries multiple STAC API endpoints with an automatic fallback strategy:

| Priority | Provider | URL | Authentication |
|----------|----------|-----|----------------|
| 1 | Element84 Earth Search | `https://earth-search.aws.element84.com/v1` | None required |
| 2 | Microsoft Planetary Computer | `https://planetarycomputer.microsoft.com/api/stac/v1` | SAS token signing via `planetary-computer` package |
| 3 | NASA CMR STAC | `https://cmr.earthdata.nasa.gov/stac/LPCLOUD` | NASA Earthdata login |
| 4 | ~~Copernicus Data Space~~ | ~~`https://stac.dataspace.copernicus.eu/v1`~~ | **Removed in Phase 2** — it was dead config (no code consumed it; there was no real fallback despite older docs). Sentinel-1 SAR via CDSE is a roadmap item (see ROADMAP.md) |

The fallback logic for Sentinel-2 queries is: Element84 first; if zero results, Planetary Computer. Landsat and HLS can be added as extra observation sources via `run_detection.py --extra-sources landsat,hls` (Phase 2, Task 7.1).

### 3.3 Query Parameters

- **Maximum cloud cover:** 20% (`MAX_CLOUD_COVER`)
- **Search window:** 16 days (`SEARCH_DAYS_BACK`)
- **Maximum items per query:** 50 (`MAX_ITEMS_PER_SEARCH`)
- **Minimum clear pixel percentage for baseline scenes:** 10% (`MIN_CLEAR_PERCENTAGE_BASELINE`)

### 3.4 CHIRPS Precipitation Data

Drought adjustment relies on monthly precipitation estimates from the **Climate Hazards Group InfraRed Precipitation with Station data (CHIRPS)** version 2.0:

- **Source URL:** `https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs`
- **Resolution:** 0.05 deg (~5.5 km)
- **Temporal coverage:** 1981--present
- **Cache directory:** `data/chirps/`
- **Current status (updated in the 2026-07 audit, revised in Phase 2):** The local cache `data/chirps/` holds **61 monthly global files** from 2021-03 to 2026-03 (count verified in Phase 2; Phase 1 said "~62"). Not tracked in Git, hence absent from the remote repo. The download was hardened during the audit (backoff retry, HTTP range resume, integrity check) in `src/acquisition/chirps.py` and the new `scripts/download_baseline_data.py`. **SPI-based drought adjustment is already ACTIVE by default** in `scripts/run_detection.py` (it calls `get_current_spi` and passes it to `detect_deforestation`) — Phase 2 confirmed this was not a "to-enable" item, and hardened it further by dropping not-yet-published recent CHIRPS months.

---

## 4. Spectral Indices

Three spectral indices form the core of the detection pipeline. The selection prioritizes moisture-sensitive indices over pure greenness indices, specifically to address the challenge of Caatinga deciduousness.

### 4.1 NDMI -- Normalized Difference Moisture Index (Primary)

**Formula:**

    NDMI = (NIR - SWIR1) / (NIR + SWIR1)

**Band mapping:**
- Sentinel-2: (B8A - B11) / (B8A + B11) at 20 m
- Landsat: (B5 - B6) / (B5 + B6) at 30 m

**Physical meaning:** NDMI quantifies the water content of vegetation canopies by exploiting the contrast between NIR reflectance (high for healthy vegetation) and SWIR1 reflectance (absorbed by leaf water). Typical values range from -0.5 (bare soil/rock) to +0.6 (dense, well-hydrated vegetation).

**Why chosen for Caatinga/Cerrado:** NDMI is sensitive to canopy moisture stress independently of greenness. Deciduous Caatinga species lose their leaves during the dry season but the woody structure retains a different moisture signature than cleared or burned land. NDVI, by contrast, drops dramatically during natural leaf-off, creating false deforestation signals. NDMI shows a smaller seasonal amplitude in intact vegetation, making it more reliable for distinguishing anthropogenic clearing from phenological change.

**Role in the pipeline:** Primary detection index. Required for medium- and high-confidence alerts. Validated as clean in baseline data (values within [-0.56, 0.55], mean 0.058).

**Implementation:** `src/processing/indices.py::ndmi()`

### 4.2 NBR -- Normalized Burn Ratio (Primary)

**Formula:**

    NBR = (NIR - SWIR2) / (NIR + SWIR2)

**Band mapping:**
- Sentinel-2: (B8A - B12) / (B8A + B12) at 20 m
- Landsat: (B5 - B7) / (B5 + B7) at 30 m

**Physical meaning:** NBR is structurally similar to NDMI but uses the longer-wavelength SWIR2 band (2190 nm), which is more sensitive to soil moisture and charcoal/ash signatures. It is the standard index for burn severity mapping (dNBR).

**Why chosen:** NBR complements NDMI by providing sensitivity to fire-related clearing, which is a major driver of vegetation loss in the Araripe region. The SWIR2 band also penetrates thin smoke layers better than visible bands, making NBR more robust during active fire seasons.

**Role in the pipeline:** Primary detection index alongside NDMI. Both must flag a pixel for high-confidence classification. Also used for fire vs. mechanical clearing discrimination via dNBR (delta NBR). Validated as clean in baseline data (values within [-0.58, 0.75], mean 0.279).

**Additional thresholds for fire detection:**
- dNBR > 0.27: Low-severity burn (`DNBR_LOW_SEVERITY`)
- dNBR > 0.66: High-severity burn (`DNBR_HIGH_SEVERITY`)
- Post-fire NBR < 0.1: Confirms fire signature (`NBR_POST_FIRE_THRESHOLD`)

**Implementation:** `src/processing/indices.py::nbr()`, `src/processing/indices.py::dnbr()`

### 4.3 EVI2 -- Enhanced Vegetation Index 2 (Confirmatory)

**Formula:**

    EVI2 = 2.5 * (NIR - RED) / (NIR + 2.4 * RED + 1)

**Band mapping:**
- Sentinel-2: 2.5 * (B8 - B4) / (B8 + 2.4 * B4 + 1) at 10 m
- Landsat: 2.5 * (B5 - B4) / (B5 + 2.4 * B4 + 1) at 30 m

**Physical meaning:** EVI2 is a two-band simplification of the full EVI (which requires the blue band). The 2.5 scaling factor amplifies the vegetation signal, while the soil adjustment term (2.4 * RED + 1) reduces background soil reflectance effects. Unlike NDVI, EVI2 does not saturate in high-biomass canopies. Note that EVI2 is NOT bounded to [-1, 1] due to the 2.5 multiplier; however, values above ~1.0 are physically unrealistic for natural vegetation.

**Why chosen:** EVI2 provides a greenness-sensitive complement to the moisture-based NDMI and NBR. While it shares some of the deciduousness sensitivity of NDVI, it is less affected by atmospheric scattering and soil background. It can detect clearing that involves canopy removal without altering soil moisture (e.g., selective logging).

**Limitation (revised in v2.0):** The v1.1 validation found 45.7% of EVI2 pixels outside [-1, 1] (P99 = 1.74) and attributed this to thin cirrus. The audit showed that the **dominant cause was a units/scale issue**: acquisition added the BOA *offset* but **did not divide by 10000**, leaving the bands on the DN scale (~0--10000); because the "+1" term in the EVI2 formula assumes reflectance in [0, 1], the index inflated to ~1--2.5. NDMI and NBR, being pure ratios, are immune -- exactly the pattern observed. **Fix (v2.0):** metadata-driven conversion to reflectance (`DN·scale + offset`, per-scene/sensor), coupled to the baseline rebuild via `REFLECTANCE_SCALING = True`. After the fix, per-scene EVI2 falls at ~0% outside [-1, 1], **without** the artificial cap at 1.0 of v1.1. Thin-cirrus contamination can still marginally raise individual values, but it is no longer systematic.

**Role in the pipeline:** Confirmatory index. Can trigger low-confidence alerts independently but cannot elevate to medium or high confidence without NDMI or NBR agreement.

**Implementation:** `src/processing/indices.py::evi2()`

### 4.4 Why NDVI Was Deprioritized

Although NDVI is implemented in the codebase (`src/processing/indices.py::ndvi()`), it is not used in the detection pipeline. In Caatinga vegetation, NDVI drops by 0.3--0.5 units during the dry season (August--October) due to complete deciduousness, which would produce widespread false positive alerts. The Caatinga leaf-off months are explicitly defined in the configuration (`CAATINGA_LEAFOFF_MONTHS = [8, 9, 10]`).

### 4.5 Additional Indices Available

The following indices are implemented but used only for ancillary analysis, not for primary detection:

- **SAVI** (Soil-Adjusted Vegetation Index): `1.5 * (NIR - RED) / (NIR + RED + 0.5)`. Useful in sparse Caatinga where bare soil contributes to pixel reflectance.
- **BSI** (Bare Soil Index): `((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))`. Used to confirm clearing when combined with vegetation index drops, and in the fire vs. mechanical clearing discrimination module.

---

## 5. Baseline Construction

### 5.1 Design Approach

The detection system uses a per-month baseline approach: for each of the 12 calendar months, a pixel-wise statistical summary (central tendency and variability) is computed from multiple years of historical observations. This captures the phenological cycle of the vegetation, so that a January observation is compared against the historical January distribution rather than an annual mean.

### 5.2 Source Data

The current baselines (v2.0) were built on **Google Earth Engine (GEE)** from the `COPERNICUS/S2_SR_HARMONIZED` collection, which automatically harmonizes the reflectance *offset* introduced in Processing Baseline 04.00 (2022). The reference window is the set of **5 climatically "quiet" years: {2017, 2019, 2021, 2022, 2025}**, selected to exclude 2023 and 2024 -- the two strongest El Nino events in the recent record (see §5.5 and `AUDITORIA_TECNICA.md`, Task 3). The 2026 calendar year onwards is used only for detection. The source data:

- **Source:** Sentinel-2 L2A (`S2_SR_HARMONIZED`), **surface reflectance** (bands are divided by 10000 on the server, so the indices land on the correct physical scale).
- **Cloud mask:** clear SCL classes {2, 4, 5, 6, 7, 11}, applied per-pixel before compositing.
- **Spatial coverage:** the entire APA AOI (UTM tile mosaic done server-side).
- **CRS:** EPSG:32724 (UTM zone 24S), **Resolution:** 20 m.
- **Exported bands:** the 3 detection indices (NDMI, NBR, EVI2), each with monthly median and standard deviation.

> **Why GEE.** The streaming COG construction from the public S3 (`scripts/build_baseline.py`) is implemented and validated, but the real bottleneck was the **network** (S3 throttling from Brazil, ~1 MB/s), which made rebuilding the 60 composites locally infeasible. GEE computes the median on the server and exports only 12 small GeoTIFFs, working around that bottleneck. Scripts: `scripts/build_baseline_gee.py` / `docs/gee_baseline_cloudshell.py` (computation) and `scripts/split_gee_baselines.py` (slicing into the detector's 72 COGs). Step-by-step in `docs/BASELINE_GEE.md`.

### 5.3 Processing Pipeline

For each month, the baseline construction (on GEE) proceeds as follows:

1. **Temporal and spatial filter** -- The collection is filtered by the AOI and by the corresponding calendar months across the 5 selected years.
2. **Cloud mask + reflectance + indices** -- Each scene is masked with the SCL, converted to reflectance, and turned into NDMI/NBR/EVI2 (the same `prep()` preparation used in GEE detection, ensuring baseline and observation share the same scale).
3. **Temporal compositing** -- For each month, the pixel-wise **median** and **standard deviation** are computed over all scenes from the 5 years. The median is preferred over the mean for robustness to outliers (residual clouds, shadows). A true median is feasible on GEE (the whole stack stays on the server).
4. **Export** -- The monthly composites are exported to Google Drive and, on the local machine, sliced into 72 files `{index}_month{MM}_{mean,std}.tif` by `split_gee_baselines.py`, which restores the no-data sentinel and writes `nodata=NaN`.

> **No EVI2 cap.** Unlike v1.1 -- which applied `EVI2_CAP = 1.0` to contain the unrealistic EVI2 tail on the DN scale -- v2.0 does not need that clip: with correct reflectance, EVI2 already falls within the expected physical range (medians ~0.15--0.44, with the correct seasonality). The cap masked the units problem and artificially compressed the signal (see §4.3 and §8.2).

> **Note on streaming as a fallback.** The `scripts/build_baseline.py` path (streaming COG, median, `nodata=NaN`, disk guard, per-scene retry) remains available and fixed -- useful in CI (fast network) or as an alternative to GEE.

### 5.4 Output

The baseline construction produces **72 COG files**:

    3 indices (NDMI, NBR, EVI2) x 12 months x 2 statistics (mean/median, std) = 72 files

Naming convention: `{index}_month{MM}_mean.tif` and `{index}_month{MM}_std.tif`

All 72 baseline files have been successfully rebuilt (via GEE) and are stored in `data/baselines/` (and published to R2). Note: although the filenames use the suffix `_mean`, the actual statistic computed is the **median**. This naming convention was inherited from the original pipeline design and kept for compatibility with the loader (`load_baseline_pair`).

### 5.5 Temporal Depth

The configuration specifies a target of 5 years of history (`BASELINE_YEARS = 5`), now **achieved**: the v2.0 baselines use **{2017, 2019, 2021, 2022, 2025}**, with 2026 reserved for detection. **[2026-07 audit]** The previous window (2023--2025) contained exactly 2023 and 2024 -- the two strongest El Nino years in the recent record (ONI peaks +2.06 and +1.92) -- which biased the baseline toward drought conditions and raised the risk of **omission** (a pixel genuinely cleared in 2026 looks less anomalous against an already-dry "normal"). The script `scripts/select_baseline_years.py` reproducibly selects the recent years with the lowest climate anomaly (combining ENSO/ONI severity and CHIRPS precipitation anomaly over the AOI); the adopted decision was {2017, 2019, 2021, 2022, 2025}, excluding 2023 and 2024. See `AUDITORIA_TECNICA.md`, Task 3. Remaining caveat: 5 years may still not cover the full range of extreme inter-annual variability; extending the window as more quiet scenes are acquired is still recommended.

### 5.6 Visual Inspection of Baselines

For quick verification of spatial coverage and the phenological cycle, the script `scripts/plot_baselines.py` produces 4×3 grid figures (one per index and statistic) under `data/baselines/plots/`. Each panel shows the monthly index distribution with the APA Chapada do Araripe (yellow) and FLONA Araripe-Apodi (green) contours overlaid, plus the percentage of valid pixels in the title. These files are not deployed to the Hugging Face Space (the `data/baselines/` folder is excluded from sync) and are intended only for internal baseline auditing.

---

## 6. Change Detection Method

### 6.1 Overview

The detection method is a **z-score anomaly detection** approach with multi-index confirmation. A new satellite observation is compared pixel-by-pixel against the monthly baseline, and pixels showing statistically significant decreases in vegetation/moisture indices are flagged as potential deforestation alerts.

The detection logic is implemented in `src/detection/change_detect.py::detect_deforestation()`.

### 6.2 Z-Score Computation

For each index, the z-score measures how many standard deviations the current observation deviates from the historical baseline for the corresponding month:

    z = (current - baseline_mean) / baseline_std

Negative z-scores indicate a decrease in the index value (vegetation loss). The baseline_std is floored at a small value to prevent division by zero.

### 6.3 Delta (Absolute Change)

In addition to the z-score, an absolute delta is computed:

    delta = current - baseline_mean

This provides a secondary filter to prevent alerts from being triggered by small absolute changes that happen to have a large z-score (e.g., pixels with very low baseline variability).

### 6.4 Confidence Classification

Alerts are classified into three confidence tiers based on the agreement between z-score thresholds, delta thresholds, and the number of confirming indices. The classification follows a hierarchical approach where higher confidence levels take precedence.

#### High Confidence (confidence = 3)

Requirements (ALL must be met):
- z-score < -3.0 (`Z_THRESHOLD_HIGH`) in **both** NDMI and NBR
- delta < -0.20 (`DELTA_THRESHOLD_HIGH`) in **both** NDMI and NBR

This is the most conservative tier, requiring agreement between two independent moisture indices with both a large statistical departure and a substantial absolute change.

#### Medium Confidence (confidence = 2)

Requirements (ALL must be met):
- z-score < -2.5 (`Z_THRESHOLD_MEDIUM`) in **at least one** moisture index (NDMI or NBR)
- delta < -0.15 (`DELTA_THRESHOLD_MEDIUM`) in the same index

Both conditions are required to avoid flagging normal inter-annual variation that might cross a single threshold.

#### Low Confidence (confidence = 1)

Requirements (ALL must be met):
- z-score < -2.0 (`Z_THRESHOLD_LOW`) in **any single** index (NDMI, NBR, or EVI2)
- delta < -0.15 (`DELTA_THRESHOLD_LOW`) in the same index

### 6.5 Minimum Alert Area

Detected pixels are vectorized into connected-component polygons, and polygons with area below **1.0 hectare** (`MIN_ALERT_AREA_HA`) are discarded. At 20 m resolution, 1 ha corresponds to 25 pixels, which provides a reasonable spatial filter against noise.

### 6.6 Vectorization and Output

The vectorization process is implemented in `src/detection/alerts.py::vectorize_alerts()`:

1. The confidence raster is binarized at the minimum confidence level.
2. Connected components are extracted using `rasterio.features.shapes()`.
3. Each polygon's area is computed in hectares (assuming the projected CRS is in meters).
4. Polygons below the minimum area are discarded.
5. Each surviving polygon is assigned the **maximum confidence** value found **within its exact geometry**. *(v2.0 fix: previously the computation used the polygon's rectangular *bounding-box* window, so it could inherit the confidence of a pixel from another neighboring polygon within the rectangle; it now rasterizes the geometry with `geometry_mask` and reduces only over interior pixels.)*
6. Polygons are reprojected from EPSG:32724 (UTM) to EPSG:4326 (WGS 84) for GeoJSON output.
7. Metadata (detection date, creation timestamp, confidence label) is appended.
8. Output is saved as `data/alerts/alerts_{YYYY-MM-DD}.geojson`.

### 6.7 Fire vs. Mechanical Clearing Discrimination

An auxiliary classification module (`src/detection/change_detect.py::classify_fire_vs_mechanical()`) distinguishes the cause of detected clearing:

- **Fire:** dNBR > 0.27 AND post-fire NBR < 0.1
- **Mechanical clearing:** High BSI without charcoal signature (BSI > 0.1, dNBR > 0.05, no fire mask)
- **Uncertain:** Some change detected (dNBR > 0.1) but does not clearly match either pattern

*(v2.0: this module, previously implemented but never called, has been **wired into the pipeline** -- each alert receives a `clearing_type` field = fire/mechanical/uncertain/none, assigned by the modal class over the polygon's exact geometry.)*

### 6.8 Temporal Persistence (new in v2.0)

Detection is per-scene and stateless. To contain commission from transient phenomena (cloud/shadow/temporary water), v2.0 adds a **vector persistence filter** (`src/detection/persistence.py`): an alert is only marked `confirmed` if it **spatially overlaps** (>=5% of its own area, `min_overlap_frac`) an alert from the immediately preceding observation; otherwise it stays `candidate` (or `first_observation` on the first date). The filter is **non-destructive** -- it writes all alerts with the `persistence_status` field, allowing successive observations to be chained without reprocessing imagery.

**Before/after on the real record** (>=2 consecutive obs., min. 5% overlap): the raw sequence 13 / 1,334 / 1 / 3,776 / 4,951 / 4,709 / 2,744 (17,528 total) drops to 0 / 22 / 0 / 0 / 701 / 1,364 / 157 confirmed (**2,244; -87.2%**), and **stops growing monotonically with cloudiness**. Honest caveat: when the preceding observation is poor (e.g., a heavily clouded scene, 1 alert), confirmation becomes impossible and the filter over-suppresses -- an effect attenuated by a regular twice-weekly cadence. Tests: `tests/test_persistence.py`.

---

## 7. Drought Adjustment

### 7.1 Rationale

In the Caatinga biome, prolonged drought causes natural vegetation die-back and leaf shedding that can mimic deforestation signals in spectral indices. Without drought adjustment, a monitoring system would produce extensive false positive alerts during dry years. The system addresses this by computing the Standardized Precipitation Index (SPI) and relaxing detection thresholds when drought conditions are identified.

### 7.2 SPI Computation

The SPI computation is implemented in `src/processing/spi.py`. The 3-month SPI (SPI-3) is used to detect seasonal drought:

1. **Data source:** CHIRPS v2.0 monthly precipitation (global, 0.05 deg resolution)
2. **Aggregation:** Monthly precipitation values are summed over a rolling 3-month window to produce SPI-3.
3. **Distribution fitting:** A gamma distribution is fit to the historical reference period of non-zero 3-month precipitation sums (using `scipy.stats.gamma.fit` with location fixed at zero).
4. **Probability integral transform:** The target 3-month sum is transformed through the fitted gamma CDF, accounting for the mixed distribution (probability of zero precipitation + gamma distribution for positive values).
5. **Standardization:** The CDF value is mapped to a standard normal deviate via the inverse normal CDF (`scipy.stats.norm.ppf`), producing the SPI value.
6. **Tail clamping:** CDF values are clamped to [0.001, 0.999] to avoid infinite SPI values at the distribution tails.

SPI interpretation:
- SPI > 0: Wetter than normal
- SPI < -1.0: Moderate drought
- SPI < -1.5: Severe drought
- SPI < -2.0: Extreme drought

Fallback behavior: If fewer than 10 non-zero precipitation values are available for gamma fitting, the system falls back to a simple z-score (target minus mean, divided by standard deviation).

### 7.3 Threshold Adjustment

When the 3-month SPI falls below -1.0 (`SPI_DROUGHT_THRESHOLD`), all z-score thresholds are widened by subtracting 0.5 standard deviations (`DROUGHT_Z_ADJUSTMENT`):

| Confidence | Normal threshold | Drought threshold |
|------------|-----------------|-------------------|
| High | z < -3.0 | z < -3.5 |
| Medium | z < -2.5 | z < -3.0 |
| Low | z < -2.0 | z < -2.5 |

This effectively requires a larger departure from the baseline to trigger an alert during drought, reducing false positives from natural vegetation stress.

### 7.4 Current Status

**[Updated in v2.0]** The cache `data/chirps/` holds **61 monthly CHIRPS rasters** from 2021-03 to 2026-03 (local, untracked). SPI-based drought adjustment **is ACTIVE by default** -- `scripts/run_detection.py` (and `run_detection_from_gee.py`) call `get_current_spi(aoi_bbox)` and pass the value to `detect_deforestation`, which widens the thresholds when SPI-3 < -1.0. The Phase 1 audit assumed this was a "to-enable" item; it was in fact already wired in. The computation was **hardened** (`get_current_spi`) to drop recent months not yet published by CHIRPS (~1--1.5 month lag), preventing a missing month from silently zeroing the SPI. An AOI-mean precipitation series (2021--2026) was extracted to `data/chirps_aoi/chirps_aoi_monthly.csv`.

---

## 8. Data Validation Results

### 8.1 Validation Methodology

A validation script (`scripts/validate_baseline_data.py`) analyzed all 106 downloaded GeoTIFF files for January (month 01), producing per-band histograms, per-tile summary statistics, and a quantitative assessment of cloud contamination signals. Validation outputs are stored in `scripts/validation_output/`.

### 8.2 Per-Index Results

#### NDMI: PASS

- **Value range:** [-0.56, 0.55] -- fully within the theoretical bounds [-1, 1]
- **Mean:** 0.058, **Median:** 0.065, **Std:** 0.125
- **Distribution:** Unimodal, smooth, no bimodal cloud contamination signal
- **P1/P99:** -0.22 / 0.30
- **Out-of-range fraction:** 0.00%
- **Inter-annual variation:** 2025--2026 scenes show slightly lower NDMI than 2023, consistent with inter-annual rainfall variability
- **Assessment:** Clean and suitable for baseline compositing without modification

#### NBR: PASS

- **Value range:** [-0.58, 0.75] -- within theoretical bounds
- **Mean:** 0.279, **Median:** 0.291, **Std:** 0.168
- **Distribution:** Unimodal, right-skewed toward vegetated values, no contamination signal
- **P1/P99:** -0.12 / 0.59
- **Out-of-range fraction:** 0.00%
- **Assessment:** Clean and suitable for baseline compositing without modification

#### EVI2: FAIL (with mitigation applied)

- **Value range:** [-0.41, 2.09] -- values above ~1.0 are physically unrealistic
- **Mean:** 0.974, **Median:** 0.990, **Std:** 0.404
- **P1/P99:** 0.20 / 1.74
- **Out-of-range fraction (outside [-1, 1]):** 45.7%
- **Suspect high (> 0.95):** 48.4%
- **Likely cause:** Thin cirrus or haze not caught by the SCL cloud mask. Clouds have high NIR relative to RED, which inflates EVI2 (due to the 2.5 multiplier) far more than NDMI or NBR (which use SWIR bands that clouds absorb).
- **Mitigation applied:** EVI2 values are capped at 1.0 during baseline construction (`EVI2_CAP = 1.0` in `build_baseline_from_downloads.py`). This removes the physically unrealistic tail while preserving valid vegetation signals.
- **Assessment:** Usable with capping. However, the systematic contamination means EVI2 baselines have higher uncertainty than NDMI or NBR. This is acceptable because EVI2 serves a confirmatory role, not a primary detection role.
- **[v2.0 revision]** This analysis refers to the **DN-scale** data of v1.1. As explained in §4.3, most of the "45.7% out of range" was a **units error**, not cirrus. With the reflectance conversion (`REFLECTANCE_SCALING=True`) and the baseline rebuild, EVI2 falls to ~0% outside [-1, 1] **without** the cap at 1.0. This block is retained as a record of the original diagnosis.

### 8.3 Cloud Masking Verification

The validation resolved a key uncertainty about the downloaded data:

- **Cloud masking was applied:** Pixels use NaN for masked/no-data areas, not the declared nodata value of 0. NaN fractions of 11--90% per scene (averaging ~69%) are consistent with pixel-level SCL-based cloud masking having been applied prior to download.
- **NoData encoding:** The file metadata declares `nodata=0`, but actual no-data encoding is NaN (Float32). Very few pixels are exactly 0, so this metadata discrepancy does not cause data loss in practice.
- **Residual contamination:** Cloud masking is effective for NDMI and NBR but incomplete for EVI2 (thin cirrus leakage). This is a known limitation of the SCL mask for cirrus class boundaries.

### 8.4 Per-Tile Consistency

Analysis across the 7 UTM tiles shows:
- NDMI and NBR distributions are consistent across all tiles.
- EVI2 contamination is systematic (present in all tiles), not tile-specific.
- Tiles 24MVS and 24MVT show slightly higher NDMI/NBR values, consistent with denser vegetation on the Araripe plateau due to orographic rainfall enhancement.

---

## 9. Alert Results and Current Status

### 9.1 Generated Alerts

The detection history (v1.1) had accumulated **7 alert files / 17,528 polygons**, covering Nov 2025 to Apr 2026. *(v1.1 reported "5 files / 8,924 polygons" -- outdated: it omitted the 1-feature file of Dec 28 and the Feb/Apr files, and carried incorrect per-file counts.)*

| File | Date | Polygons (raw) | Confirmed (persistence) |
|------|------|---------------|-------------------------|
| `alerts_2025-11-26.geojson` | 2025-11-26 | 13 | 0 (1st obs.) |
| `alerts_2025-11-28.geojson` | 2025-11-28 | 1,334 | 22 |
| `alerts_2025-12-28.geojson` | 2025-12-28 | 1 | 0 |
| `alerts_2026-01-12.geojson` | 2026-01-12 | 3,776 | 0 |
| `alerts_2026-02-01.geojson` | 2026-02-01 | 4,951 | 701 |
| `alerts_2026-02-11.geojson` | 2026-02-11 | 4,709 | 1,364 |
| `alerts_2026-04-27.geojson` | 2026-04-27 | 2,744 | 157 |
| **Total** | | **17,528** | **2,244 (-87.2%)** |

> **2026 reprocessing (v2.0).** These numbers come from the old DN baseline. The 2026 detection is being **reprocessed via GEE** against the new reflectance baseline (§9.3), which will replace the counts above with values consistent on the correct scale and with a regular acquisition step (the ~30 twice-weekly dates of 2026, instead of the 7 sparse dates generated by manual runs).

### 9.2 Observations

The alert counts increase substantially from November to February. This trend warrants scrutiny:

- The November--December period is the onset of the wet season in this region, so widespread natural deforestation would be unexpected.
- The escalating alert count may reflect: (a) genuine clearing activity, (b) commission errors from cloud/shadow artifacts during the wet season, (c) changes in scene availability or quality, or (d) issues with baseline representativeness in the early months of the system.
- The near-zero alert count on 2025-12-28 (only 1 polygon) may indicate a heavily clouded scene where few pixels passed the clear-sky filter.

These alerts have not yet been validated against independent reference data (e.g., high-resolution imagery, field verification).

### 9.3 Automation and Deployment

| Component | Configuration | Status (v2.0) |
|-----------|--------------|---------------|
| GitHub Actions twice-weekly cron | `.github/workflows/update_data.yml`, Mon+Thu 06:00 UTC | Hardened; still need to enable Actions + R2 *secrets* in the repo |
| R2 baseline fetch (new) | `scripts/fetch_baselines_from_r2.py`, workflow step before detection | Added -- this is what gives CI its baselines |
| Cloudflare R2 storage | Bucket `araripe-cogs`, prefix `baselines/`, upload via `scripts/upload_to_r2.py` | Reflectance baselines **published** |
| Static public site | Vite MPA → Cloudflare Pages; data via `prepare_data.py` (reads `data/alerts` + `timeseries.db`) | In production (replaces Streamlit/HF) |
| Streamlit / Hugging Face dashboard (legacy) | `app.py`; HF sync at end of workflow | Legacy, no longer the frontend in use |

**Why the previous operation captured few dates (and why GEE captures ~30).** The old workflow **never actually detected in CI**: the check-out cloned the repository, but the baselines are local *git-ignored* data (they were neither in the repo nor in R2 in a consumable form), so the detection step found "no baselines" and skipped. The 7 sparse alert files (§9.1) were generated by **manual local runs**, each looking back only `--days-back 16` -- hence the irregular cadence. It was not a continuous twice-weekly operation. With the baselines now on R2 and the **new fetch step** in the workflow, CI now has baselines and streaming detection runs on the *runner* (fast network, unlike the home connection). The **GEE path** (below) processes **all** acquisition dates in an interval -- which is why it enumerates the ~30 real twice-weekly dates of 2026, exposing that the earlier gap was one of **operation**, not image availability.

**Google Earth Engine detection path (adopted for 2026).** It mirrors the baseline rebuild: `scripts/build_detection_gee.py` (Cloud Shell) computes **one composite per date** (NDMI/NBR/EVI2/BSI in reflectance, with the same `prep()` as the baseline) and exports small GeoTIFFs; `scripts/run_detection_from_gee.py` (local) runs the **unchanged detection logic** against the reflectance baselines (z-score → scene guard → vectorization → fire vs. mechanical → land cover → persistence). Because GEE mosaics all tiles of a date into a single AOI composite, this path also **fixes** the latent streaming bug where tiles of the same date overwrote each other's alert file. Step-by-step in `docs/DETECTION_GEE.md`. *(Fully headless GEE automation in CI -- via a service account -- is roadmap; today the GEE step is manual via Cloud Shell.)*

### 9.4 Web Dashboard — Visualization Layer

> **[v2.0] This section describes the legacy Streamlit dashboard (`app.py`), which is no longer the frontend in use.** The current frontend is a **static site** (Vite MPA → Cloudflare Pages), which consumes the same `data/alerts/*.geojson` via a preparation script (`prepare_data.py`) and serves prebuilt pages. The content below is retained as a record of the original dashboard.

The web interface (`app.py` + `src/visualization/`) was reworked in version 1.1 to reflect how the system is actually used in the field:

- **Switchable basemaps** — every map view (normal mode and export mode) exposes three layers in the layer-control widget at the top-right of the map: Esri Satellite (default), Google Satellite Hybrid, and OpenStreetMap. The same widget also toggles the APA, FLONA, and alert overlays on or off.
- **Protected-area contours** — the APA Chapada do Araripe (yellow line) and FLONA Araripe-Apodi (green line) boundaries are overlaid on every map automatically, read from `data/aoi/APA_chapada_araripe.gpkg` and `data/aoi/FLONA_araripe.gpkg` (both EPSG:4326).
- **Full alert history by default** — the date-range filter and the minimum-area filter were removed. The complete detection history is shown on the map and table so older detections do not disappear from view.
- **Recent Activity block** — a single sidebar section combines (a) the "Last scan | Imagery from" line with a "?" icon explaining the difference between the date the pipeline ran and the acquisition date of the Sentinel-2 scene it analysed; (b) the *Recent runs (N)* selector (default N = 1, configurable from 1 to 20); and (c) a **Show only recent** checkbox that filters the view to alerts from the last *N* runs. Recent alerts keep the 🆕 badge in the table and are sorted first; the magenta-outline visual highlight was removed due to inconsistent rendering across Folium versions.
- **"Recent" definition** — the set of the last *N* detection-run dates, derived from the lexicographically-sorted file names `data/alerts/alerts_YYYY-MM-DD.geojson`. A feature is flagged as recent when its `detection_date` field is in that set.
- **Bilingual Documentation tab** — exposes `REVISAO_TECNICA.md` (PT) and `TECHNICAL_REVIEW.md` (EN); the download button serves the PDF matching the active language (`REVISAO_TECNICA.pdf` or `TECHNICAL_REVIEW.pdf`), generated by `scripts/md_to_pdf.py`.

---

## 10. Known Limitations and Uncertainties

### 10.1 Phenological Confounding

The deciduous phenology of Caatinga vegetation remains the most significant source of potential commission error. During the dry season (August--October, defined as `CAATINGA_LEAFOFF_MONTHS = [8, 9, 10]`), natural leaf-off can produce spectral signatures that overlap with deforestation signals, even in moisture-based indices like NDMI. The monthly baseline approach mitigates this by comparing against same-month historical distributions; the 5-year window {2017, 2019, 2021, 2022, 2025} broadens the base relative to v1.1 (3 years), but may still not capture the full range of inter-annual phenological variability.

### 10.2 Cloud Cover

Wet season cloud cover (November--April) reduces the number of usable observations. The system applies a 20% maximum cloud cover filter at the scene level, but partial cloud contamination within scenes can still affect index values. The SCL cloud mask handles thick clouds effectively but has documented limitations with thin cirrus (especially for EVI2).

### 10.3 EVI2 Thin Cirrus Sensitivity

As documented in Section 8, EVI2 is more sensitive to residual thin cirrus contamination than NDMI or NBR. **In v2.0 the dominant cause (DN scale) was fixed** (reflectance + `REFLECTANCE_SCALING`), removing v1.1's artificial cap at 1.0 and restoring EVI2's discriminative power. Only the *residual* thin-cirrus sensitivity remains (marginally elevated individual values), keeping EVI2's uncertainty slightly above NDMI/NBR — acceptable given its confirmatory role.

### 10.4 Baseline Temporal Depth

The v2.0 baselines span **5 years {2017, 2019, 2021, 2022, 2025}**, meeting the target and **excluding 2023/2024** (strong El Nino). The 2026 calendar year was deliberately excluded so it can serve as a detection year against a fixed reference. Remaining caveat: 5 years may still not capture the full range of extreme inter-annual variability; rare future events (e.g., extreme El Nino) may generate false positives, mitigated by the drought adjustment (SPI) and by persistence.

### 10.5 Drought Adjustment — **now operational (v2.0)**

The CHIRPS data **is present** (61 rasters, 2021-03 to 2026-03) and SPI-based drought adjustment **is active by default** (thresholds widened when SPI-3 < -1.0). Caveat: the climatological norm uses few years (~5) rather than the recommended ~30, and the gamma distribution could be swapped for Pearson III (see §11.7). Historically (pre-audit) the system ran without this adjustment.

### 10.6 Temporal Persistence — **now implemented (v2.0)**

v2.0 adds a vector persistence filter (>=2 consecutive observations with >=5% spatial overlap; see §6.8), strongly reducing commission from transient phenomena (-87% over the record). Each alert carries `persistence_status` (confirmed/candidate/first_observation), non-destructively. Caveat: with irregular cadence or a very cloudy preceding observation, the filter can over-suppress; a regular twice-weekly cadence attenuates this.

### 10.7 Minimum Mapping Unit

The 1 ha minimum alert area may be too coarse for detecting small-scale selective logging or too fine for operational response prioritization. At 20 m resolution, 1 ha = 25 pixels, which provides reasonable spatial coherence but may still include fragmented noise patterns.

### 10.8 Alert Validation Gap

The generated alerts (17,528 raw polygons in the v1.1 history; 2,244 after persistence) have not been validated against independent reference data. Without accuracy assessment (commission and omission error rates), the reliability of the system cannot be quantified. `scripts/sample_alerts_for_validation.py` builds the stratified sample; the visual interpretation is a pending human step.

---

## 11. Recommendations for Specialists

This section poses specific questions for reviewers with expertise in remote sensing-based deforestation monitoring, Caatinga/Cerrado ecology, and operational alert systems.

### 11.1 Z-Score Threshold Calibration

The current z-score thresholds (-2.0 / -2.5 / -3.0) were set based on standard anomaly detection practice. Are these values appropriate for the spectral variability observed in Caatinga/Cerrado transition zones? Should the thresholds be differentiated by season (e.g., more conservative during dry months) or by vegetation type (e.g., Cerrado vs. Caatinga subregions)?

### 11.2 NDVI Inclusion

NDVI was excluded from the detection pipeline due to deciduousness concerns. However, some systems (e.g., PRODES) use NDVI in combination with other indices. Should NDVI be reintroduced as an additional confirmatory index, perhaps with a seasonal weighting scheme? Alternatively, could a phenology-adjusted NDVI baseline (e.g., using harmonic regression to model the seasonal cycle) adequately account for deciduousness?

### 11.3 Minimum Mapping Unit

Is the 1 ha minimum alert area appropriate for this region? Considering:
- Typical deforestation patch sizes in Chapada do Araripe
- The 20 m pixel resolution (1 ha = 25 pixels)
- Operational response capacity of enforcement agencies (IBAMA, ICMBio)
- Trade-off between detection sensitivity and false alarm rate

### 11.4 Temporal Persistence

Should the system require alerts to be confirmed across 2 or more consecutive observations before reporting? This would reduce timeliness (by one revisit cycle, approximately 5--10 days) but could substantially reduce false positives from transient phenomena (clouds, shadows, temporary water).

### 11.5 Dry Season Protocol

The dry season months (August--October) are identified as problematic (`CAATINGA_LEAFOFF_MONTHS`). How should the system handle these months differently? Options include:
- Increased z-score thresholds during dry months
- Excluding EVI2 entirely during dry months (relying only on NDMI and NBR)
- Using a phenology-corrected baseline that models the intra-annual cycle rather than discrete monthly composites
- Suspending low-confidence alerts during dry months

### 11.6 Additional Indices

Are there other indices that should be considered for this biome transition?

- **NDFI** (Normalized Difference Fraction Index): Used by INPE's DETER and PRODES systems for forest degradation detection. NDFI uses spectral mixture analysis to decompose pixels into green vegetation, non-photosynthetic vegetation, and soil/shade fractions. The system already defines NDFI thresholds (`NDFI_INTACT_FOREST = 0.75`, `NDFI_DEGRADED_MIN = 0.0`) but does not implement the spectral unmixing required to compute it.
- **MSI** (Moisture Stress Index): SWIR/NIR ratio, inverse of NDMI, sometimes preferred for drylands.
- **NDWI** (Normalized Difference Water Index): Could help distinguish water body changes from vegetation clearing.
- **SAR-based indices** (e.g., from Sentinel-1): Radar is weather-independent and could complement optical detection during the cloudy wet season.

### 11.7 Additional Questions

7. Is the gamma-distribution-based SPI computation appropriate for this semi-arid region, or would an alternative distribution (e.g., Pearson Type III) better fit the precipitation climatology?
8. Should the baseline construction use a robust measure of spread (e.g., median absolute deviation) instead of standard deviation, given the documented outlier contamination in EVI2?
9. How should the system handle areas that were already deforested before the baseline period? Currently, these would show consistently low index values and would not trigger alerts (low z-scores), but they may also mask ongoing degradation of remnant vegetation patches.

---

## 12. Trend Analysis Module

In addition to the near-real-time alert system, the codebase includes a trend analysis module (`src/timeseries/trends.py`) for longer-term vegetation change assessment:

- **Mann-Kendall test:** Non-parametric test for monotonic trends in vegetation index time series. Reports Kendall's tau, p-value (significance at alpha = 0.05), and trend direction (increasing / decreasing / no trend). Corrected for tied values.
- **Sen's slope estimator** (Theil-Sen): Robust slope estimation (median of all pairwise slopes), reported as change per year with 95% confidence intervals.

These tools support retrospective analysis of gradual degradation trends that may not trigger the acute change detection system.

---

## 13. References

1. Gao, B.-C. (1996). NDWI -- A normalized difference water index for remote sensing of vegetation liquid water from space. *Remote Sensing of Environment*, 58(3), 257--266. (NDMI is sometimes referred to as NDWI in the literature; the formula using SWIR1 is commonly attributed to Gao.)

2. Key, C. H., & Benson, N. C. (2006). Landscape Assessment: Sampling and analysis methods. In D. C. Lutes et al. (Eds.), *FIREMON: Fire Effects Monitoring and Inventory System* (Gen. Tech. Rep. RMRS-GTR-164-CD). USDA Forest Service. (NBR and dNBR burn severity classification.)

3. Jiang, Z., Huete, A. R., Didan, K., & Miura, T. (2008). Development of a two-band enhanced vegetation index without a blue band. *Remote Sensing of Environment*, 112(10), 3833--3845. (EVI2 formulation and validation.)

4. McKee, T. B., Doesken, N. J., & Kleist, J. (1993). The relationship of drought frequency and duration to time scales. *Proceedings of the 8th Conference on Applied Climatology*. American Meteorological Society. (Standardized Precipitation Index.)

5. Funk, C., Peterson, P., Landsfeld, M., et al. (2015). The climate hazards infrared precipitation with stations -- a new environmental record for monitoring extremes. *Scientific Data*, 2, 150066. (CHIRPS precipitation dataset.)

6. Souza Jr., C. M., Roberts, D. A., & Cochrane, M. A. (2005). Combining spectral and spatial information to map canopy damage from selective logging and forest fires. *Remote Sensing of Environment*, 98(2--3), 329--343. (NDFI and spectral mixture analysis for tropical forest degradation.)

7. Hamed, K. H., & Rao, A. R. (1998). A modified Mann-Kendall trend test for autocorrelated data. *Journal of Hydrology*, 204(1--4), 182--196. (Mann-Kendall trend test.)

8. Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *Journal of the American Statistical Association*, 63(324), 1379--1389. (Sen's slope estimator / Theil-Sen regression.)

9. Diniz, J. M. F. S., Gama, F. F., & Adami, M. (2022). Evaluation of the performance of vegetation indices for detecting deforestation in the Caatinga biome. *Remote Sensing Applications: Society and Environment*, 26, 100753. (Vegetation index performance in Caatinga, supporting NDMI over NDVI.)

10. Lamchin, M., Lee, W.-K., Jeon, S. W., et al. (2018). Long-term land cover change and deforestation in Southeast Asia using remote sensing. *Remote Sensing*, 10(11), 1663. (Z-score anomaly detection for land cover change.)

---

## Appendix A: Configuration Parameter Summary

All configurable parameters are defined in `config/settings.py`. The following table summarizes the values used in the current system:

| Parameter | Value | Description |
|-----------|-------|-------------|
| `AOI_BBOX` | [-40.0, -8.0, -39.0, -7.0] | Bounding box [W, S, E, N] in degrees |
| `TARGET_CRS` | EPSG:32724 | UTM zone 24S |
| `SENTINEL2_20M_RESOLUTION` | 20 m | Working resolution for detection |
| `LANDSAT_RESOLUTION` | 30 m | Landsat native resolution |
| `MAX_CLOUD_COVER` | 20% | Scene-level cloud cover filter |
| `SEARCH_DAYS_BACK` | 16 days | Temporal search window |
| `MIN_CLEAR_PERCENTAGE_BASELINE` | 10% | Minimum clear pixels to include a scene |
| `BASELINE_YEARS` | 5 | Target years for baseline (achieved: {2017, 2019, 2021, 2022, 2025} — see §5.5) |
| `REFLECTANCE_SCALING` | True (v2.0) | Converts DN→reflectance (`DN·scale + offset`) at acquisition; coupled to the reflectance baseline |
| `Z_THRESHOLD_HIGH` | -3.0 | Z-score for high-confidence alerts |
| `Z_THRESHOLD_MEDIUM` | -2.5 | Z-score for medium-confidence alerts |
| `Z_THRESHOLD_LOW` | -2.0 | Z-score for low-confidence alerts |
| `DELTA_THRESHOLD_HIGH` | -0.20 | Absolute change for high-confidence |
| `DELTA_THRESHOLD_MEDIUM` | -0.15 | Absolute change for medium-confidence |
| `DELTA_THRESHOLD_LOW` | -0.15 | Absolute change for low-confidence |
| `MIN_ALERT_AREA_HA` | 1.0 ha | Minimum polygon area |
| `MAX_ALERT_AREA_HA` | 1000 ha | Maximum polygon area (guard against artifacts) |
| `SCENE_ANOMALY_REJECT_FRAC` | 0.30 | Fraction of flagged pixels above which the whole scene is rejected |
| `SPI_DROUGHT_THRESHOLD` | -1.0 | SPI-3 below this triggers adjustment |
| `DROUGHT_Z_ADJUSTMENT` | 0.5 sigma | Z-threshold widening during drought |
| `DNBR_LOW_SEVERITY` | 0.27 | dNBR threshold for low-severity burn |
| `DNBR_HIGH_SEVERITY` | 0.66 | dNBR threshold for high-severity burn |
| `NBR_POST_FIRE_THRESHOLD` | 0.1 | Post-fire NBR confirming fire signature |
| `CAATINGA_LEAFOFF_MONTHS` | [8, 9, 10] | Aug--Oct dry season months |
| `NDFI_INTACT_FOREST` | 0.75 | NDFI threshold for intact forest |

---

## Appendix B: Module Reference

| Module Path | Purpose |
|-------------|---------|
| `config/settings.py` | All global configuration parameters |
| `src/acquisition/stac_client.py` | STAC API queries with provider fallback |
| `src/acquisition/chirps.py` | CHIRPS precipitation data download |
| `src/processing/indices.py` | Spectral index computation (NDMI, NBR, EVI2, NDVI, SAVI, BSI, dNBR) |
| `src/processing/cloud_mask.py` | Cloud masking for Sentinel-2 (SCL), Landsat (QA_PIXEL), HLS (Fmask) |
| `src/processing/spi.py` | SPI computation (gamma distribution fitting) |
| `src/detection/change_detect.py` | Z-score anomaly detection and confidence classification |
| `src/detection/alerts.py` | Alert vectorization (exact-geometry mask), storage, and summary statistics |
| `src/detection/baseline.py` | Z-score and delta computation primitives; `load_baseline_pair` |
| `src/detection/persistence.py` | **(v2.0)** Temporal persistence filter (overlap between observations) |
| `src/detection/landcover.py` | **(v2.0)** MapBiomas annotation/filter (10 m and 30 m, per-collection tables) |
| `src/timeseries/trends.py` | Mann-Kendall test and Sen's slope estimator |
| `scripts/build_baseline_gee.py` · `docs/gee_baseline_cloudshell.py` | **(v2.0)** Monthly reflectance baseline via Google Earth Engine |
| `scripts/split_gee_baselines.py` | **(v2.0)** Slices the GEE composites into the detector's 72 COGs |
| `scripts/build_baseline.py` | Streaming-COG baseline construction (fallback; fixed) |
| `scripts/run_detection.py` | Streaming detection execution (used in CI) |
| `scripts/build_detection_gee.py` · `scripts/run_detection_from_gee.py` | **(v2.0)** Composite-per-date detection via GEE (Cloud Shell + local ingestion) |
| `scripts/select_baseline_years.py` | **(v2.0)** Reproducible selection of the "quiet" years (ONI + CHIRPS) |
| `scripts/upload_to_r2.py` · `scripts/fetch_baselines_from_r2.py` | Publish / fetch baselines on Cloudflare R2 |
| `app.py` | Streamlit dashboard (**legacy**; current frontend is the static site) |
