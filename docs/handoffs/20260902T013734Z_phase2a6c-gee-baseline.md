# Recoverable handoff — Execute the Package 2A.6C baseline 2.0.0 rebuild on Earth Engine

- Created (UTC): <code>2026-09-02T01:37:34Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: Approved Earth Engine project with local authentication in the araripe environment
- Exact target: Server&#45;side monthly composites of COPERNICUS S2 SR HARMONIZED into 12 recorded export tasks and 72 local rasters under data/baselines&#95;v2
- Required activation: Owner approves one Earth Engine project for this rebuild, the user authenticates locally, and earthengine&#45;api is installed in the araripe conda environment

## Safety state

- Last atomic step completed: Local rebuild machinery, manifest 2.0.0 discipline, and the full backend gate of 739 tests completed cleanly
- Canonical pointer changed: false — No release pointer, publication state, or R2 object was read for mutation or changed
- Partial artifact exposed publicly: false — No raster was produced and nothing was uploaded, exported, or published anywhere
- Legacy/current production changed: false — Baseline 1.0.0 manifest bytes verified against the pinned checksum; blue workflows, Worker, buckets, domain, site, broker, and Environments untouched
- Rollback state: No rollback needed; the branch holds only additive local files and no external mutation occurred

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260902T013734Z&#95;phase2a6c&#45;gee&#45;baseline.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>claude/phase2a6c&#45;baseline</code>, commit: e87097e39a31b57eafbeb592788aaaa859b56711, status:

<pre>?? scripts/rebuild_baseline_v2_manifest.py
?? src/detection/baseline_manifest_v2.py
?? src/processing/baseline_rebuild_v2.py
?? tests/test_baseline_manifest_v2.py
?? tests/test_baseline_rebuild_v2.py</pre>
- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/site</code> — branch <code>codex/workspace&#45;consolidation</code>, commit: 15a876c25a116ecdc20b227d2b1194b88852702d, status:

<pre>clean</pre>

## Completed

- Created branch claude/phase2a6c&#45;baseline at the exact Package 2A.6B.1 science commit and verified the hash before editing
- Implemented the baseline 2.0.0 rebuild machinery consuming the accepted v2 SCL allowlist, datatake&#45;scoped composition, GEE plan parity, and v3 acquisition identities unchanged
- Implemented the recorded&#45;review&#45;only registry extension for historical processing baselines with fail&#45;closed defaults
- Implemented the baseline 2.0.0 manifest builder, raster auditor, fail&#45;closed validator, immutable writer, and manifest CLI with Package 2A.2 discipline
- Added 67 focused regressions for mask identity, complete manifest validation, baseline 1.0.0 immutability, unreviewed platform and baseline fail&#45;closed behavior, and composition plan parity
- Wrote the Package 2A.6C implementation record, committed together with this checkpoint

## External mutations already made

- No external mutation; only additive local files in the backend repository

## Verification performed

- Full backend gate passed with 739 tests including the 67 new Package 2A.6C regressions
- Standalone v2 and v3 contract validators passed unchanged
- Baseline 1.0.0 manifest bytes verified against the pinned checksum
- Git status shows only additive files; no tracked 2A.6A, 2A.6B, or 2A.6B.1 file modified

## Remaining work

- Owner approves one Earth Engine project for the rebuild and the user authenticates locally
- Install earthengine&#45;api in the araripe conda environment
- Metadata pass enumerating datatakes, scenes, processing baselines, and per&#45;scene valid pixel counts for the five source years
- Owner&#45;recorded registry extension for any processing baseline outside the closed reviewed registry before any composite is built
- Execute per&#45;datatake plans with reversed mosaic order, monthly median and population standard deviation, and 12 recorded export tasks
- Download, split into 72 rasters under data/baselines&#95;v2, audit, and write the immutable baseline 2.0.0 manifest via the manifest CLI
- Rerun the full backend gate and update the Package 2A.6C implementation record with execution evidence

## Resume preflight

- Read this checkpoint, the Package 2A.6C implementation record, the roadmap Package 2A.6 section, and the araripe&#45;safe&#45;handoff skill
- Revalidate the backend branch, commit, and clean state
- Confirm the approved Earth Engine project and authenticated principal explicitly before any call and never substitute another project or principal
- Verify the baseline 1.0.0 manifest checksum before and again after execution
- Never write to R2 or production and never dispatch any workflow from this task

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260902T013734Z_phase2a6c-gee-baseline.md`. Read it first and revalidate repository and live state. Missing capability: Approved Earth Engine project with local authentication in the araripe environment. Required activation: Owner approves one Earth Engine project for this rebuild, the user authenticates locally, and earthengine-api is installed in the araripe conda environment. Exact target: Server-side monthly composites of COPERNICUS S2 SR HARMONIZED into 12 recorded export tasks and 72 local rasters under data/baselines_v2.

Execute only the blocked Earth Engine half of Package 2A.6C for the Observatorio da Chapada do Araripe backend, on branch claude/phase2a6c-baseline. Read first: this checkpoint; the PHASE_2A6C_2026-09-01.md record under docs/implementation; the ROADMAP Package 2A.6 section and exit gate P2A; the 2026-08-11 scientific decision record under docs/decisions; and the araripe-safe-handoff skill. The deterministic machinery is already implemented and tested: baseline_rebuild_v2.py under src/processing, baseline_manifest_v2.py under src/detection, and the manifest CLI rebuild_baseline_v2_manifest.py under scripts. Consume it; never redefine the mask, composition, or contracts.

Requirements: use only the explicitly approved Earth Engine project and authenticated principal. Source collection COPERNICUS/S2_SR_HARMONIZED, years 2017, 2019, 2021, 2022 and 2025, months 1-12, scene metadata cloud filter 40, the audited 1.0.0 grid (EPSG 32724, 20 m, 10773 by 4999), the v2 SCL allowlist accepting only classes 4, 5, 6 and 7, and datatake-scoped coverage-ranked first-valid composition exactly as build_rebuild_gee_plan derives it, with reversed mosaic input order and one shared per-image mask. Monthly statistics are the median and the population standard deviation across datatake composites of reflectance indices evi2, nbr and ndmi. Run a metadata pass first; if any processing baseline outside 05.11 and 05.12 appears, stop and obtain an owner-recorded registry extension (validate_registry_extension) before composing anything; unreviewed values and platforms beyond S2A, S2B and S2C must keep failing closed. Sentinel-2C is representable through the v3 contracts.

Record the project identity, every export task identity, the query fingerprint, export checksums, per-datatake plan checksums, and count reconciliation evidence. Download and split the 12 exports into the 72 canonical rasters under data/baselines_v2, then build the immutable manifest with the manifest CLI. Baseline 1.0.0 stays untouched and require_baseline_v1_untouched must pass before and after. Never write to R2, never dispatch workflows, never touch production, blue schedules, the Worker, buckets, domain, DNS, routes, site, broker, GitHub Environments, or any secret. Keep runtime BASELINE_VERSION at 1.0.0; activation belongs to the replay packages. Do not start Package 2A.6D, the 2026 replay, or the MapBiomas Collection 10.1 export. Run the focused baseline tests and the full backend gate, update the PHASE_2A6C_2026-09-01.md record with the execution evidence, and commit coherently on this branch. If any capability is missing, stop safely and create a new immutable handoff checkpoint.</pre>
