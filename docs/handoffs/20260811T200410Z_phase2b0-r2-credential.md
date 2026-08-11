# Recoverable handoff — Resume Package 2B.0 after the accepted roadmap and candidate&#45;policy update

- Created (UTC): <code>2026-08-11T20:04:10Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: User&#45;created R2 S3 Object Read and Write credential limited to araripe&#45;v2&#45;staging
- Exact target: Object&#45;only access to private bucket araripe&#45;v2&#45;staging with no production authority
- Required activation: Create the bucket&#45;limited R2 access key in Cloudflare and save it in AWS profile araripe&#45;r2&#45;staging outside both repositories

## Safety state

- Last atomic step completed: Roadmap, candidate policy, credential guide, and handoff skill passed final local review
- Canonical pointer changed: false — No release pointer operation was attempted
- Partial artifact exposed publicly: false — The staging bucket has no public access, route, custom domain, or published object
- Legacy/current production changed: false — No existing bucket, production Worker, route, DNS record, workflow, schedule, site artifact, or canonical state was changed
- Rollback state: No rollback is required; the only live addition is an empty isolated private staging bucket

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260811T200410Z&#95;phase2b0&#45;r2&#45;credential.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>codex/technical&#45;review&#45;roadmap</code>, commit: b27126a73a22ad7d6cfbddfb3887b4e3cfb34de3, status:

<pre>M .gitignore
 M AGENTS.md
 M ROADMAP.md
 M docs/contracts/phase1/&lt;opaque-name sha256:8b1198ade7bea54e309e5e2339ad5cca95c0d157392a4a86359fa983e35e0127&gt;
 M docs/contracts/phase1/&lt;opaque-name sha256:58a06ebddb8357162d0f57462b4fe37c2981fe6bfc06b7587461b0ab7204e6ba&gt;
 M docs/contracts/phase1/examples/&lt;opaque-name sha256:5ec2e92407ac9ce7a747d336deb3750a6401e8f003beeba1ad13069f0ece0cd8&gt;
 M docs/implementation/PHASE_2A4_2026-08-03.md
 M docs/implementation/PHASE_2A5_2026-08-09.md
?? .agents/skills/araripe-safe-handoff/SKILL.md
?? .agents/skills/araripe-safe-handoff/agents/openai.yaml
?? .agents/skills/araripe-safe-handoff/references/handoff-input.example.json
?? .agents/skills/araripe-safe-handoff/references/handoff-template.md
?? .agents/skills/araripe-safe-handoff/scripts/create_handoff.py
?? .claude/skills/araripe-safe-handoff/SKILL.md
?? config/&lt;opaque-name sha256:1c8e0038146a164625baa02a3b5b8e1ba2721f3cc4af3f586e7822824b464710&gt;
?? docs/contracts/phase2a/schemas/&lt;opaque-name sha256:c0ba5f8d4ecedb8f0c07a89e0f4fbf897ecb3436945579c7eff45ad503ecc614&gt;
?? docs/decisions/&lt;opaque-name sha256:61df735363527a9c16203d2091d2e52e83d148c075d7b03000a88d93739e69c3&gt;
?? docs/handoffs/&lt;opaque-name sha256:b2456acb945d891fe46ead6de421fe1de6e28fa03708397e33da1dcc83487d6e&gt;
?? docs/implementation/PHASE_2B0_2026-08-11.md
?? docs/operations/&lt;opaque-name sha256:1f385a920f6e3929674f8013372d3c88035404b85e92df9b8c3792e27ad73199&gt;
?? tests/&lt;opaque-name sha256:ca038edf99ac1f49635bbf0bb6e03c986dc0523a37076c45351c2ece48a9d0e5&gt;
?? tests/test_safe_handoff_skill.py</pre>
- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/site</code> — branch <code>codex/workspace&#45;consolidation</code>, commit: fea5e598d658fa4a130145d4b0423e43ab7bf7d8, status:

<pre>clean</pre>

## Completed

- Created and read back the private additive bucket araripe&#45;v2&#45;staging
- Installed and verified AWS CLI v2 locally without creating a credential profile
- Resolved the Phase 2A candidate&#45;generation policy and coherent v2 identity family
- Updated Roadmap version 1.2 with sequential green isolation and Phase 6 production cutover
- Versioned and forward&#45;tested the shared araripe&#45;safe&#45;handoff skill for Codex and Claude
- Added local Claude deny&#45;read guards without changing existing allow rules

## External mutations already made

- Created only the empty private R2 bucket araripe&#45;v2&#45;staging in the existing Cloudflare account
- Installed AWS CLI v2 through Homebrew
- Changed only scoped backend repository planning, policy, provenance, skill, test, and handoff files

## Verification performed

- Live Cloudflare read&#45;back confirmed the staging bucket identity and private additive role
- Focused candidate&#45;policy and handoff tests passed
- Full backend suite passed with 381 tests
- Phase 1 contract validator and skill structural validator passed
- JSON, diff, secret&#45;shape, ignore&#45;boundary, and site&#45;repository checks passed
- Independent roadmap and credential audits returned PASS

## Remaining work

- User creates the exact one&#45;bucket R2 credential and stores it in AWS profile araripe&#45;r2&#45;staging
- Verify list, put, get, and delete only in araripe&#45;v2&#45;staging and verify AccessDenied for araripe&#45;cogs
- Re&#45;audit Worker Builds branch behavior and create a staging Worker with no production route
- Create a separate GitHub v2&#45;staging Environment and bucket&#45;only Actions identity
- Introduce inert manual v2 workflows and prove three separate concurrency lanes
- Record the accepted live before&#45;state and close the Package 2B.0 gate

## Resume preflight

- Read this checkpoint, Roadmap, Phase 2B.0 record, and the staging credential guide
- Revalidate both repository branches, commits, and dirty state
- Read back the staging bucket and confirm all production resources remain unchanged
- Confirm the AWS profile exists without reading or printing its credential values
- Load araripe&#45;safe&#45;handoff before any external operation

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260811T200410Z_phase2b0-r2-credential.md`. Read it first and revalidate repository and live state. Missing capability: User-created R2 S3 Object Read and Write credential limited to araripe-v2-staging. Required activation: Create the bucket-limited R2 access key in Cloudflare and save it in AWS profile araripe-r2-staging outside both repositories. Exact target: Object-only access to private bucket araripe-v2-staging with no production authority.

Continue only Package 2B.0 for the Observatorio da Chapada do Araripe. Read the newest phase2b0-r2-credential checkpoint, Roadmap, Phase 2B.0 record, credential guide, repository instructions, and araripe-safe-handoff skill. Revalidate both repositories and live Cloudflare state first. Confirm that AWS profile araripe-r2-staging exists without printing secrets. Test object list, put, get, and delete only in araripe-v2-staging and require AccessDenied for araripe-cogs. Then continue only the remaining green isolation checks: Worker Builds audit, a staging Worker without production route, a separate GitHub v2-staging identity, inert manual v2 workflows, and distinct concurrency lanes. Do not change production workflows, buckets, Worker, routes, DNS, site artifacts, or canonical pointers. If any capability is missing, stop safely and create a new immutable handoff checkpoint.</pre>
