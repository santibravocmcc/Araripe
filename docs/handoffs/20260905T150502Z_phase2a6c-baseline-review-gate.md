# Recoverable handoff — Execute the Earth Engine half of Package 2A.6C &#40;baseline 2.0.0 rebuild&#41;

- Created (UTC): <code>2026-09-05T15:05:02Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: Owner decision: recorded review of processing baselines outside the closed registry
- Exact target: baseline 2.0.0 rebuild, 12 monthly exports to Drive folder araripe&#95;baselines&#95;v2
- Required activation: A recorded review document in config/ validated by validate&#95;registry&#95;extension, covering the ten observed values, or an owner decision to narrow the source set

## Safety state

- Last atomic step completed: Phase 1 metadata pass completed read&#45;only and its evidence written
- Canonical pointer changed: false — No pointer write was attempted; no publication step ran
- Partial artifact exposed publicly: false — No export task was started and no object was written anywhere
- Legacy/current production changed: false — Baseline 1.0.0 manifest verified byte&#45;identical against its pinned checksum before and after
- Rollback state: No rollback required because no external mutation occurred

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260905T150502Z&#95;phase2a6c&#45;baseline&#45;review&#45;gate.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>claude/phase2a6c&#45;baseline</code>, commit: 77d090cef527c3fd0075807327ac7fdd16073d50, status:

<pre>?? docs/implementation/&lt;opaque-name sha256:5f40ba1531d5e0f72287ad74188480598fbe777b0a24aac50070ddaac2e22695&gt;</pre>

## Completed

- Read the governing workspace and repository instructions, the official execution procedure, the implementation record and its addendum, the roadmap package and exit gate, the scientific decision record, and the platform contract amendment
- Verified the Earth Engine capability: approved project, owner interactive credential with no service&#45;account key present, and the recorded client version
- Ran the Phase 1 metadata pass read&#45;only over the five source years and twelve months
- Enumerated 2079 scenes forming 575 physical datatakes with platform, datatake instant, native scene IDs and per&#45;scene processing baseline
- Evaluated the reviewed&#45;registry gate and the platform gate
- Wrote the machine&#45;readable Phase 1 evidence into the implementation folder

## External mutations already made

- No external mutation: read&#45;only metadata queries only, zero export tasks started

## Verification performed

- Baseline 1.0.0 immutability check passed before and after the pass
- Evidence document self&#45;consistency checked: datatake, scene and blocked&#45;scene totals reconcile
- Platform gate passed: only the three contract&#45;representable units were observed
- Focused and full backend test gates were run

## Remaining work

- Owner records the review for the ten values, or narrows the accepted source set
- Resume Phase 1 to compute per&#45;scene valid&#45;pixel counts under the effective registry
- Run Phase 2 composition, monthly statistics and the twelve monthly exports
- Run Phase 3 month&#45;by&#45;month split, audit and immutable manifest

## Resume preflight

- Read this checkpoint, recheck the branch and head commit, and reverify baseline 1.0.0 immutability
- Load the recorded review through the registry loader and confirm the effective value set before any composite

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260905T150502Z_phase2a6c-baseline-review-gate.md`. Read it first and revalidate repository and live state. Missing capability: Owner decision: recorded review of processing baselines outside the closed registry. Required activation: A recorded review document in config/ validated by validate_registry_extension, covering the ten observed values, or an owner decision to narrow the source set. Exact target: baseline 2.0.0 rebuild, 12 monthly exports to Drive folder araripe_baselines_v2.

Resume the Earth Engine half of Package 2A.6C on branch claude/phase2a6c-baseline only after a recorded review document exists in config/ and loads through load_baseline_rebuild_registry. Consume the existing rebuild machinery; do not redefine mask, composition, contracts or statistics. Recompute the Phase 1 valid-pixel counts under the effective registry before building any plan.</pre>
