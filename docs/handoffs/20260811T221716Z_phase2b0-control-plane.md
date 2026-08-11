# Recoverable handoff — Complete Package 2B.0 green isolation after staging credential verification

- Created (UTC): <code>2026-08-11T22:17:16Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: Cloudflare control&#45;plane connection for the Worker Builds audit and staging Worker, plus a second user&#45;created bucket&#45;scoped R2 Actions key
- Exact target: Worker Builds branch behavior, a staging Worker with no production route, and GitHub Environment v2&#45;staging limited to araripe&#45;v2&#45;staging
- Required activation: Resume in Codex with its connected Cloudflare capability; the user creates one more Object Read and Write key for araripe&#45;v2&#45;staging to serve as the separate GitHub Actions identity

## Safety state

- Last atomic step completed: Committed the verified credential results and inert v2 lane drafts as commit d804b68 on the local review branch claude/phase2b0&#45;green&#45;isolation
- Canonical pointer changed: false — No release pointer, ledger, manifest, or canonical object was read or written in any bucket
- Partial artifact exposed publicly: false — The staging bucket stays private and was left empty; nothing was pushed, merged, deployed, routed, or published
- Legacy/current production changed: false — Only staging object operations ran; the production bucket list was denied and the production site answered HTTP 200 unchanged
- Rollback state: No rollback needed; the smoke object was deleted, the bucket is empty, and the local branch can be dropped without external effect

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260811T221716Z&#95;phase2b0&#45;control&#45;plane.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>claude/phase2b0&#45;green&#45;isolation</code>, commit: d804b6816d2830c091b6075354d095494fff5f0d, status:

<pre>clean</pre>
- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/site</code> — branch <code>codex/workspace&#45;consolidation</code>, commit: fea5e598d658fa4a130145d4b0423e43ab7bf7d8, status:

<pre>clean</pre>

## Completed

- Revalidated both repositories: the previous dirty checkpoint state is now commit 4e2e9ee on the Araripe candidate branch and the site repository is unchanged and clean
- Confirmed AWS CLI v2 and profile araripe&#45;r2&#45;staging exist with a mode 600 credentials file without printing any value
- Passed the staging acceptance test: list, put, get, checksum match, and delete succeeded only in araripe&#45;v2&#45;staging under a unique credential&#45;smoke&#45;test prefix and the bucket was left empty
- Confirmed AccessDenied when listing araripe&#45;cogs with the staging profile
- Created the local review branch claude/phase2b0&#45;green&#45;isolation from commit 4e2e9ee
- Added inert dispatch&#45;only v2 workflows v2&#95;candidate&#95;replay.yml and v2&#95;promotion&#95;lane.yml with read&#45;only permissions, fork guard, environment gating, and fail&#45;closed bucket and endpoint checks
- Defined the legacy&#45;live, green&#45;candidate, and serialized&#45;promotion concurrency lanes in GREEN&#95;CONCURRENCY&#95;LANES.md
- Updated ROADMAP.md and PHASE&#95;2B0&#95;2026&#45;08&#45;11.md with the verification results and the open control&#45;plane items

## External mutations already made

- Uploaded and deleted one small probe object under a unique credential&#45;smoke&#45;test prefix in araripe&#45;v2&#45;staging, leaving the bucket empty
- No other external mutation: nothing pushed to GitHub and no Cloudflare control&#45;plane operation attempted

## Verification performed

- Staging object list, put, get, and delete succeeded with a SHA&#45;256 round&#45;trip match and a final empty recursive listing
- Production bucket araripe&#45;cogs returned AccessDenied for ListObjectsV2 with the staging profile
- Read&#45;only HEAD of the production apex domain returned HTTP 200 through Cloudflare
- Wrangler is unauthenticated and the Cloudflare connectors are unauthorized in this session, so no control&#45;plane path exists for Claude
- Both v2 workflows parse as dispatch&#45;only with contents read, cancel&#45;in&#45;progress false, and distinct green concurrency groups
- Full backend gate passed with 381 tests after the changes

## Remaining work

- Re&#45;audit Cloudflare Worker Builds branch behavior for the site repository before any candidate branch push
- Create the staging Worker or environment with no apex or custom route and its own binding and rate&#45;limit namespace
- User creates a second bucket&#45;scoped R2 key; install GitHub Environment v2&#45;staging with its two staging secrets and the bucket, endpoint, and region variables in one step
- Review the local branch claude/phase2b0&#45;green&#45;isolation, merge it only after approval, and run the post&#45;merge lane distinctness and inertness proofs
- Record the accepted live before&#45;state and close the Package 2B.0 gate

## Resume preflight

- Read this checkpoint, ROADMAP.md, PHASE&#95;2B0&#95;2026&#45;08&#45;11.md, GREEN&#95;CONCURRENCY&#95;LANES.md, and the staging credential guide in docs/operations
- Revalidate both repository branches, commits, and clean state, including the local branch claude/phase2b0&#45;green&#45;isolation at commit d804b68
- Read back araripe&#45;v2&#45;staging expecting an empty bucket or only immutable green&#45;isolation&#45;proof prefixes and confirm production resources unchanged
- Classify each step with the safe&#45;handoff skill and touch only the exact staging targets with the connected Cloudflare capability

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260811T221716Z_phase2b0-control-plane.md`. Read it first and revalidate repository and live state. Missing capability: Cloudflare control-plane connection for the Worker Builds audit and staging Worker, plus a second user-created bucket-scoped R2 Actions key. Required activation: Resume in Codex with its connected Cloudflare capability; the user creates one more Object Read and Write key for araripe-v2-staging to serve as the separate GitHub Actions identity. Exact target: Worker Builds branch behavior, a staging Worker with no production route, and GitHub Environment v2-staging limited to araripe-v2-staging.

Continue only Package 2B.0 for the Observatorio da Chapada do Araripe. Read the newest phase2b0-control-plane checkpoint, ROADMAP.md, PHASE_2B0_2026-08-11.md, GREEN_CONCURRENCY_LANES.md, the staging credential guide, repository AGENTS.md files, and the araripe-safe-handoff skill. Revalidate both repositories and live Cloudflare state first, including the local review branch claude/phase2b0-green-isolation at commit d804b68 with the inert v2 workflows.

Claude already proved that object list, put, get, and delete succeed in araripe-v2-staging with the bucket-scoped profile and that araripe-cogs is denied. Do not repeat put or delete attempts against production. Continue the remaining green isolation checks in order: re-audit Cloudflare Worker Builds branch behavior for the site repository before any candidate branch push; create a staging Worker or environment with no apex or custom route and its own binding and rate-limit namespace; after the user creates a second bucket-scoped R2 key, install GitHub Environment v2-staging with its two staging secrets and the bucket, endpoint, and region variables in one step; review and merge the local v2 workflow branch only after approval; then run the post-merge lane distinctness and inertness proofs and record the accepted before-state to close the 2B.0 gate.

Do not change production workflows, buckets, the production Worker, routes, DNS, site artifacts, or canonical pointers. Keep the blue schedules untouched. If any capability is missing, stop safely and create a new immutable handoff checkpoint with the araripe-safe-handoff skill.</pre>
