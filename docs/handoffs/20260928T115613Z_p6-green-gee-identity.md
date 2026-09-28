# Recoverable handoff — Build the green deposit lane that runs detection in CI and deposits a run prefix in the staging bucket

- Created (UTC): <code>2026-09-28T11:56:13Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: A green Earth Engine service identity held in the v2&#45;staging environment; the only identity that exists is the blue production one
- Exact target: Earth Engine project ee&#45;araripe, computation and pixel download only, no asset writes
- Required activation: The owner creates a compute&#45;only service account in ee&#45;araripe and stores its key as a new secret of the v2&#45;staging environment, following the green identity setup guide in the operations docs

## Safety state

- Last atomic step completed: The four design answers were written and the next briefing prepared; no workflow, upload or probe was created
- Canonical pointer changed: false — No pointer read or write was attempted; the green pointer stays at sequence 14
- Partial artifact exposed publicly: false — Nothing was written to any bucket; only read&#45;only listings of the staging bucket were made
- Legacy/current production changed: false — No workflow was dispatched, the blue key was never called, and no Google API or IAM setting was changed
- Rollback state: No rollback required because no external mutation occurred

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260928T115613Z&#95;p6&#45;green&#45;gee&#45;identity.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>claude/p6&#45;deposit&#45;lane&#45;design</code>, commit: 31b76fc7aad5eaa9a79cc00bdc1f9f518f6aea4c, status:

<pre>M scripts/assemble_green_run.py
?? docs/implementation/PHASE_6E_2026-09-28.md
?? docs/operations/GEE_GREEN_IDENTITY_SETUP.md
?? docs/operations/&lt;opaque-name sha256:b2e2a5754f7f483c6f6c799c0b817e520fe9fec9497dc17bdcd810f0016e71c5&gt;</pre>

## Completed

- Answered the four design questions in the Phase 6E implementation record
- Measured that the blue key is a repository secret with a documented asset&#45;writer role, and that the project IAM policy is unreadable because its APIs are disabled
- Measured that baseline 2.1.0 exists only locally and that the persistence state is recorded only as a hash
- Wrote the owner setup guide and the next&#45;session briefing
- Corrected the stale ledger&#45;producer statement in the assembler docstring

## External mutations already made

- No external mutation

## Verification performed

- Backend suite 2119 at base and 2124 on the branch
- Focused assembler and pre&#45;cutover checklist tests pass, so the revocation guard still holds

## Remaining work

- Owner creates the green Earth Engine identity
- Probe the identity with both polarities, upload baseline 2.1.0 to staging, build the two&#45;job lane, and prove one real deposit from main without promotion

## Resume preflight

- Read this checkpoint and the Phase 6E record from the default branch, then confirm the new green Earth Engine secret is listed in the v2&#45;staging environment before writing any code

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260928T115613Z_p6-green-gee-identity.md`. Read it first and revalidate repository and live state. Missing capability: A green Earth Engine service identity held in the v2-staging environment; the only identity that exists is the blue production one. Required activation: The owner creates a compute-only service account in ee-araripe and stores its key as a new secret of the v2-staging environment, following the green identity setup guide in the operations docs. Exact target: Earth Engine project ee-araripe, computation and pixel download only, no asset writes.

Resume the Araripe green deposit lane from this checkpoint and the deposit lane build briefing on the default branch. Do not start unless the v2-staging environment lists the new green Earth Engine secret. Never use the blue repository Earth Engine key, which is the production identity. Probe the new identity first and require that asset creation is refused. Upload baseline 2.1.0 to the staging bucket only after the probe passes. Do not move any pointer, do not touch production, and do not delete anything.</pre>
