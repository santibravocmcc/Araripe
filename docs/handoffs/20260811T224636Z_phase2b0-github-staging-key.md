# Recoverable handoff — Complete Package 2B.0 after the isolated Cloudflare Worker was created

- Created (UTC): <code>2026-08-11T22:46:36Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: A second R2 Object Read and Write credential scoped only to araripe&#45;v2&#45;staging for the GitHub Actions identity, plus user approval before changing the existing non&#45;production Worker Builds trigger or merging the workflow branch
- Exact target: GitHub Environment v2&#45;staging, a staging&#45;only site deploy path to observatorio&#45;chapada&#45;v2&#45;staging, and post&#45;merge green lane proofs
- Required activation: The user creates the separate Cloudflare R2 key, stores it outside the repositories as AWS profile araripe&#45;r2&#45;github&#45;staging without pasting it into chat, and confirms approval for the reviewed trigger change and later branch merge

## Safety state

- Last atomic step completed: Recorded the live Cloudflare audit and isolated staging Worker in local commit 6fd66bf
- Canonical pointer changed: false — No release pointer, manifest, ledger, or canonical object was read or written
- Partial artifact exposed publicly: false — The staging Worker has workers.dev and previews disabled and has no custom domain, zone route, schedule, or site assets
- Legacy/current production changed: false — The production Worker, custom domain, Worker Builds triggers, routes, DNS, blue workflows, araripe&#45;cogs, site artifacts, and production bindings were not changed
- Rollback state: No rollback is required because the additive staging Worker passed isolation read&#45;back; deleting only observatorio&#45;chapada&#45;v2&#45;staging would fully reverse the live addition if later approved

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260811T224636Z&#95;phase2b0&#45;github&#45;staging&#45;key.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>claude/phase2b0&#45;green&#45;isolation</code>, commit: 6fd66bfd5b1fa7dd6fc0d5c081fda617b22b6dc0, status:

<pre>clean</pre>
- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/site</code> — branch <code>codex/workspace&#45;consolidation</code>, commit: fea5e598d658fa4a130145d4b0423e43ab7bf7d8, status:

<pre>clean</pre>

## Completed

- Revalidated both repository branches and the prior immutable checkpoint
- Read back the private staging bucket and production Worker state without exposing credentials
- Proved that the existing wildcard non&#45;production Worker Builds trigger runs npx wrangler deploy and is unsafe for candidate site pushes
- Created observatorio&#45;chapada&#45;v2&#45;staging with only the araripe&#45;v2&#45;staging R2 binding and distinct rate&#45;limit namespace 2001
- Verified the staging Worker has no public subdomain, preview URL, custom domain, zone route, schedule, asset bundle, AI binding, or secret
- Committed the roadmap, Phase 2B.0 record, and Cloudflare green before&#45;state as local commit 6fd66bf

## External mutations already made

- Created the additive Worker observatorio&#45;chapada&#45;v2&#45;staging in the approved Cloudflare account
- Created local documentation commit 6fd66bf on branch claude/phase2b0&#45;green&#45;isolation
- No object, public route, production resource, GitHub setting, push, merge, or deployment to the final domain was changed

## Verification performed

- Staging Worker settings show R2 bucket araripe&#45;v2&#45;staging and rate&#45;limit namespace 2001 only
- Staging Worker workers.dev and previews are disabled; schedules and zone routes are empty
- The final public domain remains attached only to production Worker observatorio&#45;chapada
- Production rate&#45;limit namespace remains 1001 and production Worker metadata remained unchanged
- Worker Builds still watches main separately and every non&#45;main branch with the unsafe full deploy command; no site branch was pushed
- Git diff checks passed and no secret value was found in the new records

## Remaining work

- User creates a separate R2 Object Read and Write key scoped only to araripe&#45;v2&#45;staging and stores it as local AWS profile araripe&#45;r2&#45;github&#45;staging
- Install GitHub Environment v2&#45;staging with separate staging secrets and approved bucket, endpoint, and region variables without exposing secret values
- Prepare and review a site staging configuration that can target only observatorio&#45;chapada&#45;v2&#45;staging with bucket araripe&#45;v2&#45;staging and rate&#45;limit namespace 2001
- Obtain user approval before changing the existing non&#45;production Worker Builds trigger or pushing a site candidate branch
- Review and merge the local backend workflow branch only after user approval, then run and record the lane distinctness and inertness proofs
- Record the accepted final before&#45;state and close Package 2B.0 only after every gate passes

## Resume preflight

- Read this checkpoint, ROADMAP.md, the Phase 2B.0 implementation record, the concurrency&#45;lanes record, and the Cloudflare green before&#45;state record
- Confirm backend branch claude/phase2b0&#45;green&#45;isolation contains local commit 6fd66bf plus only this expected checkpoint delta and confirm the site repository remains clean
- Read back staging Worker bindings, subdomain, domains, routes, and schedules and stop if they differ
- Confirm the second local AWS profile exists and its credentials file remains mode 600 without reading or printing either value
- Confirm explicit user approval before changing the Worker Builds trigger, pushing a site branch, or merging the backend workflow branch

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260811T224636Z_phase2b0-github-staging-key.md`. Read it first and revalidate repository and live state. Missing capability: A second R2 Object Read and Write credential scoped only to araripe-v2-staging for the GitHub Actions identity, plus user approval before changing the existing non-production Worker Builds trigger or merging the workflow branch. Required activation: The user creates the separate Cloudflare R2 key, stores it outside the repositories as AWS profile araripe-r2-github-staging without pasting it into chat, and confirms approval for the reviewed trigger change and later branch merge. Exact target: GitHub Environment v2-staging, a staging-only site deploy path to observatorio-chapada-v2-staging, and post-merge green lane proofs.

Continue only Package 2B.0 from this newest immutable checkpoint. Revalidate both repositories and all recorded Cloudflare resources first. The user must have created a second R2 Object Read and Write key scoped only to araripe-v2-staging and stored it outside the repositories as AWS profile araripe-r2-github-staging; never print or read its values into the transcript. Install GitHub Environment v2-staging with R2_STAGING_ACCESS_KEY_ID and R2_STAGING_SECRET_ACCESS_KEY as environment secrets and R2_STAGING_BUCKET, R2_ENDPOINT_URL, and AWS_REGION as environment variables, piping secret values directly from the local profile rather than exposing them. Prepare a site staging configuration that targets only observatorio-chapada-v2-staging, araripe-v2-staging, and rate-limit namespace 2001. Do not change the existing wildcard non-production Worker Builds trigger, push a site candidate branch, or merge the backend workflow branch until the user explicitly approves those reviewed changes. Production Worker observatorio-chapada, its final domain, blue workflows, araripe-cogs, routes, DNS, site artifacts, and canonical pointers must remain untouched. After approval, install the safe staging-only trigger command, review and merge the inert backend workflows, run the documented lane and inertness proofs, record the accepted before-state, and close Package 2B.0 only if every gate passes. If any capability is missing or live state differs, stop safely and create another immutable checkpoint with the araripe-safe-handoff skill.</pre>
