# Chapada do Araripe Monitoring System

**Document:** A guided technical overview
**Version:** 1.0
**Date:** 2026-07-22
**Audience:** Colleagues discovering the project for the first time

---

## 1. The project in one paragraph

The Chapada do Araripe Monitoring System is an open environmental-monitoring project that uses satellite imagery to look for unusual vegetation loss in and around the Chapada do Araripe, in northeastern Brazil. It compares each new observation with the way the same landscape normally looks in that month, turns unusual changes into mapped alert polygons, adds environmental context, and publishes the results on the website of the Observatório da Chapada do Araripe.

The project brings together remote sensing, geospatial analysis, cloud automation, open data, and public communication. Its purpose is not simply to produce a map. It is to create a repeatable path from a satellite image to information that researchers, local organizations, educators, and field teams can explore.

At its current stage, the system already includes:

- a monthly satellite baseline for the whole monitoring year;
- an automated detection workflow running twice a week;
- alert polygons with confidence, recurrence, land-cover, and location attributes;
- regional vegetation time series;
- cloud storage for large scientific files;
- a public interactive site with maps, filters, downloads, explanatory content, and an AI methodology assistant.

---

## 2. First, meet the Chapada do Araripe

The Chapada do Araripe is a large plateau in northeastern Brazil, close to the meeting point of Ceará, Pernambuco, and Piauí. Its elevation, geology, vegetation, springs, and long history of human occupation make it a distinctive landscape within the semi-arid Northeast.

The region sits at an ecological transition. Different parts of the Chapada contain:

- **Caatinga**, a seasonally dry vegetation adapted to long rainless periods;
- **Cerrado**, with savanna, grassland, shrub, and woodland formations;
- **humid forest enclaves**, especially where elevation and relief favor moisture.

The plateau is also important for water. Rain infiltrates its sedimentary layers and helps feed springs around the escarpment. These water sources connect environmental conservation directly with farms, cities, traditional communities, and daily life.

The project's geographic focus is the APA Chapada do Araripe and the wider surrounding landscape. The APA boundary stored in the project data measures approximately 972,000 hectares. The broader region also contains the Araripe National Forest and many inhabited and productive areas.

### Why satellite monitoring is useful here

Vegetation change in the Chapada can be associated with several processes: expansion of agriculture and pasture, wood extraction, fire, roads and urban growth, as well as natural drought and seasonal leaf loss.

That last point is especially important. During the dry season, healthy Caatinga vegetation can lose much of its foliage. A simple "green versus not green" method would easily confuse this normal seasonal behavior with clearing.

The central technical challenge is therefore:

> How can the system identify an unusual change while respecting the fact that this landscape naturally looks very different from one month to another?

The project answers this by using a separate reference for every month of the year and by emphasizing moisture-sensitive satellite measurements.

---

## 3. The core idea

The system does not ask whether a place is green in absolute terms. It asks whether that place looks unusually different from what is expected **for that particular month**.

For example, a relatively dry signal in September may be normal for seasonally deciduous vegetation. The same signal in a month that is normally wet may deserve attention. A monthly baseline gives the comparison the seasonal context it needs.

The conceptual sequence is:

| Step | What happens |
|---|---|
| 1. Observe | A satellite records visible, near-infrared, and shortwave-infrared light reflected by the landscape |
| 2. Clean | Cloud, shadow, and unusable pixels are masked |
| 3. Describe | Spectral indices summarize vegetation moisture, burn response, and vigor |
| 4. Compare | The new observation is compared with the historical baseline for the same month |
| 5. Detect | Pixels with unusually large negative changes receive a confidence class |
| 6. Map | Neighboring alert pixels become polygons with area and location |
| 7. Add context | Land cover, recurrence, and possible clearing type are attached |
| 8. Publish | The alert files, regional series, and web-ready products are updated |

This approach is often called **anomaly detection**: the system looks for departures from the expected condition rather than applying one fixed vegetation threshold to every season.

---

## 4. The satellite and environmental data

### 4.1 Sentinel-2 imagery

The scheduled production workflow uses the European Copernicus Sentinel-2 Surface Reflectance Harmonized collection through Google Earth Engine.

Sentinel-2 is well suited to this work because it:

- revisits the region every few days;
- provides 10 m and 20 m optical bands;
- records near-infrared and shortwave-infrared wavelengths that respond strongly to vegetation structure and moisture;
- supplies a scene-classification layer used in cloud masking.

The detection stack operates at 20 m, matching the native resolution of the shortwave-infrared bands used by the primary indices. A 20 m pixel represents an area of about 400 square meters.

The repository also contains a streaming path that can use Sentinel-2 and optional Landsat or NASA Harmonized Landsat-Sentinel data. This is retained as an alternative path; scheduled production is currently centered on Sentinel-2 in Earth Engine.

### 4.2 The monthly baseline

The baseline describes the expected seasonal cycle. It uses five selected reference years:

    2017, 2019, 2021, 2022, and 2025

For each of the 12 calendar months and each of the three principal indices, the system stores:

- a multi-year monthly median;
- a monthly standard deviation.

That produces:

    12 months x 3 indices x 2 statistics = 72 baseline files

The baseline files are Cloud Optimized GeoTIFFs, or COGs. This format is useful for cloud-based geospatial work because software can request only the portion of a large raster that it needs.

### 4.3 Supporting environmental layers

Two additional data families help interpret the satellite signal:

- **MapBiomas land cover** describes what type of surface is present, such as native vegetation, agriculture, pasture, urban area, or water.
- **CHIRPS precipitation** provides rainfall context and supports a drought adjustment so that an unusually dry regional period can be treated more cautiously.

These layers do different jobs. The spectral indices indicate that the surface changed; MapBiomas helps explain what was there; rainfall helps interpret whether regional drought may be influencing the observation.

---

## 5. How change is measured

### 5.1 Three complementary spectral indices

A satellite does not directly label "forest" or "deforestation." It measures reflected energy in wavelength bands. Spectral indices combine those bands to emphasize physical properties of the surface.

| Index | Formula | What it contributes |
|---|---|---|
| NDMI | (NIR - SWIR1) / (NIR + SWIR1) | Vegetation and canopy moisture |
| NBR | (NIR - SWIR2) / (NIR + SWIR2) | Moisture loss, exposed surface, and burn response |
| EVI2 | 2.5 x (NIR - Red) / (NIR + 2.4 x Red + 1) | Vegetation vigor and canopy change |

NDMI and NBR are the primary indicators because moisture-sensitive measurements help distinguish structural change from ordinary seasonal loss of leaves. EVI2 adds a complementary view of vegetation vigor.

### 5.2 Two comparisons for every pixel

For each index, the system calculates two forms of change:

- **absolute difference**, or delta: how far the new value moved from the monthly baseline;
- **standardized difference**, or z-score: how unusual that movement is relative to normal variation for the month.

Using both matters. A z-score can become large where historical variability is very small, while an absolute difference ensures that the physical change is also meaningful.

### 5.3 Confidence classes

The three classes are designed as a practical prioritization system:

| Class | General meaning |
|---|---|
| High | NDMI and NBR both show a very strong negative anomaly |
| Medium | At least one moisture index shows a clear negative anomaly |
| Low | An available index crosses the lower change threshold |

The exact rules combine z-score and delta thresholds. High confidence requires agreement between the two main moisture indices, which makes it more selective.

After classification, neighboring alert pixels are grouped into polygons. Very small patches are removed; the normal minimum mapping unit is 1 hectare. Each polygon then receives attributes such as:

- observation date;
- area;
- confidence;
- central coordinates and approximate nearby municipality;
- MapBiomas class and natural-vegetation fraction;
- recurrence information;
- an indicative fire or mechanical-clearing label when the required data are available.

### 5.4 Recurrence over time

One satellite observation may contain residual cloud, shadow, or another temporary effect. A change that appears again in later observations is generally more useful for prioritization.

The project therefore connects spatially overlapping observations into a recurrence history:

- first observation: seen once;
- candidate: seen between 2 and 14 times;
- confirmed tier: seen 15 or more times.

The word "confirmed" is a system tier describing recurrence in the satellite record. It is not a substitute for independent reference imagery or field confirmation.

---

## 6. From scientific processing to an automated service

The project separates heavy geospatial processing from the public website. This keeps the browser experience lighter and makes the scientific workflow reproducible.

### 6.1 Two repositories

| Repository | Responsibility |
|---|---|
| Araripe | Satellite acquisition, baseline handling, change detection, alert generation, persistence, and regional time series |
| observatorio-site | Public pages, interactive maps, charts, prepared web data, rainfall products, educational material, and the chat interface |

### 6.2 Scheduled production

The main detection workflow runs in GitHub Actions every Monday and Thursday:

1. create the Python/geospatial environment;
2. retrieve the 72 baseline COGs from Cloudflare R2;
3. retrieve the current recurrence state;
4. ask Google Earth Engine for recent Sentinel-2 observations;
5. download the daily index composites;
6. run detection, polygonization, and annotation;
7. publish alert files and state to R2;
8. update the regional time-series database in Git.

A second workflow in the site repository starts later. It:

1. retrieves the scientific outputs;
2. prepares lighter files for the browser;
3. creates the default strong subsets and the all-history point view;
4. publishes detailed full files to R2;
5. updates the public manifest and time-series JSON;
6. refreshes recent and historical rainfall products.

The most recent verified cycle at the time of this overview ran successfully on 2026-07-20 and published alert data through the 2026-07-16 satellite observation.

### 6.3 Cloud services

| Service | Role |
|---|---|
| Google Earth Engine | Searches and prepares Sentinel-2 imagery at planetary-data scale |
| GitHub Actions | Runs the scheduled processing and publication jobs |
| Cloudflare R2 | Stores large baseline, alert, and web-data objects |
| Cloudflare Worker | Serves the built site and handles the chat API |
| Git repositories | Version the code, configuration, documentation, and smaller generated products |

The architecture is intentionally modular. The detection system can evolve independently from the site, while the site consumes a defined set of prepared artifacts rather than performing geospatial analysis in the user's browser.

---

## 7. What the public site offers

The monitoring system is presented inside a broader institutional site for the Observatório da Chapada do Araripe. The site connects scientific monitoring with territory, rainfall, education, public participation, and communication.

### 7.1 The Alerts page

The Alerts page has five main tabs.

| Tab | What the visitor can do |
|---|---|
| Visão geral | Explore metrics, dates, alert maps, filters, and the alert table |
| Entenda | Learn how the baseline, indices, confidence, recurrence, and land cover work |
| Séries temporais | Follow regional NDMI, NBR, and EVI2 through time |
| Downloads | Access alert, series, and study-area data products |
| Citação | Find citation and licensing information |

The default map opens with a compact **strong subset** intended as a useful starting point. It combines high spectral confidence, recurrence, and a minimum natural-vegetation fraction. The visitor can then move into a more detailed view with:

- confidence and recurrence filters;
- a minimum number of sightings;
- a choice of MapBiomas collection;
- a natural-cover threshold;
- multiple base maps and land-cover overlays;
- one-date or all-history views.

Clicking an alert opens a summary with date, area, confidence, recurrence, land cover, location, and a Google Maps link. A table supports closer inspection.

The visitor can also draw a polygon on the map and export the selected observations as CSV or GeoJSON. This helps move from regional exploration to a smaller field or research area.

### 7.2 Regional time series

The time-series view shows how the regional mean of each index changes over time and places it alongside the expected monthly baseline range. It gives the alert polygons a broader context: users can see whether a particular observation belongs to a region-wide seasonal movement or a more unusual moment.

### 7.3 Methodology assistant

The Entenda tab includes an AI assistant grounded in a project-specific knowledge base. It can explain the indices, baseline, thresholds, recurrence, and site controls in the language used by the visitor.

The assistant is a communication layer, not part of the detection calculation. Satellite processing is completed beforehand; the assistant helps people understand the results and methodology.

### 7.4 The broader site

Beyond Alerts, the site includes:

- a Territory page with boundaries, landscape context, and rainfall;
- institutional information about the Observatório;
- an Open Data page;
- education and participation areas;
- an experimental Three.js game about land-use choices in the Chapada.

This broader design is important. It places the monitoring data within a social and educational narrative rather than presenting alerts as isolated technical objects.

---

## 8. What has been built so far

As of this overview:

- all 72 monthly baseline COGs are available in cloud storage;
- the headless Sentinel-2 workflow is scheduled twice weekly;
- the alternative streaming workflow remains available for manual use;
- the remote public manifest contains 29 published acquisition dates from 2026-01-02 through 2026-07-16;
- the archive contains more than 350,000 date-level polygon observations;
- the site publishes compact strong files, detailed files, an all-history point index, and regional time series;
- MapBiomas attributes and rainfall context are integrated;
- the Python test suite contains 96 passing offline tests;
- the Vite production site builds successfully;
- monitoring code and data include formal citation and open-license paths.

The alert archive is intentionally observation-based. If the same place appears on several dates, it can be represented several times. This is useful for studying recurrence, but totals across dates should be read as **observations**, not automatically as unique clearings or unique affected area.

For public and scientific communication, the most helpful workflow is:

1. use the strong subset to find places worth examining;
2. inspect the date, confidence, recurrence, land cover, and time-series context;
3. compare with high-resolution reference imagery or field information when a decision requires confirmation.

---

## 9. A simple interpretation guide

### What an alert means

An alert means that the satellite signal changed more than expected for that month and that the changed pixels formed a polygon large enough to retain.

### What confidence means

Confidence describes how strongly and consistently the spectral rules were met. It is a prioritization label, not a probability such as "90 percent certain."

### What recurrence means

Recurrence describes how often an overlapping signal has appeared in the observation history. Repeated appearance can make a location more interesting to investigate.

### What the strong subset means

The strong subset is a presentation filter combining high spectral confidence, recurrence, and natural-vegetation context. It helps a visitor begin with a smaller, more relevant set.

### What the system is designed to support

The system is designed for screening, exploration, research, communication, and prioritization. It helps answer:

- Where did the satellite detect unusual vegetation change?
- When was it observed?
- How strong was the signal?
- Did it recur?
- What land-cover context was present?
- What should be examined more closely?

---

## 10. Why the project matters

This project turns globally available Earth-observation data into a regional public resource. The technical contribution is the complete chain:

    seasonal understanding
        + satellite processing
        + repeatable detection
        + environmental context
        + automated publication
        + accessible communication

The result is more than a detection script and more than a website. It is an early environmental information system built around one place, its seasonal ecology, and the people who need to understand it.

Its open structure also makes the work reusable. The monitoring code is published under AGPL-3.0-or-later, while the monitoring data products use CC BY-SA 4.0. With a new study-area boundary, a rebuilt baseline, and local calibration, the general approach can be adapted to other regions.

---

## Short glossary

| Term | Plain-language meaning |
|---|---|
| AOI | Area of interest: the geographic boundary being monitored |
| Surface reflectance | Satellite measurement corrected to better represent light reflected by the ground |
| Spectral index | A formula combining wavelength bands to highlight a surface property |
| Baseline | The expected condition used for comparison |
| Z-score | A measure of how unusual a value is relative to normal variation |
| Alert polygon | A mapped area whose pixels met the change rules |
| Recurrence | Reappearance of an overlapping signal through time |
| COG | A cloud-friendly GeoTIFF raster format |
| GeoJSON | A web-friendly format for geographic features and attributes |
| GEE | Google Earth Engine |
| R2 | Cloudflare object storage used for large project files |

## Further references

| Resource | URL |
|---|---|
| Monitoring repository | https://github.com/santibravocmcc/Araripe |
| Project DOI | https://doi.org/10.5281/zenodo.19885824 |
| Sentinel-2 SR Harmonized catalog | https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED |
| CHIRPS rainfall data | https://www.chc.ucsb.edu/data/chirps |
| MapBiomas | https://brasil.mapbiomas.org/ |

---

**In one sentence:** the Chapada do Araripe Monitoring System learns the normal seasonal behavior of the landscape from satellite data, identifies unusual vegetation change, adds environmental context, and turns the result into an automated, open, and explorable public resource.
