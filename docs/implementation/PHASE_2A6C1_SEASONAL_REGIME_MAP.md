# Package 2A.6C.1 — seasonal source regimes: change map

**Status:** mapping accepted for implementation
**Owner decision:** 2026-09-05 — widen the reviewed registry for the wet season
only, relax the wet-season scene cloud filter, and declare the wet season an
explicit source regime because the compromise is one of reproducibility.
**Predecessor:** Package 2A.6C (`docs/implementation/PHASE_2A6C_2026-09-01.md`)

## 1. Why a contract change is unavoidable

The rebuild executed on 2026-09-05 produced all 72 rasters but could not write
its manifest: months 01–04 fell below the accepted `>= 0.99`
extent-coverage floor (0.4459 / 0.8325 / 0.9710 / 0.9460). Measurement of the
alternatives established that no configuration reachable under the *current*
contracts fixes it:

- relaxing the cloud filter alone tops out at 0.8314 in January, even with the
  filter removed entirely;
- adding quiet-ENSO source years moves January by 0.0002, because ESA has
  barely reprocessed the wet season of 2016–2022 onto the Collection-1 lineage;
- only two measured options clear the floor in all four months — widening the
  registry globally, or admitting the strong-El-Niño years 2023/2024.

The accepted decision is the third path: **a different source policy for the
wet season than for the dry season**. That is not expressible today. Every
source-policy element in the Package 2A.6C machinery is a single global value.

## 2. What is NOT changing

This is the load-bearing result of the survey, and it bounds the work.

`reviewed_baselines` is already a **parameter** of every closed-science entry
point — `compute_scene_scl_mask`, `scl_mask_v2`'s gates, `compose_datatake`,
and `execute_gee_plan_locally` all take it from the caller and default only for
convenience. Regime scoping is therefore entirely a *caller* concern.

- `src/processing/scl_mask_v2.py` — **unchanged**
- `src/processing/composition_v2.py` — **unchanged**
- `src/processing/gee_composition_v2.py` — **unchanged**
- `src/detection/identity_v3.py` — **unchanged**
- the accepted mask, composition, statistics, grid and extent — **unchanged**
- the `>= 0.99` coverage floor — **unchanged and not lowered** (see §6)
- baseline 1.0.0 — untouched, as always

The 2A.6C rebuild machinery and manifest discipline are extended, never
loosened: every new field is validated, and every existing gate stays.

## 3. What must change

### 3.1 `src/processing/baseline_rebuild_v2.py`

| Item | Today | Required |
|---|---|---|
| `load_baseline_rebuild_registry` | one optional extension path → one global `effective_values` | accept several recorded reviews and resolve a registry **per regime** |
| `BaselineRebuildRegistryV2` | one value set | unchanged as a type; instantiated once per regime |
| source policy | `GEE_COLLECTION_ID`, `BASELINE_SOURCE_YEARS`, `BASELINE_MAX_CLOUD_COVER` read as globals | cloud filter resolved per regime; collection/years stay global |
| `build_baseline_rebuild_plan(registry=...)` | single registry block | takes an ordered set of regimes; emits a `source_regimes` block |
| `baseline_query_fingerprint()` | hashes one global selection | must hash every regime, or a future generation is not comparable |
| month → policy | implicit (all months identical) | explicit `regime_for_month()` resolution |

New concept, `source-regime-v1`: an id, the calendar months it owns, its
reviewed-baseline registry, its scene cloud filter, and a declared provenance
state. Regimes must **partition months 1–12 exactly** — no gap, no overlap —
which is the gate that stops a month silently acquiring two policies or none.

### 3.2 `src/detection/baseline_manifest_v2.py`

| Item | Today | Required |
|---|---|---|
| `reviewed_processing_baseline_registry` | one block, validated by `_validate_registry_block` | one block **per regime**, each validated the same way |
| `_validate_datatake_entry` | checks scene baselines against one global `effective_registry` | checks against **that month's** regime registry |
| month entries | no policy field | each month binds its `source_regime` id, cross-checked against the regime's month set |
| `REQUIRED_PROVENANCE_RETAINED` | 9 items | add the per-month source regime and its provenance state |
| provenance | one completeness statement | per-regime provenance state, so a mixed-lineage regime is machine-readable |

### 3.3 `scripts/build_baseline_v2_gee.py`

Resolve the regime per month and pass that regime's registry and cloud filter
into the counts pass, the plan derivation and the composition. The admitted-set
computation becomes regime-aware; a datatake mixing admitted and rejected
baselines must still fail closed, now against its own month's registry.

### 3.4 Configuration artifacts

- `config/phase2a6c1_seasonal_source_regime_amendment_v1.json` — the accepted
  amendment, checksum-bound into the plan and manifest exactly as the
  Sentinel-2C v3 amendment is.
- `config/phase2a6c1_wet_season_processing_baseline_review_v1.json` — the
  owner's recorded review admitting `02.11 02.12 02.13 02.14 03.00 03.01 04.00`
  **for months 1–4 only**. The existing
  `config/phase2a6c_baseline_processing_baseline_review_v1.json` stays
  byte-unchanged and applies to both regimes.

### 3.5 Tests

New coverage required, all fail-closed:

- regimes partition 1–12 exactly; a gap, an overlap or an out-of-range month
  is rejected;
- a scene whose processing baseline is admitted in the wet regime but used in
  a dry-season month fails closed, and vice versa;
- the per-month regime binding in the manifest must match the regime's month
  set;
- the plan checksum and the derived run-manifest binding change with the
  regimes, and identical regimes reproduce identical checksums;
- the query fingerprint covers every regime;
- a manifest declaring a regime not present in the plan is rejected;
- baseline 1.0.0 immutability, unchanged.

## 4. Execution consequence

The rebuild plan checksum is regime-derived, so it changes, and with it the v3
run-manifest binding and **every acquisition identity**.

The rasters, however, depend only on the source scenes and the closed science.
The dry regime keeps exactly the policy that produced months 05–12 — the same
registry and the same cloud filter — so **those eight months are byte-valid as
they stand and are not re-exported**. Only months 01–04 change source policy
and must be recomputed. This is the difference between four export tasks and
twelve.

## 5. Chosen wet-season policy

Months 1–4: registry widened to every observed value, scene cloud filter `< 60`.

Measured outcome: coverage 0.9991 / 1.0000 / 1.0000 / 1.0000; January's
below-three-contribution tail falls from 99.2% to 21.7%.

The filter stops at 60 rather than 80 or unfiltered on measured evidence, not
caution: a cloud-leakage test found no systematic contamination in NDMI or NBR
(the sign was inconsistent, and reversed in March), but EVI2 — the only index
using the red band, which thin cloud brightens most — carries a positive offset
that grows monotonically with cloud, `+0.027` at 40–60% and `+0.043` at 60–80%
against a clean dispersion of `0.087`. The 60 bound takes the coverage while
holding that one measured bias at its smaller value. The test's limits are
recorded in the implementation record; it is not a general clearance.

## 6. What this deliberately does not do

- **The coverage floor is not lowered.** The chosen policy clears `0.99` in
  every month, so 2A.2 discipline is kept intact rather than relaxed to fit.
- **No minimum contribution depth is imposed.** That remains the owner's and
  Phase 5's decision; the rebuild still measures and reports.
- **The wet-season regime is not permanent.** ESA is actively reprocessing —
  January 2019 is 7/25 done, April 2019 1/14, August 2021 65/78 — so the
  admitted wet-season products are precisely those not yet reached. The regime
  records a provenance state that a future package can retire by rebuilding
  the wet season on pure Collection-1. The declaration is machine-readable so
  that retirement has a precise target rather than a prose reminder.
- **Nothing touches production**, R2, workflows, the site, or baseline 1.0.0.
