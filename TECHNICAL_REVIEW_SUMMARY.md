# Concise Technical Review: Chapada do Araripe Monitoring System

**Version:** 1.0
**Date:** 2026-07-22
**Audience:** Technical colleague handoff
**Scope:** Detection repository, site repository, GitHub Actions, Cloudflare R2, and the Alerts tab

---

## 1. Bottom line

The monitoring system is real, automated, and technically substantial. A scheduled Google Earth Engine pipeline processes Sentinel-2 imagery twice weekly, stores baselines and alerts in Cloudflare R2, updates a public Vite/Cloudflare Worker site, and exposes maps, time series, downloads, rainfall, and an AI methodology assistant.

The current outputs should nevertheless be treated as **experimental change observations, not verified deforestation statistics**. The most important reason is a persistence defect: the same satellite date can be counted again when the rolling 16-day window overlaps, a job retries, or a manual rerun occurs. As a result, the public candidate, confirmed, and strong totals may be inflated.

Two other correctness issues need early attention:

- scheduled GEE processing uses the APA bounding rectangle rather than the APA polygon, covering about 2.2 times the intended area;
- the scene-wide anomaly check counts nodata/cloud pixels in its denominator, weakening rejection of contaminated scenes.

The public site is useful, especially its Alerts tab, but the R2 migration left broken download/Home links and an unverified cross-origin full-data path. The site also describes strong as confirmed, although strong includes candidates from two sightings onward.

**Recommendation:** keep the system online, but add an interpretation warning, correct the three scientific-state defects, rebuild persistence deterministically, and then republish the alert products before using confirmed/strong statistics for decisions.

---

## 2. System in one view

    Backend Actions -> GEE composites -> detection/persistence -> R2 and Git
    Site Actions -> R2 source alerts -> full/strong products -> site data/rainfall
    Cloudflare Worker -> eight-page Vite site -> Alerts UI and /api/chat

| Component | Current status |
|---|---|
| Scheduled detector | Active; latest verified scheduled run succeeded on 2026-07-20 |
| Baseline store | Complete: 72 monthly reflectance COGs |
| Source alert store | 29 run files through 2026-07-16 |
| Site refresh | Alerts/series and rainfall bot commits published on 2026-07-20 |
| Python tests | 96 passed |
| Site build | Passed; 59 modules and 126 output files |
| npm advisory scan | 0 known advisories |
| Scientific validation | Not yet sufficient for operational deforestation claims |

The site is not Pages-only. It is configured as a Cloudflare Worker serving static assets and a chat API, with Workers AI and an 8 requests/IP/minute limiter. The repository documentation still describes the older static-only deployment.

---

## 3. Current published snapshot

The remote manifest currently reports:

| Metric | Value | Interpretation |
|---|---:|---|
| Published acquisition dates | 29 | 2026-01-02 through 2026-07-16 |
| Polygon observations | 352,919 | Observations across dates, not unique events |
| Summed observation area | 1,897,470.5 ha | Repeats the same places across runs |
| High-confidence observations | 225,477 | Rule-based spectral tier |
| Candidate | 222,867 | Provisional persistence label |
| Confirmed | 6,544 | Provisional; may include duplicate-date increments |
| Strong | 94,910 | High + at least 2 sightings + natural cover; provisional |
| Maximum reported sightings | 27 | Not guaranteed to be 27 distinct dates |

The latest run, 2026-07-16, contains 9,524 polygon observations and 49,311.5 summed ha. Those numbers describe that generated artifact; they do not show 9,524 independently verified clearings or 49,311.5 ha of new deforestation.

### What can be shared safely

- The system produced these many **algorithmic polygon observations**.
- High, medium, and low are threshold-based spectral classes.
- Alerts are candidates for investigation and field/reference verification.
- The 72 baseline objects exist and the automation has run successfully.

### What should not yet be claimed

- Confirmed means 15 distinct satellite observations.
- Strong means independently confirmed deforestation.
- Total hectares is unique affected area.
- The monitoring footprint is exactly the APA polygon.
- The current totals have known precision/recall.

---

## 4. How detection works

Production currently uses Sentinel-2 Surface Reflectance Harmonized in GEE. It searches a rolling 16-day window, masks scenes, builds one composite per acquisition date, and compares three indices with monthly baselines:

- **NDMI:** vegetation moisture;
- **NBR:** moisture/burn response;
- **EVI2:** vegetation vigor.

The baseline uses five selected years: 2017, 2019, 2021, 2022, and 2025. For each month and index, R2 stores a median and standard-deviation COG, for 72 objects in total.

Pixel confidence rules are:

| Class | Simplified rule |
|---|---|
| High | NDMI and NBR both show very large negative z-score and delta |
| Medium | At least one moisture index shows a large negative change |
| Low | Any index crosses the lower anomaly threshold |

Connected pixels become 1-1,000 ha polygons. MapBiomas attributes and a provisional fire/mechanical label are added. These classifications are useful triage signals, not calibrated probabilities.

Persistence is intended to reconnect the same place for up to 180 days:

- 1 sighting: first observation;
- 2-14: candidate;
- 15 or more: confirmed.

The implementation currently increments a matched track every time a file is processed, without remembering which acquisition dates were already counted. That is the highest-priority correction.

The drought adjustment is better described as an SPI-like experimental modifier. It uses a short, non-seasonally stratified CHIRPS reference and applies one current value across a run; it is not a fully standard SPI-3 implementation.

---

## 5. Alerts tab: what a colleague will see

The Alerts page has five sections.

### Visao geral

This is the main operational map. It shows run metrics, alert polygons or points, a table, and filters.

Default view uses the **strong subset**:

    high confidence
    + persistence_count at least 2
    + MapBiomas 10 m natural vegetation at least 50 percent

Strong therefore includes candidates as well as confirmed features. The current page copy incorrectly says it requires confirmed persistence.

When strong is turned off, the interface attempts to load the full run from R2 and enables confidence, persistence, minimum-sightings, land-cover, and natural-cover filters. The map supports base layers, MapBiomas overlays, popups, approximate location, a Google Maps field link, and incremental table loading.

All-executions mode is a lightweight point panorama of strong observations. It performs approximate spatial deduplication for display but is not a unique-event dataset.

The drawing/export tool selects features by an approximate centroid inside the drawn polygon. It is not a true polygon-intersection query.

### Entenda

This section explains the baseline, indices, confidence, persistence, and MapBiomas context. It also loads the AI assistant, which answers from an embedded project knowledge base.

The assistant is rate-limited and escapes output, but the site should disclose that prompts may pass through different AI providers. Public debug/error detail, long sequential fallback, and lack of a global timeout are operational gaps.

### Series temporais

The page plots NDMI, NBR, and EVI2 against monthly baseline bands. The current caption says 2020-2025, while the actual baseline is the five discrete years above. Some tracked records also show low coverage or implausible EVI2 values and lack processing-version/QA fields.

### Downloads

The page lists per-run GeoJSON and supporting data. The per-run full links currently point to files that are no longer deployed with the site, so they return 404. The Open Data page and Home use the same retired path.

### Citacao

This section provides citation and license guidance. License wording should more clearly separate upstream monitor code, site/game/Worker code, and data products.

---

## 6. Main risks, in priority order

| Finding (severity) | Immediate response |
|---|---|
| [P0] Duplicate-date persistence inflation | Make updates idempotent and rebuild state chronologically |
| [P0] GEE uses a rectangle 2.203 times the APA polygon | Use one canonical polygon and reprocess affected products |
| [P0] Scene anomaly denominator includes invalid pixels | Derive validity from finite source data and add a regression test |
| [P1] No independent accuracy assessment | Keep alert language provisional; design a stratified validation sample |
| [P1] R2 state errors can silently start from zero | Fail closed except on a confirmed missing object |
| [P1] Home and full-download paths are broken | Point them to the production R2/Worker asset contract and test links |
| [P1] Full-view CORS/custom domain is not verified | Use a production custom domain and exact-origin CORS |
| [P1] Source, baseline, state, and public files share one public bucket | Separate public and private storage boundaries |
| [P1] No concurrency or atomic release | Serialize runs and publish with staging plus a release manifest |
| [P1] Published wording overstates strong, totals, sources, and baseline period | Correct the UI and manifest semantics |
| [P2] No PR CI/site tests and mutable dependencies | Add install/test/build/schema/link checks and lock environments |
| [P2] R2 and Git data grow inefficiently | Incremental sync, compression/tiling, pruning, and small Git manifests |
| [P2] Worker privacy/error/timeout and site accessibility gaps | Remove debug detail, disclose providers, harden headers, and add keyboard/mobile QA |

---

## 7. R2 and operating cost

Live read-only inventory:

| Product | Objects | Size |
|---|---:|---:|
| Baselines | 72 | 13.408 GB |
| Source alerts | 29 | 1.190 GB |
| Full site alerts | 35 | 0.612 GB |
| Persistence state | 1 | 0.132 GB |
| **Total** | **137** | **15.342 GB** |

The current R2 Standard free allocation includes 10 GB-month. This bucket alone is above that quantity, so the system is low-cost rather than guaranteed zero-cost. The overage is small at present but should be monitored as alerts and generated copies grow.

The site uses an r2.dev public endpoint. Cloudflare documents that endpoint for non-production, rate-limited traffic. A custom domain is the appropriate production path for caching and security controls.

Representative public checks also showed that objects outside site-full, including the persistence state and baselines, were retrievable when their paths were known. Public and private data should not rely on prefixes inside one public bucket.

Bucket-level CORS, lifecycle, versioning, encryption configuration, and access policy could not be read with the available object token. They must be verified in the Cloudflare account; they are not assumed absent.

---

## 8. Recommended handoff plan

### First: protect the meaning of current data

1. Add a site note that counts are run observations, area is not unique, and persistence tiers are provisional.
2. Stop using confirmed or strong totals in decision material until state is rebuilt.
3. Keep raw acquisition-date outputs as the canonical replay source.

### Then: correct and republish

1. Store a distinct observation ID/date set or watermark per track.
2. Make duplicate and out-of-order replay deterministic.
3. Use the APA polygon consistently.
4. Fix the valid-pixel scene guard.
5. Rebuild all state chronologically and regenerate the manifest/site.
6. Recompute or quarantine mixed-quality time-series dates.

### Restore reliable delivery

1. Put public full data behind a custom domain or Worker route.
2. Fix CORS and all Home/Download URLs.
3. Split public site products from private source/baseline/state storage.
4. Add Cache-Control, checksums, incremental sync, pruning, and release manifests.
5. Add shared workflow concurrency, fail-closed state handling, and completeness gates.

### Establish scientific confidence

1. Create a stratified independent validation sample.
2. Report precision, recall, commission, omission, and uncertainty.
3. Add stable track IDs and separate observation counts, unique tracks, and unique-area estimates.
4. Version the AOI, baseline, algorithm, and every release.

---

## 9. Overall assessment

This is a promising and already functioning research/monitoring platform. Its strongest assets are the automated satellite pipeline, complete baseline store, transparent rule logic, useful public interface, and open data intent.

Its main weakness is not lack of implementation; it is that operational reruns, spatial extent, and publication semantics can change the meaning of the output without visibly failing. Correcting those state and provenance issues should come before threshold tuning or new features.

After the persistence rebuild, AOI correction, scene-guard fix, public data-contract repair, and independent validation, the project can move from an experimental alert demonstrator toward a defensible operational monitoring product.

For implementation evidence, file-level findings, environment variables, storage limits, and the complete remediation roadmap, see **TECHNICAL_REVIEW.md**.
