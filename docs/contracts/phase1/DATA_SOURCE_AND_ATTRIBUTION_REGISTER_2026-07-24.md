# Phase 1 data-source and attribution register

**Register date:** 2026-07-24

**Scope:** monitoring/backend, generated site data, and public map/reference layers

**Status:** accepted for Phase 1 on 2026-07-28 with assigned later provenance
and scientific gates; no production data was changed

This register distinguishes four kinds of evidence:

- **Verified local:** read from the checked-out source, file header, filesystem
  metadata, or a local checksum.
- **Verified upstream:** read from an official provider page on the register
  date.
- **Historical:** taken from a dated audit and not re-verified as current.
- **Unresolved:** the repository does not yet preserve enough evidence to make
  the claim reproducible.

URLs and identifiers in this document are public dataset identifiers. Secret
values, private endpoints, and credential material are deliberately excluded.

## 1. Canonical monitoring extent

The scheduled GEE detector currently obtains the bounds of
`data/aoi/APA_chapada_araripe.gpkg` and constructs a non-geodesic EPSG:4326
rectangle. That rectangle, rather than the APA polygon alone, is the operational
monitoring extent for Phase 1.

| Field | Registered value |
| --- | --- |
| Extent ID | `araripe-implementation-rectangle-v1` |
| Source file | `data/aoi/APA_chapada_araripe.gpkg` |
| Source SHA-256 | `2bff31afa6cb74630a437b4fffb96ad88f7f873a3aa1461f337c66f61c209881` |
| Source CRS / features | EPSG:4326 / 1 |
| Exact W,S,E,N | `[-40.89236812577142, -7.840780758480428, -38.95208146319247, -6.957104781339829]` |
| Rectangle geometry SHA-256 | `b4986ef80d8a0d6e65bbb41b575dbd952c010415bf3aee93a88412b3b657e8c7` |
| Bounds-array SHA-256 | `93f254373d6b203bca33aa5c356bd03fec3bff7f43c9c15b368cc2bdb7029f28` |
| Equal-area calculation CRS | EPSG:32724 |
| APA polygon area | `972183.8447659418 ha` |
| Monitoring rectangle area | `2092576.6787705552 ha` |

The canonical compact geometry used for the geometry hash is:

```json
{"coordinates":[[[-40.89236812577142,-7.840780758480428],[-38.95208146319247,-7.840780758480428],[-38.95208146319247,-6.957104781339829],[-40.89236812577142,-6.957104781339829],[-40.89236812577142,-7.840780758480428]]],"type":"Polygon"}
```

Known drift that must be removed in Phase 2:

- `scripts/build_baseline_gee.py` uses the rounded rectangle
  `[-40.90, -7.85, -38.95, -6.95]`, not the exact registered extent.
- `config/settings.py` retains the fallback
  `[-40.0, -8.0, -39.0, -7.0]`.
- the site territory/education window is
  `[-41.0, -8.0, -38.8, -6.8]`, and the GPM acquisition window is
  `[-41.15, -8.10, -38.70, -6.73]`.

Those larger or different rectangles may remain valid for presentation or
acquisition padding, but every derived artifact must name which registered
extent it uses. They must not be described as interchangeable AOIs.

## 2. Operational monitoring sources

### 2.1 Sentinel-2 surface reflectance

| Field | Registered value |
| --- | --- |
| Provider / producer | Google Earth Engine catalog; European Union/ESA/Copernicus |
| Collection ID | `COPERNICUS/S2_SR_HARMONIZED` |
| Official catalog | <https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED> |
| Availability / cadence | From 2017-03-28; nominal 5-day revisit |
| Native data | Level-2A surface reflectance, UINT16, reflectance scaled by 10,000; bands at 10 m, 20 m, and 60 m |
| Terms | Copernicus Sentinel Data Terms and Conditions, linked from the official catalog |
| Upstream review date | 2026-07-24 |

Current baseline transform, verified from
`scripts/build_baseline_gee.py`:

1. Query years 2017, 2019, 2021, 2022, and 2025, by calendar month.
2. Apply the scene-level cloud percentage filter.
3. Retain SCL classes `2, 4, 5, 6, 7, 11`.
4. Divide B4/B8/B8A/B11/B12 values by 10,000.
5. Derive NDMI, NBR, and EVI2.
6. Pool scenes with the median and standard deviation for each month.
7. Clip to the rounded baseline rectangle, fill masked pixels with `-9999`,
   and export float GeoTIFFs in EPSG:32724 at 20 m.
8. Split each monthly export into the current 72 baseline components.

Current scheduled-observation transform, verified from
`scripts/run_detection_gee.py`:

1. Query the registered monitoring rectangle and date window, with
   `CLOUDY_PIXEL_PERCENTAGE < 60`.
2. Retain the same SCL classes and divide reflectance by 10,000.
3. Derive NDMI, NBR, EVI2, and BSI.
4. Mosaic images by acquisition date, clip to the rectangle, and fill masked
   pixels with `-9999`.
5. Download EPSG:32724, 20 m tiles and run the local detector against the
   monthly baseline.

The current pipeline does **not** persist the complete set of Earth Engine
asset IDs, processing baselines, source checksums/ETags, query fingerprint, or
per-date scene list in a processing ledger. Phase 2 publication must be blocked
until those fields are captured by the versioned ledger/release contracts.

### 2.2 CHIRPS 2.0 monthly precipitation

| Field | Registered value |
| --- | --- |
| Provider | Climate Hazards Center, UC Santa Barbara |
| Dataset | CHIRPS 2.0 monthly precipitation |
| Official README | <https://data.chc.ucsb.edu/products/CHIRPS-2.0/README-CHIRPS.txt> |
| Exact base URL in code | <https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs> |
| Exact file pattern | `chirps-v2.0.YYYY.MM.tif.gz` |
| Resolution / coverage | 0.05 degree; 1981 to near-real-time |
| Expected CRS / NoData | Geographic lon/lat; negative values, including `-9999`, are treated as NoData |
| Upstream review date | 2026-07-24 |

Current transform:

1. Download and decompress each global monthly GeoTIFF, checking HTTP length
   where available and verifying that Rasterio can open the result.
2. Read the pixel window intersecting the requested rectangle.
3. Convert all negative values to NaN and calculate the unweighted regional
   pixel mean in mm/month.
4. Build rolling three-month sums over approximately five years and fit a gamma
   distribution; use a z-score fallback when there are fewer than ten non-zero
   observations or the fit fails.
5. Drop unpublished trailing months. A missing/failed SPI currently returns or
   collapses to `0.0`, and detection continues.

License/attribution status is **unresolved** in the repository: the project
credits CHIRPS/UCSB but does not pin a license text or citation in generated
releases. Raw redistribution must remain disabled until that is reviewed.
Derived values should identify CHIRPS 2.0, the provider, source URL, access
date, months used, and transform version.

The official README says CHIRPS 2.0 production will end after December 2026.
A CHIRPS 3 migration decision, overlap comparison, and release cutover are
therefore time-bounded operational requirements, not optional cleanup.

## 3. MapBiomas national sources acquired for Phase 2

The five files below are local, ignored source inputs under
`data/landcover/updated/`. The browser download-origin metadata records
2026-07-23 as the acquisition date for the original four inputs; the official
national Collection 10 legend fixture was acquired and checksum-bound on
2026-08-11. The two national rasters were not rewritten, staged, or uploaded
during Phase 1.

### 3.1 File inventory

| Local file | Exact origin URL | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `ATBD-Collection-10.1.pdf` | <https://brasil.mapbiomas.org/wp-content/uploads/sites/4/2026/02/ATBD-Collection-10.1.pdf> | 4,476,538 | `859f388422e25aacaaa2fe8024ed631496fc24a1be237a88d58732439ab2ed19` |
| `ATBD_Col3_10m_Caatinga_v1.pdf` | <https://brasil.mapbiomas.org/wp-content/uploads/sites/4/2026/05/ATBD_Col3_10m_Caatinga_v1.pdf> | 3,364,548 | `21f960d54b75303a33fcf74d59a91b9575959e6421e3e1b101b4523efa1472b4` |
| `Legenda-Colecao-10-Legend-Code.pdf` | <https://brasil.mapbiomas.org/wp-content/uploads/sites/4/2025/08/Legenda-Colecao-10-Legend-Code.pdf> | 84,039 | `77fb06ebeb938a5155af86227ad13709e10d65312222ff36c8ba1cf4cbc1eb44` |
| `brazil_coverage_2024.tif` | <https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/collection_10/lulc/coverage/brazil_coverage_2024.tif> | 802,022,037 | `1be96442929c98cdbe0126d5c83d65a8142b61642ec14fb0ad1dfdfa3bf68d6c` |
| `brazil_lulc_10m_2024.tif` | <https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/lulc_10m/collection_3/brazil_lulc_10m_2024.tif> | 6,766,932,375 | `2ba20d400976020b4e7472a37de04fe1755c6f23631008b39da388001a034f59` |

### 3.2 Dataset identity and raster headers

**MapBiomas Collection 10 direct GeoTIFF, 30 m**

- Product: annual land-cover/use series for Brazil, 1985–2024; the 2024 band
  is the acquired classification.
- Byte-level version evidence: the exact origin path is `collection_10`; the
  remote ETag is `dc8434523522eac0c69be51d9473efeb`, equal to the local MD5,
  and the object was last modified on 2025-08-13. These bytes therefore predate
  the February 2026 Collection 10.1 release and must not be labelled 10.1.
- Sensor/resolution: Landsat, nominal 30 m.
- The separate future Collection 10.1 source is the official GEE asset
  `projects/mapbiomas-public/assets/brazil/lulc/collection10_1/mapbiomas_brazil_collection10_1_coverage_v1`.
  Package 2A.6 must export and checksum its `classification_2024` band before
  any Collection 10.1 runtime use.
- Local raster header: one `uint8` band, `154470 × 146483`, EPSG:4326,
  pixel size `0.0002694945852358564` degrees, bounds
  `[-74.02099974839176, -34.04066954489674, -32.39217116700902, 5.435705784207225]`,
  LZW-compressed/tiled with 256-pixel blocks.
- Header NoData is unset. Under the delegated conservative version-1 decision,
  class `0` is treated as unknown/NoData and excluded from valid land-cover
  denominators unless fixture-backed official legend evidence proves a
  different interpretation. It is never classified as natural or anthropic
  merely because the header NoData field is unset.

**MapBiomas 10 m Collection 3 (beta), Caatinga method**

- Product: annual 10 m land-cover/use maps for Brazil, 2017–2024, with
  22 classes; the 2024 integration is the acquired classification.
- Version evidence: Caatinga Collection 3.0, ATBD Version 1, April 2026.
- Sensor/resolution/method: Sentinel-2, nominal 10 m; Gradient Tree Boosting is
  used for the Caatinga classification.
- Official GEE asset:
  `projects/mapbiomas-public/assets/brazil/lulc_10m/collection3/mapbiomas_10m_collection3_integration_v1`.
- Local raster header: one `uint8` band, `464738 × 476391`, EPSG:4326,
  pixel size `0.00008983152841195215` degrees, bounds
  `[-74.72150600694815, -35.187638499660544, -32.97338115583433, 7.607293152037755]`,
  NoData `0`, LZW-compressed/tiled with 512-pixel blocks.

Official identity pages reviewed on 2026-07-24:

- Collection 10.1 release:
  <https://brasil.mapbiomas.org/en/2026/02/09/mapbiomas-publica-colecao-10-1-de-mapas-anuais-de-cobertura-e-uso-da-terra-no-brasil/>
- 10 m Collection 3 method:
  <https://brasil.mapbiomas.org/mapbiomas-cobertura-10m/>
- Collection/GEE asset index:
  <https://brasil.mapbiomas.org/colecoes-mapbiomas/>

### 3.3 License and required attribution

MapBiomas states that its data are public, open, and free under CC-BY, subject
to source attribution:
<https://brasil.mapbiomas.org/termos-de-uso/>.

The release manifest and every public UI/download that uses these sources must
carry, at minimum:

- 30 m direct download: `Projeto MapBiomas – Coleção 10 da série anual de Mapas de Cobertura e Uso
  da Terra do Brasil, acessado em 2026-07-23 através do link:
  https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/collection_10/lulc/coverage/brazil_coverage_2024.tif`
- 10 m: `Projeto MapBiomas – Coleção 3 (beta) de Mapas Anuais de Cobertura e Uso da
  Terra do Brasil com 10 metros de resolução espacial, acessado em 2026-07-23
  através do link:
  https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/lulc_10m/collection_3/brazil_lulc_10m_2024.tif`

The Collection 10.1 attribution must be generated only after the separate GEE
export exists and must name Collection 10.1, its exact asset/export identity,
and its actual access/export date. These strings identify acquired files;
scientific outputs must additionally cite the corresponding ATBD/method and
keep the class legend version.

### 3.4 Required Phase 2 crop transform

The accepted transform is not the legacy territory crop:

1. Verify the national source checksum before reading.
2. Select the 2024 classification band represented by the acquired single-band
   file.
3. Window/crop to `araripe-implementation-rectangle-v1`; categorical data may use
   nearest-neighbour resampling only.
4. Preserve the source grid where practical. If alignment/reprojection is
   required, record source/destination transforms, CRS, resolution, resampling,
   and the exact software version.
5. Preserve/declare NoData explicitly. Treat class `0` as NoData for the 10 m
   source and as unknown/NoData for the direct Collection 10 source. Apply the
   same conservative project treatment to the future Collection 10.1 export
   unless its checksum-bound export metadata supplies stronger evidence.
6. Write a tiled, compressed local crop; compute its SHA-256, pixel dimensions,
   class histogram, bounds, CRS, transform, and NoData.
7. Register the crop in a release manifest before any consumer can select it.
8. Keep both national inputs immutable and outside Git/R2 publication.

The crop produced from the direct 30 m file during Package 2A.5 is retained as
immutable audit evidence only. It is not an authorized Collection 10.1 runtime
crop. The superseding decision is recorded in
`docs/decisions/PHASE_2A_SCIENTIFIC_DECISIONS_2026-08-11.md`.

The current `mapbiomas10m_crop.py` defaults to the presentation rectangle,
an older Collection 2 filename/year, and outdated legend labels. It is not an
accepted implementation of this transform without Phase 2 changes and tests.

## 4. Site rainfall sources

### 4.1 GPM IMERG Daily Late Run

| Field | Registered value |
| --- | --- |
| Product short name / version | `GPM_3IMERGDL`, version `07` |
| Official landing page | <https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGDL_07/summary> |
| DOI | `10.5067/GPM/IMERGDL/DAY/07` |
| Nominal grid | 0.1 degree |
| Access | NASA Earthdata / GES DISC |
| Acquisition rectangle | `[-41.15, -8.10, -38.70, -6.73]` |

Weekly transform in `site/scripts/fetch_gpm.py`:

1. Search the seven daily granules ending three days before execution by
   default.
2. Require seven granules unless `--allow-partial` is explicitly supplied.
3. Read `Grid/precipitation`; when units describe a rate in mm/hour, multiply
   by 24 to obtain mm/day.
4. Sum the daily arrays, orient north-up, assign EPSG:4326, crop to the
   acquisition rectangle, and write a weekly GeoTIFF.
5. `prepare_territorio.py` crops again to the presentation rectangle and
   converts value bands into a PNG/JSON display.

The code still labels the first write as requiring scientific validation.
Publication must record granule IDs, units actually observed, completeness,
conversion applied, min/max/mean checks, and a checksum. A partial week must
never be presented as complete.

### 4.2 GPM IMERG Monthly Final Run

| Field | Registered value |
| --- | --- |
| Product short name / version | `GPM_3IMERGM`, version `07` |
| Official landing page | <https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGM_07/summary> |
| DOI | `10.5067/GPM/IMERG/3B-MONTH/07` |
| Nominal grid | 0.1 degree |
| Record requested by code | From 2000-06-01 |

`fetch_gpm_historico.py` calculates a spatial mean within the acquisition
rectangle and converts an mm/hour monthly mean rate to mm/month using the number
of days. It derives monthly/annual series, climatology, and a linear trend from
complete Final years. For the current year it fills completed months from
Daily Late granules.

Two Phase 1 blockers are recorded:

- the site currently cites DOI `10.5067/GPM/IMERG/3B-HH/07`, which identifies a
  half-hourly product, not either product used by these scripts;
- the shared `_area_mean_mm` function multiplies any rate by the number of days
  in the month even when called once per Daily Late granule, then sums those
  results. The unit conversion for current-year Late aggregation requires a
  fixture-backed scientific review before further publication.

NASA access/usage terms and the exact citation returned with each Earthdata
product must be pinned in the release metadata before raw data redistribution.
The site publishes derived values and must name NASA GPM IMERG, the exact short
name/version, DOI, date range, completeness, and transform version.

## 5. Existing presentation/reference sources

These layers are not substitutes for the operational monitoring inputs above.

| Layer | Current source/evidence | Current attribution state | Required action |
| --- | --- | --- | --- |
| Legacy territory MapBiomas | `observatorio_atual/MapBiomas/MapBiomas_LULC_YYYY_Araripe.tif`, 2010–2024, described in code as EPSG:4326 and approximately 300 m | Output says “Coleção 10 (Souza et al., 2020)”; exact upstream URLs, acquisition dates, source checksums, aggregation method, and license chain are absent | Freeze as legacy until lineage is recovered; do not relabel it as either newly acquired 2024 national raster |
| APA source shapefile | `observatorio_atual/.../APA_chapada_araripe.{shp,shx,dbf,prj}` | Local component hashes exist; official publisher, edition, download URL/date, and terms are unresolved | Recover authoritative source/edition and produce a deterministic package checksum |
| FLONA source shapefile | `observatorio_atual/.../FLONA_araripe_apodi.{shp,shx,dbf,prj}` | Same gap as APA | Recover authoritative source/edition and terms |
| Backend AOI GeoPackages | `data/aoi/APA_chapada_araripe.gpkg` and `FLONA_araripe.gpkg` | File hashes registered below; conversion lineage is incomplete | Record source package and deterministic conversion |
| Public AOI GeoJSON | `site/public/data/aoi/apa.geojson`, `flona.geojson` | File hashes registered below; public files do not embed complete provenance | Generate them from the registered authoritative source and release manifest |
| Terrain | Terrarium tiles at `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`, default z11 | Code labels these “NASA SRTM/NASADEM via Terrain Tiles”; per-source mosaic attribution is not preserved | Use the Terrain Tiles attribution chain and record tile IDs/access date; review source-specific notices |
| Basemaps | Esri World Imagery; CARTO light using OSM; OpenStreetMap standard tiles | Leaflet displays `Esri, Maxar, Earthstar Geographics`, `OpenStreetMap & CARTO`, and `OpenStreetMap contributors` | Retain visible attribution and review provider tile-use terms |
| Geosite coordinates | `site/public/data/educacao/geossitios.geojson` says Secult-CE Cultural Map and OpenStreetMap, checked July 2026 | Exact feature URLs/record IDs and individual verification evidence are not registered | Pin source records or mark coordinates as editorial |

Useful public terms:

- Terrain Tiles registry and citation guidance:
  <https://registry.opendata.aws/terrain-tiles/>
- Terrain Tiles detailed attribution chain:
  <https://github.com/tilezen/joerd/blob/master/docs/attribution.md>
- OpenStreetMap ODbL and attribution requirements:
  <https://www.openstreetmap.org/copyright>

### 5.1 Local boundary fingerprints

These hashes identify current files; they do not establish authority or
license.

| File | SHA-256 |
| --- | --- |
| `data/aoi/FLONA_araripe.gpkg` | `c7abc3b97b0067a25b1d63161217c3f36e65941556ababa8f991fd2e0aa37dca` |
| `data/aoi/chapada_araripe.geojson` | `3fee6d8ad07ebaf6653bcd5dc66ed94cd416dd7e5b9bc0c9162b46d29c9b1167` |
| `data/aoi/chapada_araripe.gpkg` | `19f930c8861b11cd308aa8daa6878bb8e48eabe5e2fd7d60cdd4244f9f5b3f48` |
| `site/public/data/aoi/apa.geojson` | `c394cdc5c116cd4c8a1b4a54a01860cd1579cbe75df5802f5d20ac9e891dd253` |
| `site/public/data/aoi/flona.geojson` | `07b01fde483f0c98b51f23d33c7af0ddfc2cb02aedea4243d2efc2545355b8a3` |

The source shapefile component hashes are:

- APA: SHP `67fe3847bb089bf2144932310020a86ff2809438060315ff36fb99315f8cecc7`,
  SHX `d91711635856942051ae0f2796da70d205adb959a7ee0216ba23696b0efdb73c`,
  DBF `03c9c9a6177024ad67fd204139049668fe61ba61f6156c0314a203c5107b3c8e`,
  PRJ `6fd133464c46e57ff29739eb14ea39e83d72ab233ccba0ded03e050c9ccdace9`.
- FLONA: SHP `b99f4ed512e0385678896030a0ca54634de48f1a2ad9cffee8a4518682f5a29d`,
  SHX `3d12b317c26dcf72aa116f644e915866e832aca453b3870048ea0f01cdb2de2f`,
  DBF `dc85f3397e9cd3ebadddf19690cb0bfaa99cfc5e68853dfc9973ad472f29b139`,
  PRJ `6fd133464c46e57ff29739eb14ea39e83d72ab233ccba0ded03e050c9ccdace9`.

## 6. Attribution and release rules

1. A release may reference only source versions present in its immutable
   manifest; UI labels must be derived from that manifest rather than copied
   into unrelated JavaScript or JSON.
2. Every source record must carry provider, dataset/product ID, semantic
   version or edition, official URL, access time, time coverage, CRS,
   resolution, NoData semantics, license/terms URL, required citation, and
   upstream identifier/checksum where available.
3. Every derived record must carry the source record IDs, exact extent ID,
   transform name/version, parameters, software/runtime versions, output
   checksum, and QA status.
4. Unknown provenance or unknown license is a publication blocker for raw
   redistribution, not a field to silently omit.
5. Generated project code and prose may use the repository's own license, but
   that license does not replace upstream data terms. A derived visualization
   must preserve every required upstream attribution.
6. MapBiomas crops are context/stratification layers; they do not become raw
   spectral detections and must not silently filter valid observations.
7. All freshness claims must distinguish acquisition time, observation time,
   processing time, release time, and client fetch time.

## 7. Assigned open provenance gates

The project owner (`@santibravocmcc`) is the accountable Phase 1 owner for
commissioning and recording resolution of the gates below. This assignment
does not substitute the qualified scientific or source-specific review
required by a later gate:

- authoritative APA/FLONA publisher, edition, URL, acquisition date, and terms;
- full lineage of the legacy `observatorio_atual` MapBiomas rasters;
- CHIRPS license/citation pin and CHIRPS 3 cutover plan;
- GPM Daily Late unit fixtures and current-year aggregation correction;
- exact Earth Engine scene/asset lineage in the processing ledger;
- Terrain Tiles source-specific attribution for the requested tile set;
- correction of outdated Collection 2/Collection 10 labels and the wrong GPM
  DOI in generated site artifacts;
- fixture-backed verification of both MapBiomas class-0/NoData interpretations
  and independent review of the wider-extent crop QA.

The conservative version-1 rule treats 10 m class `0` as NoData and 30 m class
`0` as unknown/NoData; neither can remove a raw observation. The register can
therefore close Phase 1 as an evidence-backed design with assigned follow-up,
but it is not a claim that existing public artifacts already have complete
provenance or that the later scientific gates have passed.

---

## Addition dated 2026-10-04 — re-read against the green system and the public site

The register above was written for the 2026-07-24 system and was not
re-read against the green system until now. Nothing above is rewritten; this
section records what the code, the providers' pages, and the public site say
on 2026-10-04. Full audit, with every file:line, in
`docs/implementation/PHASE_6T_2026-10-04.md`. Site corrections in
`observatorio-site#38`.

Evidence base: backend `origin/main` and site `origin/main` read with
`git show`; provider pages fetched on 2026-10-04.

### A1. What the green system actually consumes

| Source | Where the green runtime takes it | Differs from the register? |
| --- | --- | --- |
| Sentinel-2 L2A, `COPERNICUS/S2_SR_HARMONIZED` | `scripts/replay_2026.py` `_base_collection`, run by `v2_green_deposit_lane.yml` | No (§2.1). Scene IDs are now recorded per acquisition (`AcquisitionV3.scene_ids`, `src/detection/identity_v3.py`, written to the v3 ledger). |
| MapBiomas 10 m context | `config/settings.py` `LANDCOVER_RASTERS["mapbiomas10m"]` = `data/landcover/mapbiomas10m_araripe_2023.tif`, applied by `annotate_alerts_all_collections` in `replay_2026.py` | **Yes.** It is **Collection 2 (beta), year 2023**, cropped from `mapbiomas_10m_collection2_integration_v1-classification_2023.tif` (its `.report.json`). §3 registers Collection 3 (beta) **2024**, and ROADMAP topic 27 says Collection 3 beta 10 m is the primary context. The frozen replay (`config/phase3_replay_freeze_v1.json`, group `mapbiomas`) photographs the 2023 file, so the release is consistent with its freeze — but not with topic 27. Access date and source checksum of the national 2023 file are **not recorded**. |
| MapBiomas "30 m" context | `LANDCOVER_RASTERS["mapbiomas30m"]` = `data/landcover/mapbiomas30m_araripe_2023.tif` | **Yes.** Header measured: 816 × 445 px at 0.0026949° (≈ 300 m), EPSG:4326, NoData 0; SHA-256 `a080e65ed8cacc39bb6d14d44907faa4d2d0b5ddbcbaf02a123298cfa4a10222`. It is not 30 m and is neither file in §3; `config/settings.py` calls it the territory crop "~300 m aggregated", which places it in the §5 legacy row whose lineage is unrecovered. |
| CHIRPS | not consumed: `drought.operationally_applied` is `false` in the freeze | Register §2.2 obligations are dormant, not met. |
| Monitoring extent | `araripe-implementation-rectangle-v1` (freeze) | No. |

### A2. Licences re-read at the source on 2026-10-04

- **MapBiomas.** The terms URL in §3.3 (`/termos-de-uso/`) now answers
  **404**. The current page is <https://brasil.mapbiomas.org/uso-de-dados/>:
  public, open, free use "mediante referência", **CC BY 4.0**. The reference
  format is in the FAQ (question 18): "Projeto MapBiomas – Coleção [versão]
  da Série Anual de Mapas de Cobertura e Uso da Terra do Brasil, acessado em
  [data] através do link: [LINK]". CC BY 4.0 §3(a)(1) also requires the
  licence link and an indication of modification; the site regroups classes.
- **Copernicus Sentinel.** The Sentinel Data Legal Notice requires
  "Contains modified Copernicus Sentinel data [Year]" when the data are
  adapted. The alerts are; the public site carried the notice **nowhere**
  before `observatorio-site#38`.
- **OpenStreetMap / CARTO.** OSMF attribution guidelines: "OpenStreetMap"
  linked to `/copyright`, in a map corner. carto.com/attributions:
  "© OpenStreetMap contributors, © CARTO", both linked. **CARTO basemaps now
  require an API key** (carto.com/basemaps/apikey); every tile request
  without one returns an "API KEY REQUIRED" image, so the light basemap on the
  public site is broken today. Not caused by, and not fixed by, this addition.
- **Esri World Imagery.** The service's own `copyrightText` is now
  "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community".
- **Terrain Tiles.** tilezen/joerd `docs/attribution.md` requires "SRTM
  terrain data courtesy of the U.S. Geological Survey" (and GMTED2010).
- **GPM IMERG.** DataCite confirms `10.5067/GPM/IMERGDL/DAY/07` (Late, 1 day,
  V07) and `10.5067/GPM/IMERG/3B-MONTH/07` (Final, 1 month, V07), both 2023,
  Huffman, Stocker, Bolvin, Nelkin, Tan. NASA's data-use terms were **not**
  re-read in this pass.

### A3. Status of the §7 gates on 2026-10-04

| §7 gate | Status |
| --- | --- |
| APA/FLONA publisher, edition, URL, terms | **open.** `educacao.html` credits "ICMBio" for the limits; no evidence in either repository supports that attribution. |
| Legacy `observatorio_atual` MapBiomas lineage | **open, and now wider**: the green "30 m" context crop is that lineage (A1). |
| CHIRPS licence/citation and CHIRPS 3 plan | open; dormant while drought stays disabled. CHIRPS 2.0 production ends after December 2026 per its README (§2.2). |
| GPM Daily Late unit fixtures | not re-examined here. |
| Exact Earth Engine scene lineage in the ledger | **scene IDs recorded** per acquisition in the v3 ledger (`AcquisitionV3.scene_ids`); whether processing baselines and source ETags/checksums are also recorded was **not** checked here. |
| Terrain Tiles source-specific attribution | **text corrected** on the site; tile-set source list still not recorded. |
| Wrong GPM DOI / Collection labels in site artifacts | **DOI corrected** in `observatorio-site#38`; Collection labels now match the files actually drawn (A1). |
| MapBiomas class-0 interpretation | not re-examined here. |

### A4. Gaps that are decisions, not text

1. The green release (`release.json`, alert GeoJSON) carries **no source or
   attribution record**, though §3.3 and §6.1 require the manifest to carry
   it. Adding it is a release-contract change.
2. Which MapBiomas files the green context should use (A1) is a scientific
   decision under topic 27, with consequences for the strong subset, which
   filters on `lc_natural_frac_10m >= 0.5`.
3. The licence of the project's own data products: the site says
   CC-BY-SA 4.0. CC BY 4.0 inputs may be adapted under BY-SA; the Copernicus
   terms impose only the notice. No incompatibility was found, but the choice
   is the owner's.

---

## Addition dated 2026-10-06 — MapBiomas 2025 (10 m Collection 4, Collection 11)

The owner downloaded both national 2025 coverage files on 2026-10-06 from the
official bucket. They were cropped on the same day by
`scripts/crop_mapbiomas_national.py` to the display window
`(-41.0, -8.0, -38.8, -6.8)` — a window read on the native grid, no
resampling — and the national files were then moved to the system Trash, not
kept. Each crop's `.report.json` is the binding to the national bytes.

| | 10 m Collection 4 | Collection 11 (30 m) |
| --- | --- | --- |
| Origin URL | `https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/lulc_10m/collection4/coverage/brazil_coverage/brazil_coverage-col4_10m_2025.tif` | `https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/collection11/lulc/coverage/brazil_coverage/brazil_coverage-col11_2025.tif` |
| National bytes | 4,707,906,958 | 763,286,575 |
| National MD5 = bucket ETag | `17dbc582322190b9f8e7a40c16348006` | `1c8ee63d2752b08463d703b6ae585101` |
| National SHA-256 | `58a2debdcd37ae2d4d66100272e52214fba4dbcd6da5958a766653c528d73040` | `0035bf482e8e6fab6c623275485d2891ed19713b5f258d194a7bb0764d8392db` |
| Bucket `last-modified` | 2026-08-20 00:11:03 GMT | 2026-08-18 21:38:54 GMT |
| National header | 487854 × 467490, uint8, EPSG:4326, 0.0000898°, NoData unset | 154470 × 146501, uint8, EPSG:4326, 0.0002695°, NoData unset |
| Crop | `data/landcover/mapbiomas_col4_10m_2025_araripe.tif`, 24490 × 13358, SHA-256 `d8ba1b38104fc9a441b8a58f75bd0814b8bdb49f384038d0c75ba5aba7715fc8` | `data/landcover/mapbiomas_col11_30m_2025_araripe.tif`, 8163 × 4453, SHA-256 `f3d8db14951ee383e4d805e5c4a3f7918c2db0d0d785383df6e4a74c6c1c2179` |
| Class 0 in crop | none (full coverage) | none |
| Legend | "Códigos das classes da legenda", 10 m Collection 4, published 2026-08-21, levels 1–3 | Collection 11, published 2026-08-13, levels 1–4 |

Both legends were read from `brasil.mapbiomas.org/codigos-de-legenda/`.
Required reference, MapBiomas FAQ format: "Projeto MapBiomas – Coleção 4 de
Mapas Anuais de Cobertura e Uso da Terra do Brasil com 10 metros de resolução
espacial, acessado em 06/10/2026 através do link: [URL above]" and
"Projeto MapBiomas – Coleção 11 da Série Anual de Mapas de Cobertura e Uso da
Terra do Brasil, acessado em 06/10/2026 através do link: [URL above]". Licence
CC BY 4.0 (A2).

**Measured against the crops in use, inside the monitoring extent:** the 10 m
crops share the grid exactly; 84.01% of pixels keep their project group;
natural goes 63.55% → 69.65% (10.28% farming→natural, 3.97% natural→farming).
The legacy "30 m" (≈ 300 m) crop has natural 68.36%, Collection 11 65.41%.

**What uses them on 2026-10-06:** the public map overlay only
(`observatorio-site#40`). The detector's annotation — and therefore
`lc_natural_frac_10m` and the strong subset — still reads the 2023 crops
(`config/settings.py` `LANDCOVER_RASTERS`, unchanged). Switching it is open:
releases already published were annotated with the 2023 crops, so a switch
without re-annotating them would make one release carry two land-cover
versions. The class tables in `src/detection/landcover.py` gained the codes
the 2026 legends add (7, 77, 84 natural; 75 and 91 infrastructure); none of
them occurs in the 2023 crops, so today's annotation is unchanged
(`tests/test_mapbiomas_2025_crops.py`).

**The project's five groups are not MapBiomas level 1.** Level 1 is Forest /
Herbaceous and shrub vegetation / Farming / Non-vegetated / Water; the project
joins forest and natural herbaceous vegetation as "natural", and keeps rocky
outcrop (29) and hypersaline tidal flat (32), which MapBiomas files under
herbaceous vegetation, in "other". The site now offers both.

---

## Addition dated 2026-10-07 — the publication carries its sources (A4.1)

Nothing above is rewritten. Gap A4.1 (the release carries no source or
attribution record) has a design and an implementation on a branch, **not yet
published**: `docs/contracts/phase2b/GREEN_SOURCES_CONTRACT_V1.md`, decision
record `docs/implementation/PHASE_6V_2026-10-07.md`.

- **Where.** Not inside `release.json`: a release's id does not read its
  manifest, every release schema is closed, and attribution changes (§A2).
  A document beside the release, `sources/<sources-id>/sources.json`, whose id
  is a function of the release, the land-cover context it covers, and the
  reviewed records in `config/green_sources_v1.json`.
- **§6.1 read as it can be met.** "A release may reference only source
  versions present in its immutable manifest" holds for Sentinel-2 — the
  ledgers seal `collection_id` per acquisition, and the document is refused
  unless the ledgers read exactly the declared collection — and for the 2025
  context, whose recipe seals each crop. It cannot hold for the 2023 crops:
  nothing a release seals names them. Their records are **asserted**, checked
  against the replay freeze (path and bytes) and the tracked files (sha256).
  The freeze photographs the 2023 crops by path and bytes, **not** by sha256.
- **§6.4 enforced.** A record may leave a required field empty only by naming
  it in `open_gaps`. Seven gaps, all on the two 2023 crops (origin URL, access
  date and national checksum of both; the collection of the ≈300 m one).
- **Copernicus terms URL**, read on 2026-10-07 from the Earth Engine catalog
  page of `COPERNICUS/S2_SR_HARMONIZED`:
  <https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice>.
  The notice years are the baseline's source years (2017, 2019, 2021, 2022,
  2025, from the freeze) together with the years of the release's dates that
  had a usable acquisition, written `first–last`, as the site already does.
