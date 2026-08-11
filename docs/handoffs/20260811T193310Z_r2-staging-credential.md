# Recoverable handoff — Complete Package 2B.0 Claude R2 credential acceptance

- Created (UTC): <code>2026-08-11T19:33:10Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: User&#45;created bucket&#45;scoped R2 S3 credential
- Exact target: Private R2 bucket araripe&#45;v2&#45;staging in the recorded Cloudflare account
- Required activation: Create the one&#45;bucket token in the Cloudflare dashboard and configure local AWS profile araripe&#45;r2&#45;staging without sharing its values

## Safety state

- Last atomic step completed: Created and read back the isolated empty staging bucket and completed local contracts, roadmap, decision records, and handoff tests
- Canonical pointer changed: false — No release pointer or canonical object was written
- Partial artifact exposed publicly: false — The staging bucket has no public access, custom domain, CORS policy, or production binding
- Legacy/current production changed: false — No legacy bucket, production Worker, route, DNS record, workflow, site artifact, or scheduled automation was changed
- Rollback state: No production rollback is required; the isolated empty staging bucket may be removed later only through a separately approved action if abandoned

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260811T193310Z&#95;r2&#45;staging&#45;credential.md.

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
?? docs/implementation/PHASE_2B0_2026-08-11.md
?? docs/operations/&lt;opaque-name sha256:1f385a920f6e3929674f8013372d3c88035404b85e92df9b8c3792e27ad73199&gt;
?? tests/&lt;opaque-name sha256:ca038edf99ac1f49635bbf0bb6e03c986dc0523a37076c45351c2ece48a9d0e5&gt;
?? tests/test_safe_handoff_skill.py</pre>
- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/site</code> — branch <code>codex/workspace&#45;consolidation</code>, commit: fea5e598d658fa4a130145d4b0423e43ab7bf7d8, status:

<pre>clean</pre>

## Completed

- Created private additive R2 bucket araripe&#45;v2&#45;staging
- Recorded the Cloudflare and Claude credential boundary
- Updated the roadmap for isolated sequential Packages 2B.0 through 2B.4
- Versioned and adversarially validated the cross&#45;tool safe&#45;handoff skill
- Resolved candidate&#45;generation policy while preserving the Phase 5 validation gate

## External mutations already made

- Created only the empty private bucket araripe&#45;v2&#45;staging
- No production or public resource mutation

## Verification performed

- Confirmed staging bucket public access disabled and no custom domain, CORS, object lock, Worker binding, or uploaded object
- Confirmed production bucket, Worker, routes, DNS, workflows, site, and canonical state were untouched
- Passed focused decision and safe&#45;handoff tests plus independent adversarial review

## Remaining work

- Create an R2 Object Read and Write token scoped only to araripe&#45;v2&#45;staging
- Save it outside the repositories as AWS profile araripe&#45;r2&#45;staging
- Verify list, put, get, and delete only under a unique credential smoke&#45;test key
- Verify the same identity receives AccessDenied for araripe&#45;cogs
- Continue the remaining Package 2B.0 isolation checks before any green workflow activation

## Resume preflight

- Read the checkpoint and current roadmap before acting
- Read back the live staging bucket and confirm it still has no public or production attachment
- Confirm AWS profile araripe&#45;r2&#45;staging exists without reading or printing its credential values
- Run object tests only against the exact staging bucket and never broaden the token
- Stop and create a fresh safe handoff if Cloudflare control&#45;plane or GitHub capability is unavailable

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260811T193310Z_r2-staging-credential.md`. Read it first and revalidate repository and live state. Missing capability: User-created bucket-scoped R2 S3 credential. Required activation: Create the one-bucket token in the Cloudflare dashboard and configure local AWS profile araripe-r2-staging without sharing its values. Exact target: Private R2 bucket araripe-v2-staging in the recorded Cloudflare account.

Continue Package 2B.0 from this checkpoint after I have created the bucket-scoped R2 token and local AWS profile. Do not read, print, rotate, or copy credential values. Revalidate both repositories and the live bucket first. Test the profile only against araripe-v2-staging, prove AccessDenied against araripe-cogs, remove only the unique smoke-test object, update the implementation record with sanitized evidence, and make no production workflow, Worker, route, DNS, site, or canonical-pointer change.</pre>
