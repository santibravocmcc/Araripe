# Technical Review: Araripe Deforestation Monitoring System

**Version:** 1.0
**Date:** 2026-04-01
**Prepared for:** Specialist peer review (remote sensing, environmental monitoring)
**System repository:** `/Users/sbravo/Documents/Projetos/Araripe/`

---

## 1. Executive Summary

The Araripe Deforestation Monitoring System is a near-real-time change detection pipeline designed to generate weekly deforestation and degradation alerts for the Chapada do Araripe region in northeastern Brazil. The system ingests multispectral satellite imagery (Sentinel-2 L2A, Landsat 8/9 Collection 2, NASA HLS) via open STAC APIs, computes moisture- and vegetation-sensitive spectral indices (NDMI, NBR, EVI2), and detects anomalous vegetation loss through z-score deviation from monthly baselines constructed over a 4-year reference period (2023--2026).

The system is designed to operate at zero recurring cost, using GitHub Actions for weekly automation, Hugging Face Spaces for the Streamlit dashboard, and Cloudflare R2 for Cloud Optimized GeoTIFF (COG) storage. Detection outputs are vectorized alert polygons in GeoJSON format, classified into three confidence tiers (high, medium, low) with a minimum mapping unit of 1 hectare.

**Current operational status:** The full codebase is implemented and functional. Monthly baselines (72 COG files) have been produced for all 12 months across three spectral indices. Five alert files have been generated covering the period November 2025 through February 2026, containing a total of 8,924 alert polygons. The CHIRPS precipitation data for drought adjustment has not yet been populated. The weekly automation pipeline and public dashboard are configured but not yet deployed in production.

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
| 4 | Copernicus Data Space | `https://stac.dataspace.copernicus.eu/v1` | Configured but not actively used in the fallback chain |

The fallback logic for Sentinel-2 queries is: Element84 first; if zero results, Planetary Computer. Landsat queries go directly to Planetary Computer. HLS queries go to NASA CMR STAC.

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
- **Current status:** Cache directory is empty; CHIRPS data has not yet been downloaded.

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

**Limitation:** Validation revealed that EVI2 is susceptible to residual thin cirrus contamination not caught by the SCL cloud mask. Clouds have high NIR reflectance relative to RED, which inflates EVI2 far more than NDMI or NBR (which use SWIR bands that clouds absorb). In the January baseline data, 45.7% of valid EVI2 pixels fell outside [-1, 1] and P99 reached 1.74. This required a mitigation step (capping values at 1.0) during baseline construction.

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

Baselines were built from downloaded Sentinel-2 L2A scenes using the script `scripts/build_baseline_from_downloads.py`. The source data consisted of:

- **106 GeoTIFF files per month** (January as reference), each containing 3 bands (NDMI, NBR, EVI2)
- **7 UTM tiles** covering the AOI: 24MTS, 24MTT, 24MUS, 24MUT, 24MVS, 24MVT, 24MWS
- **3 satellite platforms:** Sentinel-2A (40 scenes), Sentinel-2B (40 scenes), Sentinel-2C (26 scenes)
- **4 years of coverage:** 2023 (22 scenes), 2024 (30 scenes), 2025 (16 scenes), 2026 (38 scenes)
- **CRS:** EPSG:32724 (UTM zone 24S), **Resolution:** 20 m

### 5.3 Processing Pipeline

For each month, the baseline construction proceeds as follows:

1. **Group by acquisition date** -- Files are grouped by the 8-digit date prefix in their filename (e.g., `20230103`).
2. **Tile mosaicking** -- For each date, the 7 UTM tiles are merged into a single raster covering the full AOI extent using `rasterio.merge` with `method="first"` and NaN as no-data.
3. **AOI clipping** -- The merged raster is masked to the AOI polygon (pixels outside the polygon are set to NaN).
4. **EVI2 outlier filtering** -- For the EVI2 band, values exceeding 1.0 in absolute value are capped at 1.0 (`EVI2_CAP = 1.0`). This mitigates residual thin cirrus contamination that inflates EVI2 beyond physically realistic bounds.
5. **Temporal compositing** -- All dates within a given month are stacked into a 3D array (dates x height x width). The pixel-wise **median** and **standard deviation** are computed across the temporal axis. Median is preferred over mean for robustness to outliers. Pixels with fewer than 2 valid observations across all dates have their standard deviation set to NaN.
6. **COG output** -- Results are saved as Cloud Optimized GeoTIFFs with DEFLATE compression, 512x512 internal tiling, and overviews (via `gdal_translate -of COG` when available).

### 5.4 Output

The baseline construction produces **72 COG files**:

    3 indices (NDMI, NBR, EVI2) x 12 months x 2 statistics (mean/median, std) = 72 files

Naming convention: `{index}_month{MM}_mean.tif` and `{index}_month{MM}_std.tif`

All 72 baseline files have been successfully produced and are stored in `data/baselines/`. Note: although the filenames use the suffix `_mean`, the actual statistic computed is the **median** (as implemented in `build_baseline_from_downloads.py`). This naming convention was inherited from the original pipeline design.

### 5.5 Temporal Depth

The configuration specifies a target of 5 years of history (`BASELINE_YEARS = 5`), but the current baselines are constructed from **4 years** (2023--2026). While this exceeds the minimum of 3 years considered adequate for baseline statistics, it may not fully capture extreme inter-annual variability (e.g., strong El Nino / La Nina cycles).

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
5. Each surviving polygon is assigned the **maximum confidence** value found within its spatial extent.
6. Polygons are reprojected from EPSG:32724 (UTM) to EPSG:4326 (WGS 84) for GeoJSON output.
7. Metadata (detection date, creation timestamp, confidence label) is appended.
8. Output is saved as `data/alerts/alerts_{YYYY-MM-DD}.geojson`.

### 6.7 Fire vs. Mechanical Clearing Discrimination

An auxiliary classification module (`src/detection/change_detect.py::classify_fire_vs_mechanical()`) distinguishes the cause of detected clearing:

- **Fire:** dNBR > 0.27 AND post-fire NBR < 0.1
- **Mechanical clearing:** High BSI without charcoal signature (BSI > 0.1, dNBR > 0.05, no fire mask)
- **Uncertain:** Some change detected (dNBR > 0.1) but does not clearly match either pattern

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

The CHIRPS precipitation data cache (`data/chirps/`) is currently empty. The drought adjustment module is fully implemented but has not yet been activated in operational runs. Until CHIRPS data is ingested, the system operates without drought adjustment (SPI defaults to 0.0, no threshold widening).

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

Five alert files have been generated, covering the period November 2025 through February 2026:

| File | Date | Alert Polygons | File Size |
|------|------|---------------|-----------|
| `alerts_2025-11-26.geojson` | 2025-11-26 | 13 | 257 KB |
| `alerts_2025-11-28.geojson` | 2025-11-28 | 1,334 | 5.6 MB |
| `alerts_2025-12-28.geojson` | 2025-12-28 | 1 | 1.8 KB |
| `alerts_2026-01-12.geojson` | 2026-01-12 | 3,085 | 17.7 MB |
| `alerts_2026-02-01.geojson` | 2026-02-01 | 4,491 | 23.9 MB |
| **Total** | | **8,924** | **47.5 MB** |

### 9.2 Observations

The alert counts increase substantially from November to February. This trend warrants scrutiny:

- The November--December period is the onset of the wet season in this region, so widespread natural deforestation would be unexpected.
- The escalating alert count may reflect: (a) genuine clearing activity, (b) commission errors from cloud/shadow artifacts during the wet season, (c) changes in scene availability or quality, or (d) issues with baseline representativeness in the early months of the system.
- The near-zero alert count on 2025-12-28 (only 1 polygon) may indicate a heavily clouded scene where few pixels passed the clear-sky filter.

These alerts have not yet been validated against independent reference data (e.g., high-resolution imagery, field verification).

### 9.3 Automation and Deployment

| Component | Configuration | Status |
|-----------|--------------|--------|
| GitHub Actions weekly cron | `.github/workflows/update_data.yml`, Mondays at 06:00 UTC | Configured, not yet active |
| Streamlit dashboard | `app.py` with Leafmap/Plotly, 4-tab layout | Implemented |
| Hugging Face Spaces hosting | Configured for HF Spaces deployment | Not yet deployed |
| Cloudflare R2 COG storage | Bucket `araripe-cogs`, upload via `scripts/upload_to_r2.py` | Configured, endpoint URL not set |

---

## 10. Known Limitations and Uncertainties

### 10.1 Phenological Confounding

The deciduous phenology of Caatinga vegetation remains the most significant source of potential commission error. During the dry season (August--October, defined as `CAATINGA_LEAFOFF_MONTHS = [8, 9, 10]`), natural leaf-off can produce spectral signatures that overlap with deforestation signals, even in moisture-based indices like NDMI. The monthly baseline approach mitigates this by comparing against same-month historical distributions, but the baseline may not capture the full range of inter-annual phenological variability, especially given only 4 years of reference data.

### 10.2 Cloud Cover

Wet season cloud cover (November--April) reduces the number of usable observations. The system applies a 20% maximum cloud cover filter at the scene level, but partial cloud contamination within scenes can still affect index values. The SCL cloud mask handles thick clouds effectively but has documented limitations with thin cirrus (especially for EVI2).

### 10.3 EVI2 Thin Cirrus Sensitivity

As documented in Section 8, EVI2 is more sensitive to residual thin cirrus contamination than NDMI or NBR. The capping mitigation (values > 1.0 set to 1.0) addresses extreme cases but does not correct moderately elevated values in the range 0.8--1.0 that may still be contaminated. This increases the uncertainty of the EVI2 baseline statistics (both median and standard deviation).

### 10.4 Baseline Temporal Depth

The current baselines span 4 years (2023--2026), short of the 5-year target. This may not capture the full range of climate-driven inter-annual variability. In particular:

- If 2023--2026 includes an anomalously wet or dry period, the baseline will be biased accordingly.
- Rare events (e.g., extreme El Nino) may not be represented, leading to false positives during similar future events.

### 10.5 Drought Adjustment Not Yet Operational

The CHIRPS data has not been downloaded, so the SPI-based drought adjustment is not active. All alerts generated to date were produced without drought threshold widening. This means that alerts during drier-than-normal periods may include false positives from natural vegetation stress.

### 10.6 No Temporal Persistence Filter

The current system classifies each observation independently (single-date detection). There is no requirement for an alert to be confirmed by a subsequent observation. This design choice maximizes timeliness but increases the false positive rate compared to systems that require persistence across 2 or more dates (e.g., DETER, Global Forest Watch).

### 10.7 Minimum Mapping Unit

The 1 ha minimum alert area may be too coarse for detecting small-scale selective logging or too fine for operational response prioritization. At 20 m resolution, 1 ha = 25 pixels, which provides reasonable spatial coherence but may still include fragmented noise patterns.

### 10.8 Alert Validation Gap

The generated alerts (8,924 polygons) have not been validated against independent reference data. Without accuracy assessment (commission and omission error rates), the reliability of the system cannot be quantified.

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
| `BASELINE_YEARS` | 5 | Target years for baseline (4 achieved) |
| `Z_THRESHOLD_HIGH` | -3.0 | Z-score for high-confidence alerts |
| `Z_THRESHOLD_MEDIUM` | -2.5 | Z-score for medium-confidence alerts |
| `Z_THRESHOLD_LOW` | -2.0 | Z-score for low-confidence alerts |
| `DELTA_THRESHOLD_HIGH` | -0.20 | Absolute change for high-confidence |
| `DELTA_THRESHOLD_MEDIUM` | -0.15 | Absolute change for medium-confidence |
| `DELTA_THRESHOLD_LOW` | -0.15 | Absolute change for low-confidence |
| `MIN_ALERT_AREA_HA` | 1.0 ha | Minimum polygon area |
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
| `src/detection/alerts.py` | Alert vectorization, storage, and summary statistics |
| `src/detection/baseline.py` | Z-score and delta computation primitives |
| `src/timeseries/trends.py` | Mann-Kendall test and Sen's slope estimator |
| `scripts/build_baseline_from_downloads.py` | Baseline COG construction from downloaded scenes |
| `scripts/run_detection.py` | Manual detection execution |
| `scripts/upload_to_r2.py` | Cloudflare R2 COG upload |
| `app.py` | Streamlit dashboard entry point |
