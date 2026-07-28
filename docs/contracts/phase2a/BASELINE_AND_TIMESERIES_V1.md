# Phase 2A baseline and time-series contract, version 1

**Accepted:** 2026-07-28

**Package:** Phase 2A.2 — baseline and time-series audit

**Production mutation:** none

## 1. Authoritative baseline generation

`config/baseline_manifest_v1.json` is the authoritative identity and audit
record for baseline version `1.0.0`. `config/settings.py` and the detection
identity contract use that exact version. A file under `data/baselines/` is not
part of version 1 merely because its filename matches: its byte size and
SHA-256 must match the manifest.

The accepted inventory is:

- 72 single-band rasters: three indices × twelve months × two statistics;
- R2 keys `baselines/<index>_month<NN>_{mean,std}.tif`;
- aggregate bytes `13,408,183,319`;
- aggregate inventory SHA-256
  `c0ede11bb02cdcfbf67653dfee521f0e922955179c8da5b69c07ea5069cc1054`.

The `*_mean.tif` filename is retained for compatibility but stores the
multi-year monthly **median**. `*_std.tif` stores the multi-year monthly
standard deviation.

### 1.1 Source and transform

| Field | Accepted value |
| --- | --- |
| Collection | `COPERNICUS/S2_SR_HARMONIZED` |
| Years | `2017, 2019, 2021, 2022, 2025` |
| Year selection | Historical expert-reviewed set; partially reconstructed |
| Scene cloud filter | `CLOUDY_PIXEL_PERCENTAGE < 40` |
| Clear SCL classes | `2, 4, 5, 6, 7, 11` |
| Reflectance conversion | divide source bands by `10,000` |
| Indices | NDMI, NBR, EVI2 |
| Central statistic | monthly multi-year median |
| Dispersion statistic | monthly multi-year standard deviation |
| Generation rectangle | `[-40.90, -7.85, -38.95, -6.95]` |
| Generator/splitter | `scripts/build_baseline_gee.py`, `scripts/split_gee_baselines.py` |
| Historical generator commit | `fecbde3e87671c214b0efbcde14615b803c2e51f` |

`scripts/select_baseline_years.py` is a diagnostic ranking, not retroactive
proof that an algorithm selected the accepted year set. Its Python 3.11 syntax
failure was corrected in this package, its AOI now names the approved
monitoring extent, and its output explicitly declares itself non-authoritative.

### 1.2 Grid, coverage, and range evidence

All 72 objects passed the following complete read:

| Check | Result |
| --- | --- |
| CRS | all `EPSG:32724` |
| Shape | all `10,773 × 4,999` |
| Pixel size | all `20 × 20 m` |
| Transform | all `[20, 0, 290080, 0, -20, 9231780]` |
| Raster bounds | all `[290080, 9131800, 505540, 9231780]` |
| Type / bands / NoData | all float32 / one band / NaN |
| Layout | all tiled, DEFLATE, `256 × 256` blocks |
| Internal overviews | none |
| Approved-extent valid coverage | `99.700183%` minimum; `100%` maximum |
| Range violations | zero pixels |

Observed global ranges across the twelve objects in each family:

| Index | Median-file range | Standard-deviation-file range |
| --- | ---: | ---: |
| EVI2 | `[-0.263937, 0.966073]` | `[0, 0.470155]` |
| NBR | `[-1, 1]` | `[0, 0.822592]` |
| NDMI | `[-1, 0.838926]` | `[0, 0.715444]` |

Per-object byte size, R2 metadata, SHA-256, grid, coverage, finite-pixel count,
minimum, maximum, accepted range, and range-violation count are retained in the
manifest. R2 ETags are recorded as transport metadata; SHA-256 is the
authoritative content checksum.

### 1.3 Provenance disposition and rebuild decision

The provenance record is explicitly partial. It retains the collection, years,
transform configuration, generator commit, R2 metadata, and final 72 object
checksums. The original provider-native scene list per month, source processing
baseline per scene, GEE task IDs/query fingerprint, and checksums for the
twelve original multi-band exports were not retained and cannot be
reconstructed from the split objects.

These gaps are not repaired by regenerating different rasters now. Because the
existing objects pass the scientific scale, range, grid, checksum, and wider-
extent coverage gates, **a rebuild is not required for the Phase 2A method-
selection pilot**. A future build creates a new baseline version and must
capture complete provider-native provenance at execution time.

Version 1 is invalidated and processing fails closed if any object is missing,
has a different name/size/SHA-256, drifts from the reference grid, falls below
the manifest coverage gate, or contains values outside the accepted ranges.
The fetcher checks the exact remote inventory, size, ETag, and downloaded
SHA-256. The production loader also binds each default-path raster to its
manifest checksum once per process.

## 2. Legacy 2026 time-series disposition

The tracked `data/timeseries/timeseries.db` is preserved unchanged. Its
read-only audit is
`docs/implementation/PHASE_2A2_TIMESERIES_AUDIT_2026-07-28.json`.

| Fact | Audited value |
| --- | ---: |
| Database SHA-256 | `2768755da91442a34419974dbce2def34f7c0dc104b5c4684ec74d9e8b56b946` |
| Regional rows / dates | `126 / 42` |
| Regional date range | `2026-01-02` through `2026-07-15` |
| Alert rows | `32` |
| Distinct regional write-day groups | `10` |
| Rows/dates below 10% coverage | `19 / 9` |
| Dates with cross-index coverage disagreement | `11` |
| EVI2 rows outside the accepted splitter range | `3` |

The legacy rows do not store generation ID, acquisition ID, source collection,
scene IDs, baseline version, algorithm version, monitoring-extent version, or
an explicit per-date QA result. Dates written before and after the reflectance
baseline activation coexist. Those missing identities make row-level
generation assignment unverifiable.

The entire database is therefore classified
`quarantined_mixed_generation_audit`: it is preserved for audit, is not
publishable as the corrected series, and individual rows cannot be copied into
a clean generation merely because their values appear plausible.

## 3. Clean time-series schema

`src/timeseries/schema.py` defines schema version `1.0.0` for a future empty-
chronology rebuild. This package creates no candidate database and replays no
date.

The schema separates:

- `processing_generations`: schema, algorithm, baseline, exact monitoring
  extent checksum, source collection, composition method, reflectance scale,
  and candidate/accepted/quarantined state;
- `acquisitions`: exactly one canonical acquisition per generation/date,
  provider scene-list JSON, source-metadata checksum, valid/total pixels,
  coverage fraction, and accepted/rejected QA;
- `regional_stats_v1`: generation/acquisition/date/index/region statistics
  carrying source, scene, baseline, algorithm, extent, coverage, and QA fields;
- `alert_stats_v1`: generation/acquisition/date counts and area with arithmetic
  reconciliation.

Foreign keys and checks enforce one generation and acquisition identity,
coverage arithmetic, rejection reasons, confidence-count reconciliation, and
generation isolation. Missing/download/processing failures remain authoritative
processing-ledger statuses rather than invented statistical rows.

Only a new chronological generation built from empty state may populate the
clean schema. Promotion requires an accepted generation, complete processing
ledger reconciliation, and immutable release checksums in later phases.

## 4. Local gates

```bash
python scripts/audit_baselines.py --baseline-dir <downloaded-baselines>
python scripts/audit_timeseries.py
python scripts/select_baseline_years.py --min-year 2025 --max-year 2025 --n 1
python -m pytest -q
```

Regenerating the manifest uses `--write-manifest --r2-read` only during an
authorized read-only audit of the same immutable generation. A content change
requires a new version; it must not overwrite version 1.
