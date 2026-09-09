# Recoverable handoff — Deposit the Phase 4 replay candidate as a green run prefix in staging

- Created (UTC): <code>2026-09-09T18:40:30Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: A staging&#45;scoped R2 object identity reachable from a lane, and a lane that runs the run assembler at all
- Exact target: runs/&#60;run&#45;id&#62;/ in the araripe&#45;v2&#45;staging bucket
- Required activation: Either an operator runs the assembler apply mode with the staging identity, or a reviewed workflow step is added and merged to the default branch so the v2&#45;staging environment will release its identity

## Safety state

- Last atomic step completed: The candidate was assembled and validated locally by the same library the deposit lane calls, and its run prefix was materialised on disk with a digest per object
- Canonical pointer changed: false — No pointer read or write was attempted; the publish and promote steps were never invoked
- Partial artifact exposed publicly: false — Nothing was uploaded to any bucket; every artifact is under an isolated local directory outside both repositories
- Legacy/current production changed: false — No workflow was dispatched, the blue time&#45;series database was opened read&#45;only, and the blue baseline default is unchanged
- Rollback state: No rollback required because no external mutation occurred

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260909T184030Z&#95;green&#45;run&#45;deposit&#45;lane.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>claude/phase4b&#45;replay&#45;execution</code>, commit: 66206321aa9cac24e1aa4d9165593c11d72e9c84, status:

<pre>?? docs/implementation/PHASE_4B_2026-09-09.md
?? docs/operations/PACKAGE_P4C_PROMPT.md</pre>
- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/site</code> — branch <code>claude/phase3&#45;site&#45;freeze</code>, commit: cadbeaead6e724e6780527884a40bf67ad8e3d37, status:

<pre>clean</pre>

## Completed

- Ran the 2026 replay in bounded chronological batches against the decided baseline generation
- Reproduced the enumeration of the previous session, minting the same run manifest identity
- Recorded which seasonal source regime each month was composed against, scoping any rework to the four wet&#45;season months
- Recorded the fail&#45;closed persistence refusal as a terminal status instead of losing the batch to it
- Sealed the old generation as an immutable inventory with the producer claim verified against the tracked bytes
- Measured the real per&#45;composite cost and corrected the previous projection
- Measured the post&#45;cutoff queue by a second enumeration instead of inheriting an empty one

## External mutations already made

- No external mutation

## Verification performed

- Backend suite 1830 passed, site suite 203 passed, site worker 44 of 44
- Nine mutations applied in memory to the seasonal regime module and all nine killed by the test naming each
- The finalizer exercised end to end on a synthetic replay directory, which caught a dead reference and a wrong fixture field
- No workerd process left running

## Remaining work

- Decide the ambiguous event&#45;lineage question, which is scientific and belongs to the owner
- Design how a run body reaches the staging bucket, then deposit and reconcile the candidate

## Resume preflight

- Read this checkpoint, then re&#45;read the phase record and the next&#45;session briefing from the default branch before any deposit
- Do not deposit the current candidate: its strong subset is empty because nothing chained, and a deposited release is immutable and cannot be deleted

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260909T184030Z_green-run-deposit-lane.md`. Read it first and revalidate repository and live state. Missing capability: A staging-scoped R2 object identity reachable from a lane, and a lane that runs the run assembler at all. Required activation: Either an operator runs the assembler apply mode with the staging identity, or a reviewed workflow step is added and merged to the default branch so the v2-staging environment will release its identity. Exact target: runs/&lt;run-id&gt;/ in the araripe-v2-staging bucket.

The Phase 4 replay finished locally and its candidate is assembled and validated, but it must NOT be deposited yet. Two things block it. First, the persistence layer refuses ambiguous event lineage by accepted contract and the reviewed-correction mechanism it presupposes was never built, so nothing chains across dates and the candidate strong subset is empty; that is a scientific decision for the project owner and must not be worked around by changing an overlap threshold. Second, no workflow runs the run assembler, and the staging object identity lives only in a protected environment that accepts the default branch. Read the Phase 4B implementation record and the next-session briefing on the default branch first. Do not move any pointer, do not touch production, and do not delete anything.</pre>
