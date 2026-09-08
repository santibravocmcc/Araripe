# Phase 2A candidate-generation policy decisions

**Accepted:** 2026-08-11

**Machine-readable record:** `config/phase2a_candidate_generation_decisions_v2.json`

**Status:** Policy closed; implementation 2A.6 and scientific validation remain open

## Outcome

The open Phase 2A.4/2A.5 questions are resolved far enough to implement a new
2026 candidate. This record does not invent qualified labels, a reviewer
usability result, or scientific accuracy. Those remain Phase 5 evidence before
canonical publication.

Packages 2B.0–2B.4 may proceed sequentially among themselves in isolated green
resources while 2A.6 proceeds in parallel. No blue/production mutation is
authorized. Phases 3 and 4 remain blocked until both the 2A.6 implementation
gate and the Phase 2B gate close.

The checksum-bound v1 registries and evidence packages are not edited. This v2
record supersedes their unresolved decision state for future implementation and
preserves them as audit evidence.

## Resolved questions

| Previously open question | Resolution | Consequence |
|---|---|---|
| Qualified primary labels, usability, accuracy | Not fabricated and not required for infrastructure or candidate-method implementation | Required in Phase 5 for accuracy claims and canonical promotion |
| Acquisition, observation, event identities | Implement one coherent v2 family for acquisition, observation, event, lineage, persistence, and ledger; preserve v1 concepts and artifacts only for audit | A v2 acquisition is never serialized into a v1 schema; legacy pilot IDs are never promoted |
| Same-day persistence | Retain every datatake as an independent observation, but create at most one persistence contribution per event per UTC date after all run-manifest acquisitions for that date are terminal | Two near-simultaneous satellite passes cannot make an event look persistent by themselves; a late same-day acquisition requires a new chronological candidate generation |
| Cloud mask | Implement candidate-only `scl-explicit-allowlist-v2`: accept SCL 4/5/6/7, reject 0/1/2/3/8/9/10/11, and measure SCL 7 separately | Both v1 masks are rejected; baseline must be rebuilt identically; SCL 7 and canonical suitability remain Phase 5 questions |
| Daily composition | Use coverage-ranked first-valid composition, explicitly scoped to one physical Sentinel-2 datatake | Different datatakes on one date cannot be merged into one acquisition |
| Drought adjustment | Keep `drought-disabled-v1`; make activation inaccessible in candidate entrypoints | CHIRPS v2 incomplete evidence stays audit-only; a future CHIRPS v3 contextual analysis cannot suppress raw detections |
| MapBiomas mapping | Freeze exact `mapbiomas-context-groups-v2` lists; class 33 is uncertain/mixed in both collections | Unknowns remain unmapped; mappings are context, not truth; false disagreement from two project meanings for water is avoided |
| 30 m Collection identity | Correct the direct-download file to Collection 10, not 10.1 | Existing mislabeled 10.1 crop is invalid for future candidate use; export true 10.1 band from the official GEE asset |
| NoData/classes 0 and 27 | Keep per-source semantics; export true 10.1 masked pixels as 255; exclude 0/27/255 from valid mapped denominators | Counts stay explicit and none may remove a raw detection |
| Natural-vegetation threshold | Select inclusive 50% majority using Collection 3 pixel centers and all valid mapped pixels | Public name becomes “majority natural-vegetation context subset”; empty denominator is not-assessed; 75% remains sensitivity-only |
| Spectral signature | Retain quantitative metrics and select the 60% dominant-share aggregator for internal candidate comparison only | No causal label or public display until Phase 5 qualified validation |
| Collection disagreement | Record agreement/disagreement/not-assessed as context only | It cannot break ties, change subset membership, or modify raw detections |
| Historical 31-object archive | Close as audit-only and superseded | Population-wide annotation uses only the new complete checksum-bound 2026 replay |

### Why the identity family changes major version

The v1 contracts require `acq-v1-*` references and exactly one canonical
acquisition per expected date. That cannot represent two legitimate datatakes
on one date without either losing an observation or double-counting persistence.
The v2 family therefore records each datatake independently, orders intraday
processing by UTC timestamp and acquisition ID, writes one terminal ledger row
per manifest-bound acquisition, and derives a reconciled daily summary.
Persistence remains date-based: all source observations are retained, but one
event receives at most one contribution for that UTC date.

## Phase 2A.4 reasoning

### Drought

The fixed CHIRPS v2 candidate is unavailable in all 60 pilot cases because the
retained acquisition produced only seven complete seasonal reference windows
per case and no complete target window. A `+0.5σ` detection adjustment has no
local validation and precipitation alone cannot establish that a spectral
change was caused by drought. The safe decision is therefore explicit disable,
not a neutral fallback.

A later CHIRPS v3 Final SPI-3 product may be evaluated as spatial context. It
must use a fixed reference, complete season-matched windows, no mixed v2/v3
inputs, and no effect on raw detection existence. Any effect on ranking or a
subset requires Phase 5 evidence.

### Cloud mask

The SCL-only v1 candidate incorrectly accepted classes 2 and 11 as clear. In
current Sentinel-2 L2A semantics these are cast/topographic shadow and snow/ice.
The more complex v1 candidate used an all-direction Euclidean dark-NIR
proximity rule and 60 m dilation rather than a solar-azimuth shadow projection;
in the retained pilot its cloud-probability component added no raw cloud pixels
across the 70 scene pairs, while proximity/dilation rejected 57,509 additional
pixels.

The v2 mask therefore uses an explicit SCL allowlist only. SCL 7 is
provisionally treated as clear for candidate generation and its fraction is
recorded for every scene/composite; this is not a validated quality or burned-
area claim. Missing, unexpected, or unreviewed SCL/processing-baseline metadata
fails closed. Package 2A.6 must read either the STAC
`s2:processing_baseline` or GEE `PROCESSING_BASELINE` value, normalize it
without rounding, and enumerate every value present in the baseline and replay.

The present 72-object baseline used a different SCL policy. Observations cannot
be compared scientifically with a method-incompatible baseline, so the
baseline rebuild is now required rather than optional.

### Physical acquisition and composition

One pilot date, 2026-04-07, contains distinct S2A and S2B datatakes roughly ten
minutes apart. “Same calendar day” is not a sufficient acquisition identity.
Tiles from the same datatake may form one spatial acquisition; different
datatakes remain separate observations.

The coverage-ranked first-valid method is selected because it is deterministic,
keeps every selected pixel's bands from one scene, and produced identical
contributor arrays in 52 of 57 comparable cases. The cloud-probability ranking
did not improve coverage and adds an unnecessary dependency and seam risk. The
GEE order must be explicit because ordinary mosaicking gives later images
priority.

## Phase 2A.5 reasoning

### MapBiomas source correction

The official MapBiomas collections page currently distinguishes two sources:

- the true Collection 10.1 GEE asset
  `projects/mapbiomas-public/assets/brazil/lulc/collection10_1/mapbiomas_brazil_collection10_1_coverage_v1`;
- the direct GeoTIFF link explicitly labelled Collection 10 under a
  `collection_10` path.

The local 30 m file's MD5 equals the remote ETag
`dc8434523522eac0c69be51d9473efeb`, and the remote object reports a
last-modified date of 2025-08-13. The Collection 10.1 handbook and release are
from February 2026. The direct-download bytes therefore cannot be claimed as a
Collection 10.1 acquisition. The v1 registry's 10.1 label is retained only as
historical audit evidence and is superseded for future use.

Package 2A.6 must export `classification_2024` from the official Collection
10.1 asset under the locked export contract: confirm asset metadata and band,
bind the monitoring extent, use the selected band's exact native CRS/transform,
omit a conflicting scale argument, preserve categorical values with nearest
neighbour only, and encode the source mask as NoData 255 rather than conflating
it with class 0. The manifest records the Earth Engine project/task, request and
metadata hashes, timestamps, output header/bytes/checksum, histogram, mask count,
and class-0 count. The existing national file is not deleted or overwritten.

Because the v1 comparison package used Collection 10 bytes under a 10.1 label,
the new export requires regenerated v2 context registry, regional manifest,
per-case evidence, cross-collection statistics, blinded reviewer panels, and
method-comparison package. V1 remains audit-only and is not valid input for a
qualified review.

### Mapping and subsets

Collection 3 beta 10 m remains the primary detailed 2024 context. The fixed
project grouping remains usable because it is explicit, preserves uncertain
and unmapped states, and does not claim to reproduce accuracy or truth. The
Caatinga handbook supplies biome method context; the national integration
legend supplies the shared class hierarchy. The handbook's visible Version
1/PDF metadata V2 conflict remains recorded rather than silently reconciled.

The checksum-bound national legend is the code fixture. The v2 mapping fixes
the exact code lists and treats class 33 as uncertain/mixed in both collections;
this conservative choice avoids manufacturing disagreement solely from two
project category interpretations. Code 27 is not-assessed, unknown codes remain
unmapped, and source-specific class 0 plus exported 255 are excluded and counted.

The inclusive 50% threshold is calculated from Collection 3 pixels whose
centres fall inside the detection polygon. Its numerator is mapped natural-
vegetation pixels and its denominator is every valid mapped pixel; NoData,
unknown, not-observed, and unmapped values are excluded. A zero denominator is
not-assessed. The 75% alternative remains sensitivity-only. This is a context
filter, not confidence or accuracy, and raw detections remain available.

### Spectral context

The v1 dNBR, post-NBR, BSI, class proportions, missingness, and assessed share
remain useful quantitative context. The 60% dominant-share alternative is more
conservative than a 0.15 plurality margin because it requires one class to hold
an absolute majority of assessed pixels. It is selected only for internal
candidate comparison.

The retained internal pixel rules use finite dNBR/post-NBR/BSI values and their
fixed v1 thresholds. Counts and proportions use detector-grid pixel centres
inside the polygon. The selected aggregator emits a unique top assessed class
only at a share of at least 0.60; otherwise it emits mixed/uncertain, and an
empty assessed denominator is not-assessed. It runs only on the selected v2
mask/composition, not across obsolete candidate strata.

Public labels remain disabled. If Phase 5 supports them, the minimum approved
explanation is: “assinatura espectral contextual; indica semelhança com um
padrão e não determina a causa da mudança.” Fire, clearing, or another cause
must never be asserted from this signature alone.

## Package 2A.6 — required implementation closure

Before Phase 3 or any full replay:

1. define and implement the complete v2 acquisition, observation, event,
   lineage, persistence-contribution/state, and processing-ledger family with
   new IDs, schemas, examples, validators, and no v2-to-v1 serialization;
2. retain all same-day datatake observations but finalize only one persistence
   contribution per event/date after every manifest-bound acquisition is
   terminal; test deterministic intraday order, retries, late arrivals, and
   split/merge lineage;
3. implement and test `scl-explicit-allowlist-v2`, fail closed on missing or
   unreviewed metadata, and enumerate every processing baseline;
4. make coverage-ranked ordering explicit locally and in GEE, with contributor
   maps, repeatability, order-invariance, and parity tests;
5. rebuild all baseline objects using the identical mask and validate the full
   baseline manifest;
6. verify the national legend fixture and implement the exact v2 mappings,
   class-0/27/255 policy, pixel-centre majority subset, and internal signature;
7. export true Collection 10.1 `classification_2024` under its full manifest
   contract and regenerate every affected Phase 2A.5 v2 evidence/review artifact;
8. invalidate the mislabeled Collection 10 crop for runtime and qualified-review
   use without deleting its audit bytes;
9. lock drought disabled in every candidate entrypoint;
10. update algorithm/source versions and pass deterministic and fail-closed
   regression gates.

This is a high-intensity package, estimated at 30k–55k implementation tokens
plus GEE/baseline processing time. It can run in parallel with Packages 2B.0–2B.4,
but Package 2A.6 owns the v2 ledger contract, schema, and backend producer.
Package 2B.2 consumes that exact version/checksum for publication; its gate
cannot close until the producer/consumer integration passes. Both tracks must
close before Phase 3.

## Gate decision

- Candidate-generation policy gate: **closed**.
- Candidate-generation implementation gate: **open; Package 2A.6 required**.
- Scientific validation gate: **open; Phase 5 qualified evidence required**.
- Packages 2B.0–2B.4: **authorized in order, only in isolated green resources,
  in parallel with 2A.6**.
- Production workflow, route, and pointer mutation: **not authorized**.
- Phase 3 and full 2026 replay: **not yet authorized**.
- Accuracy claims, public contextual labels, canonical status, and Phase 6
  promotion: **require Phase 5 qualified evidence and all prior gates**.

## Primary evidence and references

- MapBiomas collections and official Collection 10.1 asset:
  <https://brasil.mapbiomas.org/colecoes-mapbiomas/>
- MapBiomas Collection 3 beta 10 m:
  <https://brasil.mapbiomas.org/mapbiomas-cobertura-10m/>
- Sentinel-2 S2cloudless cloud/shadow method:
  <https://developers.google.com/earth-engine/tutorials/community/sentinel-2-s2cloudless>
- Sentinel-2 SR Harmonized SCL definitions:
  <https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED>
- Earth Engine compositing and mosaicking:
  <https://developers.google.com/earth-engine/guides/ic_composite_mosaic>
- CHIRPS v3:
  <https://www.chc.ucsb.edu/data/chirps3>
- Official Collection 10 legend fixture:
  <https://brasil.mapbiomas.org/wp-content/uploads/sites/4/2025/08/Legenda-Colecao-10-Legend-Code.pdf>
- Local MapBiomas handbooks and legend (checksum-bound but intentionally ignored by Git):
  `data/landcover/updated/ATBD_Col3_10m_Caatinga_v1.pdf` and
  `data/landcover/updated/ATBD-Collection-10.1.pdf`, plus
  `data/landcover/updated/Legenda-Colecao-10-Legend-Code.pdf`.
