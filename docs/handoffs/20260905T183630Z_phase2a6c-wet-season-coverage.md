# Recoverable handoff — Execute the Earth Engine half of Package 2A.6C &#40;baseline 2.0.0 rebuild&#41;

- Created (UTC): <code>2026-09-05T18:36:30Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: Owner decision: the Collection&#45;1 source restriction cannot satisfy the accepted extent&#45;coverage contract in the wet season
- Exact target: baseline 2.0.0 manifest for the 72 rebuilt monthly rasters
- Required activation: Either a revised recorded review that admits more processing baselines, or an owner decision on the accepted coverage floor for the wet&#45;season months

## Safety state

- Last atomic step completed: All twelve monthly exports were split and audited; the manifest write refused
- Canonical pointer changed: false — No pointer write was attempted; no publication step ran
- Partial artifact exposed publicly: false — Rasters are local only; nothing was written to object storage and no manifest exists
- Legacy/current production changed: false — Baseline 1.0.0 manifest verified byte&#45;identical against its pinned checksum before and after
- Rollback state: No rollback required; the run wrote only new local files under the isolated v2 directories

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260905T183630Z&#95;phase2a6c&#45;wet&#45;season&#45;coverage.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>claude/phase2a6c&#45;baseline</code>, commit: d6449f6cd31ced697d3222e4f4d860186fca99d8, status:

<pre>?? scripts/build_baseline_v2_gee.py</pre>

## Completed

- Loaded the owner review and confirmed the effective registry and the expected rebuild plan checksum before composing
- Reconfirmed the Earth Engine capability: approved project and owner interactive credential, no service&#45;account key
- Resumed Phase 1 and computed valid&#45;pixel counts for all admitted datatakes
- Verified that the Earth Engine dispersion reducer is the population form and the median is exact at rebuild scale
- Corrected three Earth Engine behaviours that would have corrupted the science or the audit
- Ran Phase 2: derived every per&#45;datatake plan from the counts, reconciled all of them, and exported twelve monthly images
- Ran Phase 3: fetched, grid&#45;verified, split and deleted each export month by month
- Audited the seventy&#45;two rebuilt rasters and measured contribution depth per index and month

## External mutations already made

- Twelve Earth Engine export tasks wrote twelve files to the owner Drive folder for the rebuild
- No object storage write, no workflow dispatch, no production change

## Verification performed

- All admitted datatakes reconciled with zero partition anomalies and exact first&#45;valid priority
- All seventy&#45;two rasters share the single pinned grid with no range violation and no negative dispersion
- The finite&#45;pixel against contribution&#45;depth cross&#45;check passed for all seventy&#45;two
- Four wet&#45;season months fall below the accepted extent&#45;coverage floor
- Focused and full backend test gates were run

## Remaining work

- Owner decides between widening the reviewed registry and revising the wet&#45;season coverage expectation
- Re&#45;run the affected exports under whichever decision is taken
- Write and validate the immutable baseline 2.0.0 manifest

## Resume preflight

- Read this checkpoint, recheck the branch and head commit, and reverify baseline 1.0.0 immutability
- Recompute the rebuild plan checksum under the effective registry before reusing any raster, because every acquisition identity is derived from it

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260905T183630Z_phase2a6c-wet-season-coverage.md`. Read it first and revalidate repository and live state. Missing capability: Owner decision: the Collection-1 source restriction cannot satisfy the accepted extent-coverage contract in the wet season. Required activation: Either a revised recorded review that admits more processing baselines, or an owner decision on the accepted coverage floor for the wet-season months. Exact target: baseline 2.0.0 manifest for the 72 rebuilt monthly rasters.

Resume Package 2A.6C on branch claude/phase2a6c-baseline. Twelve monthly rasters exist locally and audit clean except that four wet-season months fall below the accepted extent-coverage floor. Do not lower that floor and do not widen the reviewed registry without a new recorded review. If the registry changes, every acquisition identity changes with the plan checksum, so all twelve months must be re-exported.</pre>
