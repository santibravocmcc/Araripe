# Executing the baseline 2.0.0 rebuild (Package 2A.6C)

**Status:** procedure fixed and gated locally; Earth Engine execution pending
**Applies to:** baseline version `2.0.0` only
**Does not apply to:** baseline `1.0.0`, whose build procedure is
`docs/BASELINE_GEE.md` and whose artifacts are immutable

The accepted 1.0.0 generation used the legacy SCL policy (clear classes
`{2,4,5,6,7,11}`) and a plain collection median. The 2026-08-11 decision
record replaced that policy, so observations can no longer be compared
scientifically against it: the baseline must be rebuilt with the identical
accepted candidate science before any 2026 replay. That rebuild is version
`2.0.0`; version `1.0.0` is retained unchanged as audit and rollback material.

## 1. What is fixed and what is decided

Fixed by `build_baseline_rebuild_plan` and the contracts; not negotiable at
execution time:

- collection `COPERNICUS/S2_SR_HARMONIZED`, source years
  `{2017, 2019, 2021, 2022, 2025}`, months 1–12, scene metadata cloud filter 40;
- the audited 1.0.0 grid (EPSG:32724, 20 m, 10773 × 4999) so a rebuilt object
  stays pixel-compatible with the detector and the accepted wider extent;
- `scl-explicit-allowlist-v2` (accept SCL 4/5/6/7 only) with fail-closed
  missing / unexpected / unreviewed metadata;
- `coverage-ranked-first-valid-v1` composition scoped to one physical datatake,
  executed through the explicit reversed-order mosaic plan;
- monthly multi-year **median** and **population standard deviation** across
  datatake composites, plus the per-index **contribution depth**;
- platforms `S2A`/`S2B`/`S2C` (the acquisition-v3 contract); anything later
  fails closed and needs a new contract major, not a flag.

Decided by the owner, at the moment the evidence exists:

- **which Earth Engine project** executes the rebuild;
- **whether a processing baseline outside `{05.11, 05.12}` is accepted**, one
  recorded review per value (§5);
- **whether any minimum contribution depth should later gate detection** — see
  the open question in §8. The rebuild measures depth; it deliberately does not
  impose a threshold.

## 2. Version isolation

Nothing in a 2.0.0 rebuild shares a name, key, or directory with 1.0.0:

| Artifact | 1.0.0 (immutable) | 2.0.0 (rebuild) |
|---|---|---|
| Drive folder | `araripe_baselines` | `araripe_baselines_v2` |
| Export file | `araripe_baseline_monthNN.tif` | `araripe_baseline_v2_monthNN.tif` |
| Object key prefix | `baselines/` | `baselines_v2/2.0.0/` |
| Local rasters | `data/baselines/` | `data/baselines_v2/2.0.0/` |
| Contribution depth | — | `data/baselines_v2/2.0.0_evidence/counts/` |
| Downloaded exports | — | `data/baselines_v2/exports/` (transient) |
| Manifest | `config/baseline_manifest_v1.json` | `config/baseline_manifest_v2.json` |
| Splitter | `scripts/split_gee_baselines.py` | `scripts/split_baseline_v2_exports.py` |

These are enforced, not conventional: the manifest validator rejects a v1
export name, a v1 Drive folder, a v1 key prefix, and any write over the v1
manifest; the v2 splitter refuses to write anywhere inside `data/baselines/`
and refuses any export file that is not a canonical v2 monthly name.

`require_baseline_v1_untouched()` verifies the 1.0.0 manifest bytes against a
pinned SHA-256 before and after the rebuild.

## 3. Prerequisites

1. **Earth Engine project**, owner-approved and registered for non-commercial
   use, with the account authenticated locally
   (`earthengine authenticate`). Never the production service-account key
   used by `.github/workflows/detect_gee.yml`; never a credential handed to an
   agent.
2. **`earthengine-api` in the `araripe` environment.** Record the exact
   version; it belongs in the execution provenance.
3. **Local disk:** ≥ 30 GB free. The 72 rebuilt rasters are ~13.4 GB (the
   1.0.0 generation's exact size) and each monthly export is ~1.3–2 GB.
4. **Drive:** ~25 GB, or month-by-month download-and-delete.

## 4. Phase 1 — metadata pass (read-only)

Enumerate, for the five source years and twelve months, every physical
datatake over the monitoring extent: platform, datatake identifier, sensing
instant, provider-native scene IDs, the processing baseline of each scene, and
each scene's valid-pixel count under the v2 mask (`reduceRegion`).

This pass touches no pixels beyond counting and produces no artifact for
promotion. It exists to surface the §5 decision **before** any composite is
built, and its counts are what `build_rebuild_gee_plan` turns into the
deterministic per-datatake execution order.

## 5. Owner decision gate — reviewed processing baselines

`araripe-reviewed-processing-baselines-v1` is `{05.11, 05.12}`: the complete
enumeration observed across the 70 retained Phase 2A.4 pilot scenes, which are
2025-era. Historical source years will almost certainly carry other values.

When they appear, **execution stops**. The values become usable only through a
recorded review document validated by `validate_registry_extension`, which
requires a reviewer, an ISO date, a scope, and — per value — the basis of the
review and where it was observed. There is no fallback path and no flag.

Two facts that inform the decision, neither of which decides it:

- the collection is `S2_SR_HARMONIZED`, which already harmonises the 2022
  reflectance-offset change, so the classic cross-baseline offset hazard is
  mitigated upstream;
- SCL class 2 changed meaning at PB04 (`dark-area-pixels` → `cast-shadows`),
  but class 2 is **rejected under both** regimes, so the mask decision itself
  does not depend on the baseline era.

A platform outside `S2A`/`S2B`/`S2C` is a different matter entirely: it needs
a new contract major, as Package 2A.6B.1 did for Sentinel-2C.

## 6. Phase 2 — composition, statistics, export

Per datatake: derive the plan from the Phase 1 counts, reconcile recomputed
counts against the plan, and mosaic strictly in the plan's reversed order with
one shared per-image mask, so no pixel mixes bands across scenes.

Per calendar month: reduce the datatake composites to median, population
standard deviation, and contribution count for each of `evi2`, `nbr`, `ndmi`.

Export one nine-band GeoTIFF per month to `araripe_baselines_v2`, named
`araripe_baseline_v2_monthNN.tif`, bands in this order:

```
ndmi_median, nbr_median, evi2_median, ndmi_std, nbr_std, evi2_std,
ndmi_count, nbr_count, evi2_count
```

Statistics are unmasked to `-9999` (restored to NaN locally); counts are
unmasked to `0`, which is the honest value — zero contributions. Record every
export task identity.

## 7. Local split, audit, manifest

Work month by month so peak disk stays bounded:

```bash
/opt/anaconda3/envs/araripe/bin/python scripts/split_baseline_v2_exports.py --in-dir data/baselines_v2/exports
```

The splitter restores the sentinel, enforces the exact per-index range
contract, writes the six canonical COGs plus three contribution-depth rasters,
and merges its evidence JSON across runs. Delete each export after it splits.

An out-of-contract statistic **fails closed** with a diagnostic rather than
being masked. That is deliberate: the v1 splitter's blanket `|v| > 1.5` mask is
looser than the NDMI/NBR contract, so a real anomaly could have been hidden
behind a manifest that then validated. Investigate the composite; do not widen
the tolerance to get past it.

When all twelve months are split, build the immutable manifest:

```bash
/opt/anaconda3/envs/araripe/bin/python scripts/rebuild_baseline_v2_manifest.py --execution-evidence <evidence.json> --build-date <YYYY-MM-DD>
```

Validation re-derives every acquisition ID through the v3 contract and every
per-datatake plan checksum from that entry's own scene counts, and reconciles
each raster's finite-pixel count against its contribution-depth evidence — a
monthly statistic is finite exactly where at least one composite contributed,
so fabricated coverage on either side cannot survive the other.

## 8. Open scientific question (not decided here)

The rebuild records how many datatake composites back every pixel of every
monthly statistic. This matters because detection divides an observation's
departure by this baseline's dispersion: a pixel backed by one composite has a
population standard deviation of exactly zero, and two gives a value that is
arithmetically defined but statistically meaningless. The 1.0.0 generation
could not express this at all.

Whether a minimum depth should mask such pixels, widen their thresholds, or
merely annotate their alerts is a scientific decision that needs the depth
distribution first and belongs to the owner and Phase 5 — not to a build
script. The manifest therefore reports minimum, maximum, median, the zero tail,
and the below-three tail per index and month, and imposes nothing.

## 9. What this procedure must never do

- write to R2, dispatch a workflow, or touch production, blue schedules, the
  Worker, buckets, the domain, DNS, routes, the site, the broker, GitHub
  Environments, or any credential;
- modify, delete, or overwrite baseline 1.0.0 in any form;
- flip runtime `BASELINE_VERSION` to `2.0.0` — activating the rebuilt baseline
  for candidate generation belongs to the replay packages, after the manifest
  exists and validates;
- start Package 2A.6D, the 2026 replay, or the MapBiomas Collection 10.1
  export.
