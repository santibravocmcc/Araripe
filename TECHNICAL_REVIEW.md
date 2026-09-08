# Technical Review: Chapada do Araripe Monitoring System

**Version:** 3.0
**Date:** 2026-07-22
**Prepared for:** Technical and scientific peer review
**Review type:** Repository, automation, storage, deployment, data-product, and interface audit

---

## 0. Executive conclusion

The system is operational: a headless Google Earth Engine (GEE) workflow runs twice weekly, Cloudflare R2 holds the baseline and alert products, the site refresh workflow has published recent alert and rainfall updates, and both the Python test suite and the Vite production build complete successfully.

It is not yet scientifically or operationally safe to present the published alert totals as verified deforestation events. Three correctness defects materially affect interpretation:

1. **Persistence is not idempotent.** The scheduled 16-day overlap, retries, and manual reruns can count the same acquisition date more than once. A track can therefore reach candidate or confirmed status without the required number of distinct satellite observations.
2. **The scheduled GEE path processes an APA bounding rectangle, not the APA polygon.** The rectangle is approximately 2.203 times the polygon area, so the production footprint is materially larger than the stated study area.
3. **The scene-wide anomaly guard uses an incorrect valid-pixel denominator.** Nodata and cloud-masked pixels are counted as valid, which weakens the intended rejection of contaminated scenes.

The current public manifest contains 29 acquisition dates through 2026-07-16 and 352,919 polygon observations. These are repeated per-date observations, not unique events. The reported 6,544 confirmed and 94,910 strong observations are provisional because they depend on the non-idempotent persistence state. The summed 1,897,470.5 ha is likewise not unique affected area and must not be described as cumulative deforestation.

The site has a sound high-level concept and a useful Alerts interface, but the data contract is inconsistent after the move to R2. Full files are no longer deployed with the site, while Home and both download surfaces still link to the retired same-origin locations. Cross-origin full-view access also requires a verified R2 CORS policy; no allow-origin header was observed for the audit request, and the current token cannot inspect the bucket policy. The default strong subset is described as confirmed, although the generator accepts candidates with two or more sightings.

Overall readiness is therefore:

| Dimension | Assessment | Reason |
|---|---|---|
| Automation | Functional, not hardened | Recent scheduled runs succeeded, but publication is non-transactional and has no concurrency guard |
| Scientific detection | Experimental | Rule-based change detection works, but spatial extent, anomaly guard, persistence, and validation require correction |
| Public alert metrics | Provisional | Counts are observations across runs; persistence-derived tiers can be inflated |
| Site | Functional with broken data links | Strong subsets render, but full/download contracts and explanatory copy diverge |
| Storage | Operational, low-cost rather than zero-cost | R2 holds 15.342 GB and uses a public development endpoint |
| Reproducibility | Partial | Unit tests and lockfile-backed site build exist; production environments, deployment, and cloud settings are incompletely codified |

No code, workflow, cloud setting, bucket object, or deployment was changed during this review. This document and its concise companion are the only requested modifications.

---

## 1. Scope, evidence, and review limits

### 1.1 Repositories and snapshots

The review covered the complete tracked structure of both repositories:

| Component | Repository / checkout | Audited state |
|---|---|---|
| Detection and scientific processing | santibravocmcc/Araripe | Local main at adf570f; remote main one generated-data commit ahead at 278c2e3 |
| Public site and Worker | santibravocmcc/observatorio-site | Local main at 832015d; remote main two generated-data commits ahead at 5e4cbed |
| Current published site data | GitHub remote main | Manifest updated 2026-07-20, covering alerts through 2026-07-16 |
| Object storage | Cloudflare R2 bucket araripe-cogs | Read-only object inventory and representative HTTP/object metadata checks |

The code at the local checkouts matches the current remote implementation; the remote-only commits update generated time-series, alerts, and rainfall artifacts. The review used the remote manifest for the current public snapshot.

### 1.2 Material inspected

The audit included:

- 115 tracked files in the detection repository, including 66 Python files, 20 top-level operational scripts, configuration, documentation, data contracts, two GitHub Actions workflows, and 17 test modules.
- 188 tracked files in the site repository, including eight HTML entry pages, JavaScript and CSS, six Python preparation scripts, the Cloudflare Worker, Wrangler configuration, the data-update workflow, generated-data contracts, and deployment documentation.
- The complete live R2 object list, prefix sizes, representative object headers, and direct public access checks.
- Recent GitHub commits and the latest available scheduled workflow evidence.
- The current alert manifest and the tracked time-series/site artifacts.
- Secret-variable names and code paths. Secret values were not read, copied, or reported.

### 1.3 Verification performed

| Check | Result |
|---|---|
| Detection unit/offline tests | 96 passed |
| Python source parsing | 65 of 66 Python files parse under the declared Python 3.11 environment |
| Detection CLI smoke checks | 15 Click-style scripts returned help successfully |
| Site production build | Passed: 59 modules, 126 output files, approximately 187 MiB |
| Site dependency advisory scan | 0 known npm advisories across 65 resolved dependencies |
| R2 baseline inventory | Exactly 72 expected baseline COG objects present |
| Current public manifest | 29 runs through 2026-07-16; totals reconcile within the manifest |

### 1.4 Limits of this review

The following controls could not be independently inspected:

- GitHub branch protection, secret/variable values, and private security settings because the local GitHub CLI token was invalid.
- Live Cloudflare Worker routes, deployed bindings, custom domains, and Worker secret presence because Wrangler authentication was invalid.
- R2 bucket-level CORS, lifecycle, encryption configuration, versioning, and access policy because the available token had object access but received AccessDenied for bucket settings.
- A live field-accuracy assessment, confusion matrix, or independent reference sample; none is currently present.
- End-to-end live GEE/STAC/R2 execution as part of the test suite.

The absence of access to a control is reported as **not verified**, not as proof that the control is absent.

---

## 2. Current architecture and data flow

### 2.1 Production flow

    GitHub Actions (Mon/Thu 06:00 UTC)
        -> GEE Sentinel-2 search over rolling 16 days
        -> daily masked mosaics and NDMI/NBR/EVI2/BSI composites
        -> local detection against 72 monthly baseline COGs fetched from R2
        -> polygonization, land-cover annotation, clearing label, persistence update
        -> source alert GeoJSON + persistence state uploaded to R2
        -> time-series SQLite committed to Araripe main

    Site GitHub Actions (Mon/Thu 07:30 UTC)
        -> clone Araripe and fetch all source alerts from R2
        -> build full site-form GeoJSON and strong subsets
        -> upload full derived files to R2 site-full/
        -> commit manifest, strong files, point index, and series to site main
        -> update GPM rainfall products
        -> Cloudflare deployment assumed outside this repository workflow

    Browser
        -> Worker Static Assets serves Vite dist/
        -> same-origin /api/chat is handled by the Cloudflare Worker
        -> strong alert files load from site assets
        -> full alert files are requested cross-origin from R2

### 2.2 Canonical stores

| Product | Canonical location | Notes |
|---|---|---|
| Baseline COGs | R2 baselines/ | 72 objects; not Git-tracked locally |
| Source alert GeoJSON | R2 alerts/ | 29 current production dates |
| Persistence track state | R2 root persistence_state.geojson | Single mutable 132 MB object |
| Full site-form alerts | R2 site-full/ | Derived copies, including stale unreferenced objects |
| Strong alert subsets | Site Git public/data/alerts/ | Large generated blobs committed to main |
| Regional and alert statistics | Araripe data/timeseries/timeseries.db | Bot-updated SQLite database |
| Public site manifest and charts | Site public/data/ | Bot-updated generated assets |

The storage split is reasonable in principle, but source, state, baseline, and public-derived objects share one bucket. The enabled public bucket URL made representative objects outside site-full/ directly retrievable. Public/private separation is therefore a bucket-level concern, not a prefix-level boundary.

### 2.3 Deployment architecture

The site is no longer a Pages-only static application. It is configured as one Cloudflare Worker deployment:

- Vite builds the eight-page multi-page application to dist/.
- Wrangler binds dist/ as static assets and routes /api/* through the Worker first.
- The Worker exposes POST /api/chat.
- A Workers AI binding is declared.
- CHAT_LIMITER is configured for 8 requests per IP per 60 seconds.
- Provider adapters can select Gemini, Z.ai, Groq, GitHub Models, or Workers AI, depending on bindings/secrets.

README.md and DEPLOY.md still describe a Pages/static-only model and do not provide a reproducible Worker deployment contract.

---

## 3. Repository structure and script review

### 3.1 Detection repository

| Area | Purpose | Review |
|---|---|---|
| config/ | Paths, sensors, thresholds, AOI, storage, band maps | Centralized but contains a third AOI extent and several unused/descriptive settings |
| src/acquisition/ | AOI, STAC, CHIRPS, downloads, GEE initialization | Streaming fallback is modular; live GEE remains outside automated tests |
| src/processing/ | Cloud mask, compositing, indices, SPI | Core formulas are clear; SPI is an approximate non-seasonal implementation |
| src/detection/ | Baseline, pixel detection, vectors, persistence, land cover | Main scientific logic; contains the critical scene-guard and persistence defects |
| src/timeseries/ | SQLite builder, trends, seasonal analysis | Builder is used; trends/seasonal modules are not wired into production |
| src/utils/ | Logging | Simple and adequate |
| scripts/ | Operational CLIs and one-off utilities | Reviewed individually below |
| tests/ | Offline unit tests | Good core coverage, but no cloud/integration/end-to-end path |
| .github/workflows/ | Scheduled GEE and manual streaming workflows | Functional but lacks CI, concurrency, transactional publication, and strict completeness gates |

### 3.2 Detection scripts

| Script group | Files | Current status / finding |
|---|---|---|
| Scheduled production | run_detection_gee.py, run_detection_from_gee.py | Active GEE path; rolling overlap, rectangle AOI, fail-open stages, and non-idempotent persistence |
| Manual fallback | run_detection.py | STAC streaming fallback; uses real AOI polygon but shares persistence and scene-guard defects |
| Baseline production | build_baseline_gee.py, split_gee_baselines.py | Produced current 72 reflectance COGs; GEE build uses rectangle |
| Alternative baseline paths | build_baseline.py, build_baseline_from_downloads.py, download_baseline_data.py | Manual/offline paths; not the scheduled production source |
| GEE manual utility | build_detection_gee.py | Cloud Shell-style script with initialization at import; not a normal testable CLI |
| R2 transfer | fetch_baselines_from_r2.py, fetch_alerts_from_r2.py, upload_to_r2.py, r2_state.py | No checksum/atomic promotion; state get catches all errors; upload helper has an unbound ext branch when explicit content_type is supplied |
| Persistence migration | apply_persistence_filter.py | Legacy strict-persistence utility, not current gap-tolerant production logic |
| Validation and analysis | validate_baseline_data.py, plot_baselines.py, sample_alerts_for_validation.py, select_baseline_years.py | Useful scaffolding; tracked validation predates current reflectance baselines; selection script is invalid under Python 3.11 |
| Land cover preparation | mapbiomas10m_crop.py | One-off data preparation |
| Documentation output | md_to_pdf.py | Generates the review PDFs; not part of scientific production |

The syntax failure is in select_baseline_years.py, which uses nested f-string syntax requiring Python 3.12 while environment.yml declares Python 3.11. The adopted baseline years are also a human decision; the selection JSON does not reproducibly select the published set.

### 3.3 Site repository

| Area | Purpose | Review |
|---|---|---|
| Eight HTML pages | Home, Territory, Alerts, About, Collaborate, Open Data, Education, Game | Valid Vite MPA inputs |
| src/js/ and src/styles/ | Page logic, maps, charts, tabs, forms, responsive styles | Alerts functionality is substantial; accessibility and mobile behavior are incomplete |
| src/jogo/ | Three.js educational game | Lazy-loaded; responsible for the only build chunk warning |
| worker/ | AI chat API and anchored knowledge | Rate-limited and output-escaped; error disclosure, privacy, timeout, and observability gaps remain |
| scripts/ | Alerts, rainfall, territory, education preparation | Production alert preparation retransfers the whole archive; gen_strong.py is obsolete |
| public/data/ | Generated public assets | Large and growing Git history; contains only strong, not full, alert files |
| wrangler.jsonc | Worker assets, AI, and rate-limit bindings | Defines intended deployment, but deploy tooling is not pinned or scripted |
| .github/workflows/update-data.yml | Alerts/series and rainfall refresh | Direct bot pushes; no build/validation, timeout, concurrency, or deploy health check |

### 3.4 Site scripts

| Script | Role | Finding |
|---|---|---|
| prepare_data.py | Alerts, series, manifest, strong/full products | Core production script; full archive downloaded and reuploaded every run; no pruning or provenance schema |
| fetch_gpm.py | Recent GPM rainfall | Active in workflow |
| fetch_gpm_historico.py | Historical GPM rainfall | Active in workflow; large unpinned geospatial install |
| prepare_territorio.py | Territory data | Active data-preparation utility |
| prepare_educacao.py | Education assets | Active data-preparation utility |
| gen_strong.py | Old strong generator | Obsolete because it expects full files under public/data/alerts/ |

### 3.5 Documentation and repository hygiene

Material documentation drift exists in both repositories:

- The previous technical review described headless GEE as future/manual work; it is now scheduled production.
- Backend README and GEE documentation describe old persistence and storage flows.
- Site README and DEPLOY describe Pages/no backend despite the Worker and AI endpoint.
- Site alert copy and baseline captions disagree with the generator and methodology.
- The site workflow still performs Git LFS setup/pull although current alert products no longer use LFS.
- The site tracks two GIS lock files and a large MP4 despite README claims.
- Persistence state and service-account filename patterns are not explicitly ignored in the detection repository.

These are maintainability and accidental-disclosure risks even when current secret files remain untracked.

---

## 4. Scientific method: implemented behavior

### 4.1 Study area

The authoritative AOI file is the APA Chapada do Araripe polygon in data/aoi/APA_chapada_araripe.gpkg. Its measured projected area is approximately 972,183.84 ha.

Three extents currently coexist:

| Path | Extent used | Approximate area / consequence |
|---|---|---|
| Scheduled GEE detection | Bounding rectangle of the APA file | 2,141,901.76 ha; 2.203 times the polygon |
| GEE baseline build | Hard-coded rectangle | Similar rectangular footprint |
| Streaming detector | Actual APA polygon | Correct polygon clip |
| Config fallback and CHIRPS utilities | [-40, -8, -39, -7] | Smaller 1 degree by 1 degree bbox |

The scheduled GEE and streaming paths are therefore not spatially equivalent. A single canonical polygon must be used for baseline, detection, drought aggregation, validation, and publication.

### 4.2 Primary imagery

Scheduled production currently uses COPERNICUS/S2_SR_HARMONIZED only:

- GEE scene-level filter: CLOUDY_PIXEL_PERCENTAGE below 60 percent.
- Rolling search window: 16 days.
- Per-day imagery: SCL-masked and mosaicked.
- Working resolution: 20 m for the detection stack.
- Indices: NDMI, NBR, EVI2, plus BSI for clearing context.

Landsat 8/9 and NASA HLS exist as optional sources in the manual streaming path. The public manifest label currently says Sentinel-2 and Landsat 8/9, which overstates the sensor mix of the scheduled production output.

SCL classes 2, 4, 5, 6, 7, and 11 are treated as clear. Including unclassified/low-probability cloud and snow/ice categories deserves explicit empirical validation for this region. Same-day GEE scenes are combined with mosaic rather than a median composite; selection in overlap areas is order-dependent.

### 4.3 Baseline

The current baseline design is monthly and uses five selected years: 2017, 2019, 2021, 2022, and 2025. GEE uses Sentinel-2 surface reflectance and stores, for each of 12 months and three indices:

- a monthly multi-year median, although files and code refer to mean;
- a monthly standard deviation.

This produces 72 COGs: 12 months x 3 indices x 2 statistics. All 72 are present in R2 and occupy 13.408 GB.

Important limitations:

- The tracked validation report and plots predate the reflectance rebuild and cannot validate the current R2 COGs.
- There is no versioned machine-readable validation report tied to object checksums.
- Baseline selection artifacts recommend/rank different year sets; the adopted set was not an automatic reproducible output.
- Baseline and production GEE use the rectangle rather than the APA polygon.
- The public series caption incorrectly says 2020-2025 instead of the five discrete years.

### 4.4 Spectral indices

The implemented indices are:

    NDMI = (NIR - SWIR1) / (NIR + SWIR1)
    NBR  = (NIR - SWIR2) / (NIR + SWIR2)
    EVI2 = 2.5 * (NIR - RED) / (NIR + 2.4 * RED + 1)

Reflectance scaling is enabled and is scientifically required for EVI2 because of the additive 1 in its denominator. NDMI and NBR are ratio indices and are less sensitive to multiplicative scale.

The baseline and scheduled composites now use reflectance consistently. However, the published SQLite/site series still contains mixed-quality historical records, including very low coverage and implausible EVI2 values on several dates. The current review found no processing-version, source, or coverage fields that allow the site to quarantine those records automatically.

### 4.5 Pixel classification

Current rule-based confidence tiers are:

| Tier | Rule |
|---|---|
| High | Both NDMI and NBR: z below -3.0 and delta below -0.20 |
| Medium | At least one of NDMI/NBR: z below -2.5 and delta below -0.15 |
| Low | Any available index: z below -2.0 and delta below -0.15 |

The detector vectorizes connected alert pixels and retains polygons from 1 to 1,000 ha. These labels are algorithmic rule tiers, not calibrated probabilities and not independent evidence of real deforestation.

### 4.6 Scene anomaly guard

The intended guard rejects a scene when more than 30 percent of valid pixels are flagged. The implementation creates the confidence raster as integer zeros and then defines valid pixels with not-NaN on that integer raster. Integer confidence contains no NaNs, so nodata/cloud pixels are included in the denominator.

A minimal reproduction with two finite source pixels in a four-pixel raster reported four valid pixels. The guard can therefore under-reject atmospheric or processing anomalies, especially over the oversized production rectangle.

### 4.7 Drought adjustment

When enabled, the pipeline computes a three-month precipitation sum from approximately five years of CHIRPS and widens z thresholds by 0.5 when the resulting value is below -1.0.

This should be described as an **SPI-like drought adjustment**, not a standard climatological SPI-3:

- one gamma distribution is fit across all rolling three-month sums rather than separately by calendar ending month;
- the target period is included in the fitted reference;
- the short five-year reference is weak for a strongly seasonal climate;
- one current value is computed per run and applied to every acquisition date in that run, including historical backfills;
- fresh CI runners have no CHIRPS cache and failures disable the adjustment without failing the run.

### 4.8 Land cover and clearing type

Each alert is annotated with both available MapBiomas collections. Land cover does not remove alerts in the backend. The site strong heuristic later requires at least 50 percent natural vegetation in the 10 m product.

The product named mapbiomas30m is actually an approximately 300 m aggregated crop, not a native 30 m raster. It should be renamed or documented accurately.

Fire/mechanical labeling uses the monthly baseline NBR as a pre-event proxy and current NBR/BSI as post-event evidence. It has no dedicated validation or test suite, and a configured high-severity dNBR threshold is unused. This label is contextual, not a verified cause.

### 4.9 Persistence

The current stateful model matches polygons by at least 5 percent overlap and allows a gap of up to 180 days. Tiers are:

- first observation: 1 sighting;
- candidate: 2-14 sightings;
- confirmed: at least 15 sightings, then retained permanently.

This model is not idempotent. update_tracks increments the matched track once on every call, but it does not record which acquisition dates have already contributed. The scheduled Monday/Thursday workflow repeatedly processes an overlapping 16-day window, and manual retries/backfills can process the same date again. Dates older than last_seen are also eligible because the difference check has no lower bound.

Reproduction confirmed that processing the same polygon with the same date twice changes its count from 1 to 2. The existing tests use distinct dates and do not cover duplicates or out-of-order replay.

Consequences:

- persistence_count does not guarantee distinct independent acquisitions;
- candidate, confirmed, and strong classifications can be promoted by reruns;
- the single R2 state object is not a reproducible derivation of the canonical alert archive;
- current confirmed and strong totals must be treated as provisional.

### 4.10 Alert output semantics

An alert GeoJSON feature represents a polygon observation on one acquisition date. The same physical clearing can appear in many run files. Therefore:

- total count across runs is an observation count, not a unique-event count;
- summed hectares across runs double-count repeated places and is not cumulative deforestation;
- first/candidate/confirmed are state labels, not validation outcomes;
- strong is a site presentation heuristic, not a scientific confidence class.

---

## 5. Current data and validation status

### 5.1 Public alert snapshot

The current remote site manifest, updated on 2026-07-20, reports:

| Metric | Value | Correct interpretation |
|---|---:|---|
| Acquisition dates | 29 | Dates with published non-empty alert artifacts |
| Date range | 2026-01-02 to 2026-07-16 | Not necessarily every processed date |
| Polygon observations | 352,919 | Repeated date-level observations |
| Summed area | 1,897,470.5 ha | Sum of observation polygons, not unique area |
| High-confidence observations | 225,477 | Rule-based high tier |
| First observations | 123,508 | Persistence-derived and provisional |
| Candidates | 222,867 | Persistence-derived and provisional |
| Confirmed | 6,544 | Persistence-derived and provisional |
| Strong | 94,910 | High + count at least 2 + natural fraction at least 50 percent; provisional |
| Maximum persistence count | 27 | May include repeated processing of the same date |

The latest published run, 2026-07-16, contains 9,524 polygon observations and 49,311.5 summed ha: 2,945 high, 5,206 medium, and 1,373 low. Its persistence-derived counts are 2,531 first observations, 5,936 candidates, and 1,057 confirmed; its strong subset contains 2,006 observations. These are descriptive pipeline outputs, not validated deforestation statistics.

### 5.2 Time-series database

The audited local database contains 42 dates and three indices through 2026-07-15, plus per-date alert statistics. The remote site series is slightly newer than the local checkout.

Quality concerns include:

- records with very low valid-pixel counts relative to normal dates;
- EVI2 values near zero or above physically credible regional means on several dates;
- a hard-coded baseline-period label that is factually wrong;
- no explicit source sensor, coverage fraction, processing version, baseline version, or QA status;
- no enforced synchronization between last imagery processed, last alert artifact, and last site refresh.

A successful zero-alert rerun can also leave a stale GeoJSON and database row because the detector exits before writing a replacement and R2 upload never deletes old keys.

### 5.3 Validation evidence

Positive:

- Core formulas, vectorization, persistence helpers, and supporting utilities have 96 passing offline tests.
- The baseline R2 inventory is complete.
- The site manifest and strong-file counts reconcile in the audited local snapshot.

Missing or insufficient:

- no independent field/reference sample for the current alert population;
- no confusion matrix, precision, recall, commission, omission, or area-adjusted accuracy;
- no current validation report tied to the reflectance baseline objects;
- no live integration test across GEE download, R2 state, detection, upload, site preparation, and browser rendering;
- no calibration of the high/medium/low rules;
- no validation of persistence tiers after the July 17 model change;
- no validation of fire/mechanical labels or the coarse MapBiomas layer.

The previous claim of an 87 percent reduction from a two-consecutive-observation filter describes a superseded algorithm and is not evidence for the current 15-sighting model.

---

## 6. GitHub Actions and operational settings

### 6.1 Detection workflow

.github/workflows/detect_gee.yml is active:

- trigger: schedule Monday and Thursday at 06:00 UTC plus manual dispatch;
- runner: ubuntu-latest;
- timeout: 120 minutes;
- permissions: contents write;
- environment: Conda from environment.yml plus unpinned pip install of Earth Engine and requests;
- inputs: optional start/end dates;
- outputs: R2 alerts/state and Git-committed time-series.

The latest verified public scheduled run, 29731597443, succeeded on 2026-07-20 and took approximately 50 minutes. Its start was several hours after the nominal cron, so GitHub cron should not be treated as a precise service-level deadline.

.github/workflows/update_data.yml is now a manual-only streaming fallback. Documentation that calls it the scheduled path is obsolete.

### 6.2 Site refresh workflow

The site workflow runs Monday and Thursday at 07:30 UTC:

- alerts job clones Araripe, fetches R2 source data, prepares full/strong products, uploads full products, and commits public/data directly to main;
- rainfall job depends on alerts, downloads recent and historical GPM products, and makes a second direct push;
- retry/rebase logic reduces but does not eliminate races.

Remote bot commits on 2026-07-20 confirm alerts/series and rainfall publication. Cloudflare deployment after those pushes was not independently verified.

### 6.3 Cross-workflow risks

| Risk | Evidence | Impact |
|---|---|---|
| No concurrency group | Both detection workflows and the site workflow permit overlapping runs | Races on state, DB, objects, and direct pushes |
| Single mutable state | One persistence_state.geojson object | Lost updates, silent resets, no deterministic history |
| Fail-open science stages | Composite, SPI, baseline, land cover, date processing, and state-save failures can be skipped/warned | Green workflow with incomplete output |
| Non-transactional publication | Alerts/state upload before Git commit; site objects and Git committed separately | R2 and Git can describe different releases |
| No completeness manifest | No expected/downloaded/processed/published gate | Missing dates or baselines can go unnoticed |
| Direct writes to main | Workflow-wide contents write | Generated changes bypass review |
| No PR CI | Neither repository runs tests/builds on pull requests | Regressions can merge undetected |
| Mutable dependencies | Action major tags, miniforge latest, unpinned pip installs | Runs can change without source changes |

The R2 baseline step is conditional on a non-empty endpoint; a misconfigured workflow can continue to detection without an explicit 72-object success gate. Site rainfall depends on the alerts job, so an unrelated R2 failure suppresses rainfall updates.

### 6.4 Secret and variable contract

Names required by the current code:

| Component | Required names |
|---|---|
| Scheduled GEE | R2_ENDPOINT_URL, R2_ACCESS_KEY, R2_SECRET_KEY, GEE_SA_KEY; EE_PROJECT repository variable |
| Manual streaming | R2 names plus optional EARTHDATA_USERNAME and EARTHDATA_PASSWORD |
| Site alerts | R2_ENDPOINT_URL, R2_ACCESS_KEY, R2_SECRET_KEY; optional R2_BUCKET_NAME |
| Site rainfall | EARTHDATA_USERNAME, EARTHDATA_PASSWORD |
| Worker chat | At least one configured provider/binding; adapters recognize GEMINI_API_KEY, ZAI_API_KEY, GROQ_API_KEY, GITHUB_MODELS_TOKEN, CEREBRAS_API_KEY, NVIDIA_API_KEY, and Workers AI |

The example environment files and deployment docs do not fully document this contract. Backend job-level secrets are exposed to every job step rather than only the steps that need them. No secret values were included in this review.

---

## 7. Cloudflare R2 review

### 7.1 Live inventory

Read-only listing on 2026-07-22:

| Prefix / object | Objects | Size |
|---|---:|---:|
| baselines/ | 72 | 13.408 GB |
| alerts/ | 29 | 1.190 GB |
| site-full/ | 35 | 0.612 GB |
| persistence_state.geojson | 1 | 0.132 GB |
| **Total** | **137** | **15.342 GB** |

All listed objects reported Standard storage. Representative objects had appropriate content types and byte-range support, but no explicit Cache-Control metadata.

### 7.2 Cost status

Cloudflare currently includes 10 GB-month of Standard R2 storage in the free allocation. This bucket alone holds approximately 15.342 GB, about 5.342 GB above that quantity if sustained. Egress remains free under current R2 pricing, but storage and request operations are not guaranteed to remain within free usage.

The correct description is **low-cost or near-zero-cost**, not zero recurring cost. At current scale the direct storage charge exposure is small, but it is non-zero and growing.

### 7.3 Public access and CORS

The site hard-codes an r2.dev public development URL for full alert files. Cloudflare documents r2.dev as rate-limited and intended for non-production traffic; custom domains provide production caching and security controls.

Direct checks found that representative objects under site-full/, alerts/, baselines/, and the root persistence state were publicly retrievable when their paths were known. Prefixes do not create access isolation in a public bucket. The 132 MB internal persistence state and baseline/source objects are therefore inside the public exposure boundary.

An Origin-bearing audit request to a representative full object did not receive Access-Control-Allow-Origin. The repository contains no CORS policy, and the object token could not read the bucket policy. Cross-origin browser fetch of full data must be considered unverified and likely to fail unless the deployed site origin is explicitly allowed.

### 7.4 Lifecycle and transfer behavior

Six site-full objects are not referenced by the current source archive/manifest, including pre-2026/test dates. No lifecycle or sync-delete behavior is codified.

Each site refresh downloads the entire source alert archive and reuploads every staged full file. In the audited local snapshot that was approximately 1.08 GiB downloaded and 0.53 GiB uploaded per cycle. No ETag-based incremental sync, checksum verification, compression, or release manifest is used.

R2 state retrieval treats every exception as a first run. Authentication, DNS, timeout, service, or corruption failures can silently reset continuity, after which the workflow can overwrite the canonical state. Only a confirmed missing-object response should be treated as initialization.

### 7.5 Bucket controls not verified

Bucket-level CORS, lifecycle, encryption configuration, versioning, retention, and token scope could not be read with the current credentials. R2 provides platform encryption at rest, but this review does not infer or certify a particular bucket configuration from an object response.

---

## 8. Site Alerts tab

### 8.1 User-visible structure

The Alerts page contains five sub-tabs:

| Sub-tab | Function |
|---|---|
| Visao geral | Metrics, date selection, Leaflet map, alert table, filters, drawing, and export |
| Entenda | Plain-language method, confidence, persistence, MapBiomas explanation, and AI assistant |
| Series temporais | NDMI, NBR, and EVI2 regional series against monthly baseline bands |
| Downloads | Per-run alert files, series data, and AOI data |
| Citacao | DOI/BibTeX guidance and code/data licenses |

### 8.2 Map modes and filters

Default mode loads a compact strong subset for the selected date. Strong is implemented as:

    confidence = high
    persistence_count >= 2
    MapBiomas 10 m natural fraction >= 0.50

Turning strong off requests the full run from R2 and exposes:

- confidence tier;
- persistence tier and minimum sighting count;
- MapBiomas collection choice;
- minimum natural-vegetation fraction;
- date/run selection.

The map offers base layers, MapBiomas overlays, grouped classes, per-alert popups, approximate municipality/location, clearing type, persistence fields, and a Google Maps link. The table initially renders 10 rows and adds 20 at a time.

All-executions mode is a lightweight panorama of strong observations. It deduplicates points approximately into 0.001 degree cells and omits detailed filters, table, and export. It must not be interpreted as a unique-event dataset.

The drawing tool exports alerts whose approximate centroid falls inside the user polygon. It does not calculate true polygon intersection, and the centroid is a simple vertex average that can be inaccurate for complex polygons and multipolygons.

### 8.3 Data-contract defects

| Defect | Current behavior | User impact |
|---|---|---|
| Retired full-file URLs | Home, Alerts Downloads, and Open Data still build same-origin /data/alerts/run-date.geojson links | Home falls back to old design examples; download links return 404 |
| Cross-origin full fetch | Detail mode fetches hard-coded r2.dev site-full URL | Can be blocked without exact CORS policy; fallback communication is weak |
| Strong vs confirmed wording | UI says strong means confirmed; code accepts count >=2 | Most strong observations may be candidates, not confirmed |
| Contradictory confirmation copy | One paragraph says confirmed on the next observation; actual confirmed threshold is 15 | Users receive two incompatible definitions |
| Baseline caption | Series says 2020-2025; method uses five discrete years | Provenance is misleading |
| Aggregate labels | Alertas totais and Area afetada sum run observations | Implies unique totals when data are repeated |
| Source label | Manifest names Sentinel-2 and Landsat | Scheduled production is Sentinel-2-only |
| Freshness semantics | last_run means latest non-empty artifact | Does not show latest processed date or successful zero-alert run |

In strong mode, the metric for first observations is necessarily zero because strong requires at least two sightings. Showing it as a prominent metric in that mode is confusing.

### 8.4 Manifest and provenance

The manifest includes filenames, dates, per-run counts, aggregate totals, last run, and a generic source. It lacks:

- schema version and generation timestamp;
- pipeline and baseline version;
- latest imagery date versus latest non-empty alert date;
- run ID and release ID;
- sensors, scene IDs, cloud/coverage, and processing status per date;
- checksums and explicit download URLs;
- QA flags for mixed-quality time-series records.

Presentation IDs are sequential and can change when the archive/order changes; they are not durable event identifiers.

### 8.5 AI assistant

Positive controls:

- same-origin API route;
- rate-limit binding;
- client-side escaping before limited Markdown display;
- bounded turns/message length in the Worker;
- no-store responses;
- anchored project knowledge.

Gaps:

- public debug=1 can reveal provider failure details;
- total failure returns joined upstream error text to any user;
- sequential provider retries can produce long latency and lack one global request budget;
- rate limiting fails open if the binding errors;
- no health check, structured observability, circuit breaker, or AI evaluation suite;
- prompts may be sent to multiple third-party providers, but the page has no provider/privacy disclosure;
- cost is described as guaranteed zero although external tiers and quotas can change.

### 8.6 Accessibility and security headers

The site lacks automated accessibility tests. Alert rows are clickable div elements rather than keyboard-accessible table controls, tabs lack full keyboard/ARIA behavior, chips do not expose pressed state, animations do not honor reduced-motion preferences, and several layouts remain weak on small screens.

The published header file provides nosniff and a referrer policy but no tested Content-Security-Policy, frame-ancestor protection, or Permissions-Policy. GPX/GeoJSON trail names are inserted through innerHTML in the education page, creating a local-file-driven DOM injection path.

License wording also needs separation: site/game/Worker code is described as proprietary in NOTICE, while Alerts/Open Data broadly call code AGPL. The upstream monitor code, site code, game assets, and data products should each have an explicit license statement.

---

## 9. Software quality and reproducibility

### 9.1 Detection environment

environment.yml declares Python 3.11 and broad lower-bound dependencies. requirements.txt is not equivalent: it omits botocore bounds and several direct operational imports. Earth Engine, requests, pandas, matplotlib, reportlab, and pytest are not consistently declared across all installation paths.

There is no lockfile or hash-pinned environment. The audited local environment also fails pip check because installed boto3 and botocore patch versions are incompatible. Several large declared packages have no current production import.

Required action: establish one reproducible environment per workflow, lock it, and test installation from scratch.

### 9.2 Site environment

The site has a Node 20 declaration and a package-lock. Locked direct versions are Leaflet 1.9.4, Three 0.183.2, and Vite 6.4.3. The production build passes. The main concern is payload scale: generated strong GeoJSON dominates an approximately 187 MiB build, and the Three.js chunk is approximately 523 kB minified.

Wrangler is not a project dependency and there is no deploy npm script. Cloudflare deployment cannot be reproduced from package scripts alone.

### 9.3 Test and CI gaps

- Detection: 96 passing offline tests, but no GitHub workflow runs them.
- Site: no unit, integration, accessibility, link, or browser tests.
- Neither repo builds/tests pull requests.
- No test covers duplicate-date persistence, out-of-order replay, R2 state failure, zero-alert correction, AOI equivalence, valid-pixel denominator, manifest schema, CORS/full fetch, or download URLs.
- No post-deploy health check verifies site assets, full alerts, downloads, API chat, and freshness.

---

## 10. Prioritized risk register

| Finding (severity) | Consequence |
|---|---|
| [P0] Persistence counts duplicate processing dates | Candidate/confirmed/strong tiers and current totals are unreliable |
| [P0] Scheduled GEE uses APA bounding rectangle | Alerts and baselines cover a much larger area than stated |
| [P0] Scene guard counts nodata/cloud pixels as valid | Contaminated scenes can pass the 30 percent rejection guard |
| [P1] No independent alert accuracy assessment | Confidence cannot be translated into real-world reliability |
| [P1] R2 state failures reset silently | Continuity can be destroyed while workflow stays green |
| [P1] Home and download URLs use absent full files | Public data links are broken and Home can display stale examples |
| [P1] Full-view CORS/custom-domain configuration is not verified | Advanced alert exploration may fail in browsers |
| [P1] One public bucket exposes public-derived, source, baseline, and state objects | Internal state and large source products are publicly retrievable |
| [P1] Publication is non-transactional and unconstrained | Concurrent/partial runs can create inconsistent R2 and Git state |
| [P1] Time series contain mixed/low-coverage records without QA metadata | Public charts can combine incompatible processing generations |
| [P1] Site strong/confirmed and aggregate-area wording is inaccurate | Technical and public users can misinterpret the products |
| [P1] R2 footprint exceeds current free storage allowance | Zero-cost claim is false and growth is unmanaged |
| [P2] Fail-open scientific stages lack completeness gates | Successful workflow can publish incomplete runs |
| [P2] Dependencies/deployments are incompletely pinned | Reproducibility and supply-chain control are weak |
| [P2] No PR CI and no site test suite | Regressions are detected late |
| [P2] Full archive is retransferred and generated blobs grow Git history | Runtime, repository, and deployment scale will degrade |
| [P2] Worker error/privacy/timeout controls are incomplete | Operational detail leakage and poor chat reliability |
| [P2] Accessibility/mobile/header gaps | Reduced usability and weaker browser security posture |
| [P3] Obsolete scripts/docs/settings and ambiguous licenses remain | Maintenance mistakes and user confusion |

---

## 11. Remediation roadmap

### Phase 0 - Protect interpretation and stop state inflation

1. Add a public caveat immediately: all persistence-derived metrics are provisional, and area/count totals are observations rather than unique events.
2. Make persistence idempotent using a stable observation key such as acquisition date plus source/scene ID per track. A replay of an already-processed observation must make no state change.
3. Reject out-of-order mutation of live state. Corrections/backfills should rebuild deterministically from the canonical archive.
4. Rebuild persistence state chronologically after the fix, then regenerate all source labels, site strong subsets, manifest totals, and time series.
5. Use the real APA polygon everywhere and reprocess baselines/alerts or explicitly redefine the published monitoring extent.
6. Compute the scene-guard denominator from the finite source/reference mask and add regression tests.

Exit criterion: identical-date replay is a no-op; scheduled and streaming AOIs match; current published tiers are regenerated from distinct acquisitions.

### Phase 1 - Restore the public data contract

1. Move production full assets behind an R2 custom domain or Worker route.
2. Configure and test CORS for the exact deployed origin.
3. Repair Home, Alerts Downloads, and Open Data URLs; add automated link checks.
4. Separate public site-full objects from private baseline/source/state objects, ideally into different buckets/tokens.
5. Add Cache-Control, compression where appropriate, and an explicit release manifest.
6. Correct strong/confirmed copy, baseline-period caption, sensor source, aggregate labels, and freshness labels.
7. Remove stale Home design examples or visibly label them as examples.

Exit criterion: browser smoke test loads strong and full modes; all download links return the intended artifact; no internal state object is publicly exposed.

### Phase 2 - Make publication deterministic and recoverable

1. Add one shared concurrency group across scheduled and manual detection, with cancel-in-progress false.
2. Treat only NoSuchKey as first-state initialization; fail on other R2/state errors.
3. Validate state schema, expected baselines, downloaded dates, processed dates, uploaded keys, and time-series rows.
4. Publish under a run-specific staging prefix and atomically promote a small release manifest after every component succeeds.
5. Use ETag/conditional writes or versioned release objects; retain tested rollback copies.
6. Clear or tombstone stale alert objects/database rows after a corrected zero-alert rerun.
7. Make site sync incremental and prune only after a reviewed dry run.

Exit criterion: a failed/racing run cannot overwrite good state or expose a partial release.

### Phase 3 - Establish scientific validity

1. Design a stratified independent reference sample across confidence, season, land cover, polygon size, and persistence tier.
2. Estimate precision, recall, commission, omission, and area-adjusted uncertainty.
3. Rebuild and validate the reflectance baseline with versioned checksums and per-month coverage statistics.
4. Recompute/quarantine mixed time-series dates and add source, clear coverage, processing version, baseline version, and QA fields.
5. Replace the SPI-like adjustment with calendar-month-stratified climatology or label it experimental; compute it for each observation date.
6. Validate the cloud mask, GEE mosaic choice, land-cover resolution, and fire/mechanical label.
7. Define a stable event/track ID and separate observation, track, and unique-area products.

Exit criterion: public claims are supported by a versioned validation report and uncertainty statement.

### Phase 4 - Reproducibility, security, and UX

1. Add PR CI: Python install/test/lint/parse; Node install/build/audit; manifest/schema/link/browser smoke tests.
2. Lock workflow dependencies and pin GitHub Actions by reviewed commit SHA.
3. Add Wrangler as a project dependency with documented build/deploy/rollback scripts.
4. Add structured logs, run summaries, alerting, post-deploy health checks, and freshness monitoring.
5. Remove public AI debug detail, add one global timeout/circuit breaker, and publish a provider/privacy notice.
6. Add CSP/frame/permissions headers and fix local-file DOM injection.
7. Complete keyboard, ARIA, reduced-motion, and mobile behavior.
8. Reconcile documentation, remove obsolete utilities, and clarify licenses.

---

## 12. What can be trusted today

### Reasonably supported

- The repositories contain an implemented, automated Sentinel-2 change-detection system.
- The 72 reflectance baseline objects exist in R2.
- The most recent verified scheduled backend and site refresh workflows completed successfully.
- The core offline Python tests pass and the site production build succeeds.
- The current manifest accurately describes the generated files and per-run counts it was built from.
- NDMI, NBR, and EVI2 formulas and the stated rule thresholds match the code.

### Must be treated as provisional

- persistence_count, candidate, confirmed, and strong totals;
- any claim that a confirmed feature represents 15 distinct independent observations;
- cumulative alert counts or hectares as unique deforestation;
- the monitoring extent as the APA polygon;
- public full-view availability until CORS is verified from the deployed origin;
- mixed historical time-series values without coverage/version QA;
- fire/mechanical and confidence labels as real-world validation;
- zero-cost operation.

### Not currently demonstrated

- field accuracy or operational detection performance;
- complete cloud IAM/bucket policy hardening;
- reproducible Worker deployment and rollback;
- transactional recovery from failed or concurrent runs;
- accessibility conformance;
- a production service-level freshness guarantee.

---

## Appendix A. Key operational configuration

| Setting | Current value / behavior | Review note |
|---|---|---|
| Scheduled cadence | Monday/Thursday 06:00 UTC | GitHub schedules are best-effort |
| Site refresh cadence | Monday/Thursday 07:30 UTC | Assumes backend completion; no freshness dependency check |
| Detection window | Rolling 16 days | Creates duplicate-date replay risk |
| Production source | Sentinel-2 SR Harmonized | Manifest should not imply routine Landsat use |
| GEE scene cloud filter | Below 60 percent | Pixel mask still essential |
| Working scale | 20 m | Matches SWIR bands |
| Minimum clear coverage | 20 percent | Based on finite composite pixels |
| Baseline years | 2017, 2019, 2021, 2022, 2025 | Human-selected discrete years |
| High threshold | z below -3.0 and delta below -0.20 in NDMI and NBR | Rule tier, not probability |
| Medium threshold | z below -2.5 and delta below -0.15 in a moisture index | Rule tier |
| Low threshold | z below -2.0 and delta below -0.15 in any index | Rule tier |
| Polygon area | 1-1,000 ha | Large scene artifacts separately guarded |
| Scene guard | Reject above 30 percent flagged | Denominator bug must be fixed |
| Drought trigger | SPI-like value below -1.0; z widened by 0.5 | Experimental implementation |
| Persistence match | At least 5 percent current-polygon overlap | Asymmetric; split/merge behavior can be unstable |
| Persistence gap | 180 days | Confirmed tracks retained permanently |
| Tiers | 1 / 2-14 / 15+ | Counts currently non-idempotent |
| Strong site subset | high + count at least 2 + natural10 at least 50 percent | Includes candidates and confirmed |
| R2 bucket | araripe-cogs | Public/private products share bucket |
| Worker rate limit | 8 requests/IP/60 seconds | Fails open on binding error |

## Appendix B. Suggested minimum release manifest

Each published release should record:

- release_id and generated_at;
- backend commit, site commit, workflow run ID, and processing version;
- baseline version and object checksums;
- canonical AOI checksum and area;
- start/end dates, expected scene dates, processed dates, skipped dates, and reasons;
- per-date sensor/scene IDs, cloud/clear coverage, and QA status;
- persistence state input/output versions and distinct observation watermark;
- alert, state, database, and site-object checksums;
- latest imagery date, latest processed date, latest non-empty alert date, and site deployment time;
- validation-version reference;
- publication status and rollback pointer.

## Appendix C. External references

| Reference | URL |
|---|---|
| Cloudflare R2 pricing | https://developers.cloudflare.com/r2/pricing/ |
| Cloudflare R2 public buckets and custom domains | https://developers.cloudflare.com/r2/buckets/public-buckets/ |
| Cloudflare R2 CORS | https://developers.cloudflare.com/r2/buckets/cors/ |
| Sentinel-2 User Handbook | https://sentinels.copernicus.eu/web/sentinel/user-guides/sentinel-2-msi |
| GEE Sentinel-2 SR Harmonized catalog | https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED |
| CHIRPS | https://www.chc.ucsb.edu/data/chirps |
| MapBiomas | https://brasil.mapbiomas.org/ |

---

**Bottom line:** the architecture is viable and automation is demonstrably running, but the current alert state must be rebuilt after correcting duplicate-date persistence, spatial extent, and scene validity. Until then, the site should present outputs as unvalidated change observations and avoid unique-event, confirmed, or cumulative-area claims.
