# Phase 2A.4 drought, cloud-mask, and daily-composition comparison contract v1

Status: fixed candidate contract; no scientific method has been selected.

This contract governs Package 2A.4 only. It defines reproducible candidate
alternatives and the local, blinded comparison evidence that may later be
reviewed by qualified reviewers. It does not authorize a baseline rebuild, a
2026 replay, a change to raw detections, a release, or a production method
change.

The Phase 2A.3 population, imagery, series, and blank review files remain
provisional audit inputs. They contain no qualified human labels. Their
technical validation establishes file and workflow integrity only; it is not
evidence of scientific accuracy. Legacy alert identifiers are not accepted
observation or event identities and must not be promoted or reconstructed for
this package.

## 1. Fixed bindings and scope

The machine-readable candidate registry is
`config/phase2a4_candidates_v1.json`, version `1.0.0`. Every derivative must
bind the registry bytes and SHA-256, not merely its version string.

The comparison is bound to:

- monitoring extent `araripe-implementation-rectangle-v1`, including geometry
  SHA-256 `b4986ef80d8a0d6e65bbb41b575dbd952c010415bf3aee93a88412b3b657e8c7`;
- accepted baseline manifest `1.0.0`, SHA-256
  `15a1ed3cea7c804d18d2c82c86a7b9a030687fedb01b315d543965b1f26f0a82`;
- frozen Phase 2A.3 package
  `p2a3-pilot-package-v1-050d2b944679385e1a3e3bf209fbe2f3a6a3892a4016ef2a24c1f96e281bf5c8`,
  manifest SHA-256
  `4b78167930fcb7a928b40d50ae1d54675e4cca47a10857bcbf28db803c18946b`;
  and
- its population snapshot
  `p2a3-population-v1-100c4e3e2f293235211d519392323c6ee0e6f2b88928d9fc8a74a71b52d80c6c`.

The accepted reference grid remains EPSG:32724, 20 m, 10,773 columns by
4,999 rows, with transform `[20, 0, 290080, 0, -20, 9231780]`. Package 2A.4
evaluates fixed per-case windows on that grid; it does not process or replace
the accepted full-grid baseline. Each sidecar records integer row and column
offsets, dimensions, transform, bounds, and a window-definition checksum. The
window is fixed before candidate evaluation and is identical for all eight
factorial cells for that case.

Coverage is measured over every pixel in the fixed case window. A valid pixel
has finite required reflectance after the candidate mask and composition and is
eligible for at least one configured index comparison with finite current
index, accepted baseline mean, and accepted baseline standard deviation. This
union rule is the accepted detector behavior; each index comparison still uses
only its own finite inputs and clamps standard deviation to the accepted `0.01`
floor. The recorded fraction is `valid_pixel_count / case_window_pixel_count`;
missing pixels are not zero and coverage below `0.20` is retained as
`rejected_low_coverage`.

## 2. Read-only input provenance

### 2.1 Sentinel-2

Candidate imagery comes from the public, read-only Element84 Earth Search STAC
endpoint `https://earth-search.aws.element84.com/v1`, collection
`sentinel-2-l2a`. A case query uses its target date, the fixed grid-aligned case
window, and `eo:cloud_cover < 60`; its canonical request payload and catalog
access time are retained. Pagination requests every page until exhaustion with
no item-count cap; a query failure remains a failed query, never a truncated or
substituted scene set. The retained page trace counts the nonempty page
collections yielded by the provenance-bound `pystac-client` runtime. Iterator
exhaustion may follow a final advertised `next` link when that client fetches
and suppresses an empty terminal FeatureCollection; every earlier yielded page
must advertise continuation. The ordered provider-native item IDs, under the
fixed collection binding, are identical for every factorial cell in the case.

The required STAC asset keys are `blue`, `red`, `nir`, `nir08`, `swir16`,
`swir22`, `scl`, and `cloud`. The `cloud` asset is the cloud-probability input
from the same STAC item; there is no second collection or scene join. For every
source scene, evidence records:

- the collection and STAC item ID, observation time, unsigned self link, and
  SHA-256 of the canonical STAC item JSON;
- each asset key, provider asset href, resolved unsigned HTTPS read URL,
  canonical STAC asset-metadata SHA-256, media type, and allowlisted HTTP
  metadata;
- a provider full-asset checksum when one is supplied, otherwise `null`; and
- the checksum, type, shape, and canonicalization of the decoded local
  grid-aligned context window used by the comparison, including the fixed
  auxiliary shadow halo.

Every reflectance asset uses the fixed normalization policy
`sentinel2-l2a-stac-scale-offset-zero-fill-nonnegative-v1`. Both `scale` and
`offset` must be explicit finite numeric values in `raster:bands[0]`, with a
positive scale; missing or invalid metadata makes that asset unavailable and
never defaults to `(1, 0)`. Raw DN zero is fill and is excluded before bilinear
resampling and scaling. The scale and offset are then applied in `float32`,
negative scaled reflectance is clipped to zero, and invalid outputs remain
`NaN`. This fixed normalization is shared by every candidate cell and is not a
method factor.

Asset URLs containing a query or fragment are forbidden in retained evidence.
Provider HTTPS hrefs are preserved. Earth Search's required cloud-probability
JP2 may instead use its public `s3://sentinel-s2-l2a/...` href; policy
`earth-search-provider-https-or-fixed-public-s3-bucket-to-https-v1` maps only
the allowlisted `sentinel-s2-l2a` and `sentinel-cogs` bucket/key forms to fixed
anonymous HTTPS read URLs. Both forms are retained, and the canonical STAC
asset metadata continues to bind the original provider href; this is a
transport mapping to the same object, not an alternate scene or input.
Remote rasters (COGs and the provider cloud-probability JP2) are read by byte
range. A local decoded-window checksum binds that window only and must never be
represented as verification of the complete remote asset. ETag and
Last-Modified values are transport
metadata, not substitutes for scientific content checksums. Missing assets or
failed reads make affected cells explicitly unavailable; they do not trigger a
different source, scene, or method.

The comparison window is fixed before any candidate is evaluated: project the
target geometry bounds to EPSG:32724, expand them by 500 m, round outward to
the accepted 20 m grid, and clip to that grid. Shadow construction reads a
fixed 1,060 m auxiliary halo around that comparison window (the 1,000 m search
plus 60 m dilation). The halo is not part of the coverage denominator, and the
STAC intersection query uses the comparison window without the halo.

### 2.2 CHIRPS rainfall

The drought candidate uses official CHIRPS 2.0 monthly COGs at
`https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/cogs/`, with
filename pattern `chirps-v2.0.YYYY.MM.cog`. The fixed reference is January 1981
through December 2025. Source URLs are public and unsigned. Each month retains
its access status, source URL, HTTP metadata, selected source-grid window,
local-window checksum, aggregation result, and any failure.

Rainfall is aggregated over the exact accepted EPSG:4326 monitoring rectangle,
not the imagery case window. Version `cell-center-cos-lat-v1` selects a CHIRPS
cell exactly when its center lies within the closed rectangle. Finite,
dataset-valid, non-negative precipitation is weighted by
`cos(latitude_cell_center_radians)`. The mean denominator is the valid-cell
weight sum. Rainfall coverage is the valid-cell weight sum divided by the
cosine-latitude weight sum for all selected cell centers. There is no
resampling.

CHIRPS is also read by remote COG ranges. The retained NumPy window checksum
does not cover the complete upstream COG. A missing or invalid target month
makes the candidate SPI unavailable. In the fixed reference, a three-month
window that depends on a missing or invalid month remains explicitly incomplete
and is excluded without substitution; the candidate is unavailable unless at
least 40 complete season-matched reference windows remain. No neighboring
month, climatology, zero, disabled candidate, or other fallback may be
substituted.

## 3. Fixed candidate alternatives

Exactly two versioned candidates exist in each family.

### 3.1 Drought adjustment

`drought-disabled-v1` uses no rainfall input and applies no threshold
adjustment.

`chirps-v2-spi3-season-matched-1981-2025-v1` computes an SPI-3 candidate whose
three-month accumulation ends in the complete calendar month immediately
before the acquisition month. Its comparison distribution contains only
complete three-month windows ending in the same calendar month in the fixed
1981–2025 reference. The exact target window is excluded from its fit. At least
40 complete reference windows and at least two positive windows are required.
The distribution is a mixed zero-probability plus gamma fit with gamma location
fixed at zero; the resulting normal probability is clipped to `[0.001, 0.999]`.

Candidate drought status is `drought` only when SPI-3 is strictly below `-1.0`.
Within derivative comparison evidence only, drought adds `0.5` to the magnitude
of each negative detection z threshold—for example, `-2.0` becomes `-2.5`.
This candidate calculation is not activation. Drought adjustment remains
disabled in production unless a later, qualified evidence decision explicitly
authorizes it.

### 3.2 Cloud and shadow mask

`scl-explicit-clear-shadow-v1` accepts only SCL classes `[2, 4, 5, 6, 7, 11]`
and masks SCL class `3` as shadow. SCL classes `[0, 1, 8, 9, 10]` are rejected.
It has no cloud-probability input and no dilation.

`scl-cloudprob-darkshadow-dilate-v1` accepts only SCL classes `[4, 5, 6, 7]`
and additionally requires the same-item `cloud` probability to be less than or
equal to `40` percent. It masks SCL class `3`, cloud classes `[8, 9, 10, 11]`,
and projected dark-shadow candidates where `nir <= 0.15` lies within 1,000 m of
cloud. The union of cloud and shadow masks is dilated by 60 m on the projected
20 m grid. Missing SCL, cloud probability, or NIR makes this candidate
unavailable; it never falls back to the SCL-only candidate.

### 3.3 Deterministic same-day composition

`coverage-ranked-first-valid-v1` orders scenes by integer valid-pixel count
descending and then STAC item ID in UTF-8 ascending order. Each output pixel is
taken from the first valid scene in that order.

`min-cloudprob-sclrank-sceneid-v1` selects each output pixel by minimum uint8
cloud probability, then fixed SCL rank `[2, 4, 5, 6, 7, 11]`, then STAC item ID
in UTF-8 ascending order. This SCL order is only a deterministic tie-break; it
is not a claim that the classes have that scientific quality order. Every
source scene must have the `cloud` asset or this candidate is unavailable.

Both candidates retain the ordered source-scene IDs, the scenes that contribute
at least one output pixel, selected-pixel counts by scene, the contributor map,
and valid coverage. Floating-point scene ranking is forbidden.

## 4. Factorial comparison

The registry enumerates the complete `2 × 2 × 2` design as eight cells. Every
frozen case is attempted in every cell with the same source-scene set, case
window, accepted baseline, and source query. A family comparison uses all four
paired strata formed by the other two factors; evidence may not present a
single convenient stratum as the family result.

Unavailable cells remain present with a reason. A case is never replaced,
silently omitted, or regenerated with a different query. Candidate constants,
filters, and thresholds may not be tuned against expected or desired detection
totals.

## 5. Blinded reviewer derivative

Phase 2A.4 creates a new derivative package; it never edits the frozen Phase
2A.3 package. Its reviewer records remain compatible with
`validation-review-v1.schema.json` and retain the Phase 2A.3 blind case IDs.
The 60 primary cases and the same 12 overlap cases are preserved.

Reviewers see opaque option IDs and labels `A` and `B`, never candidate IDs,
cell IDs, candidate filenames, or the true key. The coordinator mapping is a
checksummed, bijective artifact held outside both reviewer folders. Display
order is derived deterministically and recorded. Reviewer A and reviewer B
receive byte-identical method evidence for overlap cases but independently
derived case order; neither package contains the other reviewer's work.

Within the audited reviewer interface, the workflow enforces this order:

1. The reviewer completes change, temporal, and land-cover assessment using the
   original provisional audit evidence.
2. The tool saves and locks that primary assessment.
3. Only then does it reveal the blinded Package 2A.4 alternatives.
4. Method preference, confidence, and reason are recorded as evidence for a
   later decision and never activate or select a method.

This is a procedural, non-adversarial local review boundary: the checksummed
panel files necessarily exist inside the assigned offline directory and a
reviewer who bypasses the interface could inspect them directly. The protocol
therefore forbids source/file inspection before reveal. The exported Phase
2A.4 envelope binds the package, assignment, blank template, method-evidence
index, and review schema; it also carries an ordered reveal state with the
frozen primary snapshot so the lock survives an import on another machine.

Blank review records contain no reviewer identity, attestation, label,
preference, confidence, or reason. Missing comparisons are marked `partial` or
`unreviewable`; reviewers are not shown invented neutral panels. The Phase 2A.5
`mapbiomas` and `contextual_signature` comparison fields stay unchanged and are
not generated by this package.

## 6. Schemas and validation

The fixed schemas are:

- `phase2a4-candidate-registry-v1.schema.json` for the candidate registry;
- `phase2a4-candidate-evidence-manifest-v1.schema.json` and
  `phase2a4-candidate-evidence-case-v1.schema.json` for the provenance-bound
  local collector output;
- `phase2a4-method-evidence-v1.schema.json` for each blinded per-case sidecar;
- `phase2a4-derivative-manifest-v1.schema.json` for the derivative package; and
- `phase2a4-review-export-v1.schema.json` for package-bound reveal/lock state;
- the accepted `validation-review-v1.schema.json` for reviewer records.

JSON Schema validation is necessary but not sufficient. The local semantic
validator must also verify:

- the registry checksum and the exact two candidates in each family;
- that the eight cells are the Cartesian product exactly once for every case;
- that all 60 parent cases, including every missing case, are retained and the
  same 12 cases remain assigned for independent double review;
- the source query fingerprint, ordered unique STAC item IDs, canonical item
  JSON hashes, eight required assets per item, unsigned URLs, available source
  checksums, HTTP metadata, and explicit range-read limitations;
- the complete uncapped STAC request, frozen parent geometry, derived case and
  context windows, decoded source arrays, and every retained read failure;
- that case-window offsets and dimensions fit the accepted full grid, transform
  and bounds derive exactly from those integers, and the same window is used in
  all eight cells;
- coverage arithmetic, contributor membership, contributor pixel totals, and
  output/contributor checksums;
- offline replay of every candidate mask, deterministic composition,
  season-matched drought result, raw detection, and rendered panel byte stream;
- the rainfall artifact ID, manifest and plan checksums, fixed 1981–2025 month
  inventory, season match, minimum reference count, weighted aggregation, and
  retained month failures;
- a bijective candidate-to-option and cell-to-blind-cell mapping for each case,
  absence of the true mapping from reviewer folders, deterministic display
  order, and byte-identical overlap evidence;
- package-bound review imports, immutable method metadata, ordered reveal
  state, and byte-for-byte primary snapshots after reveal;
- every artifact byte count and SHA-256 against `CHECKSUMS.sha256`, with no
  unlisted or missing file; and
- null selected candidates, no drought activation, no cloud or composition
  lock, no raw-detection mutation, and no Package 2A.5 policy change.

Technical tests and these integrity checks demonstrate determinism and package
consistency. They do not demonstrate scientific accuracy or constitute the
qualified reviewer evidence needed to select a method.

## 7. Decision boundary and Package 2A.5 handoff

At Package 2A.4 completion, all selected-candidate fields remain `null`, all
activation and lock flags remain `false`, and no replay or release is
authorized. A later decision may be made only from completed, qualified,
independent review evidence under a separately recorded decision protocol.

Package 2A.5 receives the still-provisional Phase 2A.3 cases and Package 2A.4
method-evidence references, including missing/unreviewable status and immutable
source provenance. It must not infer labels or accepted identities from those
inputs. MapBiomas crop/version policy and contextual-signature semantics remain
entirely within Package 2A.5.
