# Phase 2A.3 validation-pilot contract, version 1

**Status:** local tooling contract; no scientific method selected

**Package:** Phase 2A.3 — validation tooling and method-selection pilot

**Production mutation:** none

## 1. Purpose and claim boundary

This contract builds a reproducible, local/private desktop package for about
60 location-date cases. Its purposes are to test the sampling and review tools,
identify missing evidence, exercise blinded comparisons, and prepare later
evidence collection for Packages 2A.4 and 2A.5.

The pilot is **not** the final candidate-population validation. It contains no
qualified human labels at generation time and produces no accuracy, precision,
recall, commission, or omission estimate. Reviewing detected features alone
cannot measure omission. Phase 5 still requires the final candidate population
and an independent known-change frame.

No candidate cloud mask, composition, drought adjustment, MapBiomas policy, or
contextual-signature method is selected, activated, promoted, or made
canonical here. Raw detections are read only and remain intact.

## 2. Provisional source population

The frame is the exact set of locally retrieved current `alerts_YYYY-MM-DD`
GeoJSON bytes supplied to the tool. Every source file is recorded by logical
key, byte size, SHA-256, feature count, origin URL when supplied, and a
canonical aggregate inventory SHA-256. The source snapshot is frozen before
sampling.

These alert objects are provisional audit inputs. They are not selected by an
accepted release manifest and their features lack the provider scene list,
accepted acquisition identity, algorithm/baseline/extent identity fields, and
scene QA needed by the Phase 1 observation contract. Therefore:

- each frame unit is explicitly one legacy alert feature at one source date;
- IDs use only `p2a3-audit-location-v1-*` and `p2a3-sample-v1-*` namespaces;
- `acq-v1-*`, `obs-v1-*`, and `evt-v1-*` IDs are never inferred;
- a physical place may occur on more than one date; the package does not call
  that an accepted event; and
- a missing alert file/date is never interpreted as a zero-alert or successful
  date because no accepted processing ledger exists.

## 3. Frame, exclusions, and strata

Every source feature is retained in deterministic `sampling/frame.jsonl.gz`, including excluded
features. Exclusions are technical only:

- missing, invalid, empty, or unsupported geometry;
- invalid or source-file-mismatched detection date;
- geometry wholly outside `araripe-implementation-rectangle-v1`; or
- an exact duplicate geometry/date record, where the stable first locator is
  retained and the duplicate points to it.

Cross-boundary polygons remain whole and carry a boundary flag. Missing or
unknown confidence, land cover, size, or persistence remains eligible in an
`unknown` stratum; it is not silently recoded. Missing evidence after sampling
never triggers replacement.

The six fixed balancing variables are:

| Variable | Levels used for exact balance |
| --- | --- |
| Confidence | `high`, `medium`, `low` (legacy provisional field) |
| Reported polygon area | `[1,2)`, `[2,5)`, `>=5` ha |
| Hydro-season | wet November–April; dry May–October |
| Land-cover context | natural; anthropic; other/water (legacy provisional field) |
| Persistence | first; candidate; confirmed (legacy provisional field) |
| Geography | fixed north/south × west/central/east grid over the accepted wider extent |

The area bands are fixed, not frame quantiles. The geographic grid uses the
accepted wider monitoring rectangle rather than the APA polygon. August–October
is also flagged as the Caatinga leaf-off period; if the frozen population has no
such date, that absence is an explicit limitation and is not repaired by
renaming other months.

## 4. Deterministic selection and probabilities

The tool forms occupied joint cells across all six variables. A binary exact-
margin optimization selects 60 cells, with the requested total divided as
evenly as possible within each variable. SHA-256 ranks derived from the recorded
seed define a full lexicographic cell order. Repeated integer-feasibility checks
fix the first feasible membership decision at each rank, avoiding tolerance-
dependent floating-point objective ties. The full SHA-256 unit rank then selects
one unit from each selected joint cell.

For every frame unit the package records:

- source artifact checksum and zero-based feature index;
- canonical geometry checksum and pilot-local source ID;
- all six strata and joint-stratum ID;
- joint-stratum population/sample count;
- full SHA-256 selection rank;
- eligibility/exclusion and selected-cell/selected-unit status; and
- exact recorded probability.

A selected joint cell has cell probability `1`; an unselected cell has
probability `0`. Within a selected cell, the seeded hash draw is treated as a
uniform conditional draw with probability `1/N_h`. Thus a unit's recorded
selection probability is `1/N_h` in a selected cell and `0` elsewhere. This
purposive balance intentionally gives incomplete population support. The
probabilities document the draw; they must not be used to claim a population
accuracy estimate.

## 5. Evidence contract

Every selected case has these mandatory evidence slots, each either available
with provenance/checksums or explicitly missing/unavailable/insufficient with a
reason:

1. pre-date imagery;
2. post-date imagery;
3. wider spatial context;
4. provenance-valid location time series;
5. independent-source/sensor comparison; and
6. MapBiomas contextual comparison.

Evidence records distinguish `operational_source_same_sensor`,
`independent_sensor`, `contextual_classification`, and `unverified_basemap`.
Sentinel-2 from another catalog is same-sensor evidence, not an independent
sensor. Landsat may corroborate a case but does not become a production source
or inherit the Sentinel-2 baseline. MapBiomas is context, not a known-change or
omission reference.

Each available scene-derived panel records the provider/catalog/collection,
provider-native item ID, observation time, item-metadata SHA-256, source asset
identity without expiring signed query tokens, window/buffer, band/render
parameters, temporal gap, coverage/cloud metadata, local byte size, and local
SHA-256. A rendered derivative checksum does not prove the upstream COG bytes;
that limitation is retained.

The tracked SQLite file remains `quarantined_mixed_generation_audit`. It has no
location or acquisition identity and cannot populate a location series. A case
series is available only when newly derived from item-provenanced observations;
otherwise the slot says unavailable. No legacy row is salvaged.

## 6. Reviewer separation and controlled fields

The package has coordinator-only and reviewer-facing trees. A deterministic
blind ID and seeded reviewer order hide system confidence, persistence,
land-cover strata, contextual label, source locator, and sample crosswalk from
the initial assessment. Method alternatives, when later provided, use A/B IDs;
the option key remains coordinator-only.

The primary reviewer receives every case. A deterministic 20% subset is
assigned independently to a second reviewer in a different order. Reviewers do
not see prior labels or agreement-subset status. Agreement later assesses
reviewer reliability, not scientific accuracy.

Human fields begin null and `unreviewed`. Controlled labels are:

- change: `real_change`, `no_change`, `uncertain`, `unreviewable`;
- temporal confidence: `high`, `medium`, `low`, `not_assessable`;
- land-cover context: natural vegetation, anthropic agriculture/pasture,
  built/extractive, water/wetland, bare/other natural, mixed, unknown, or not
  assessable; and
- contextual signature: `fire_like`, `exposed_soil_or_clearing_like`,
  `mixed_or_uncertain`, or `not_assessed`.

`uncertain` means the required evidence is present but ambiguous or conflicting.
`unreviewable` means required evidence is missing, obscured, corrupt, or
otherwise insufficient. Missing/obscured required before or after imagery
normally makes the case unreviewable; the case remains in the sample.

Each method family (`cloud_mask`, `daily_composition`, `drought_adjustment`,
`mapbiomas`, and `contextual_signature`) has separate A/B/equivalent/
inconclusive/unreviewable fields. Primary change judgement is completed before
method comparison. Every family is initially `not_generated_in_2a3` and
`selected_or_activated=false`.

## 7. Package integrity and privacy

`manifest.json` inventories every immutable file except itself and
`CHECKSUMS.sha256`. The checksum list binds the manifest plus every inventoried
file and excludes only itself, avoiding a circular self-checksum. Validation
rejects unlisted, missing, altered, absolute/traversal, or symlinked paths;
reconciles the frame, sample, cases, assignments, probabilities, and blank human
fields; and verifies that no method/accuracy claim is present.

The real package is local/private audit material. Downloaded alerts, rendered
imagery, signed URLs, reviewer exports, and generated bundles are ignored by
Git and must not be uploaded or published. Signed query parameters and
credentials must never enter provenance records. Redistribution and
attribution require a separate source-specific review.

## 8. Local commands

```bash
/opt/anaconda3/envs/araripe/bin/python scripts/build_validation_pilot.py \
  --alerts-dir <read-only-alert-snapshot> \
  --out-dir data/validation/phase2a3-pilot-v1 \
  --generated-at <fixed-RFC3339-time> \
  --source-retrieved-at <fixed-RFC3339-time>

/opt/anaconda3/envs/araripe/bin/python \
  scripts/validate_validation_package.py \
  data/validation/phase2a3-pilot-v1
```
