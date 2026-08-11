# Recoverable handoff — Install the verified staging identity in GitHub Environment v2&#45;staging

- Created (UTC): <code>2026-08-11T22:56:10Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: Valid local GitHub CLI authentication with permission to manage repository Environments, secrets, and variables
- Exact target: GitHub repository santibravocmcc/Araripe Environment v2&#45;staging only
- Required activation: The user runs gh auth login for github.com locally and completes authentication without sharing any token in chat

## Safety state

- Last atomic step completed: Committed the verified region correction and GitHub staging credential gate as e774fa5
- Canonical pointer changed: false — No release pointer, manifest, ledger, or canonical object was read or written
- Partial artifact exposed publicly: false — The staging Worker remains unrouted and no workflow, branch, site artifact, or release was published
- Legacy/current production changed: false — No production Worker, route, domain, workflow, bucket, object, DNS record, or GitHub setting was changed
- Rollback state: No rollback is required; only local non&#45;secret profile region fields and documentation changed in this resume

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260811T225610Z&#95;phase2b0&#45;github&#45;auth.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>claude/phase2b0&#45;green&#45;isolation</code>, commit: e774fa50772da5eb8ea6acb54e96d7649ff85397, status:

<pre>clean</pre>
- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/site</code> — branch <code>codex/workspace&#45;consolidation</code>, commit: fea5e598d658fa4a130145d4b0423e43ab7bf7d8, status:

<pre>clean</pre>

## Completed

- Confirmed both local R2 profiles exist and the credentials file remains mode 600 without reading secret values
- Corrected the default region of both profiles from the R2 endpoint URL to auto while preserving their keys
- Verified the GitHub Actions R2 identity can list araripe&#45;v2&#45;staging
- Verified the same identity receives AccessDenied on araripe&#45;cogs
- Confirmed the local GitHub CLI authentication is expired before attempting any GitHub mutation
- Recorded the result in local commit e774fa5

## External mutations already made

- Set the non&#45;secret region field to auto in profiles araripe&#45;r2&#45;staging and araripe&#45;r2&#45;github&#45;staging
- Created local documentation commit e774fa5
- No R2 object, GitHub setting, Cloudflare control&#45;plane resource, production resource, push, merge, or public artifact was changed

## Verification performed

- Both profile region reads return auto and the credentials file mode remains 600
- Staging list authentication succeeded with the separate GitHub identity
- Production list returned AccessDenied with the separate GitHub identity
- GitHub CLI reports its active account token invalid
- Backend and site repositories were clean before this checkpoint

## Remaining work

- User renews local GitHub CLI authentication with gh auth login for github.com
- Revalidate repository and Cloudflare state and confirm gh access before mutation
- Create GitHub Environment v2&#45;staging and install both secret values by direct pipe from local profile araripe&#45;r2&#45;github&#45;staging
- Install non&#45;secret environment variables for bucket araripe&#45;v2&#45;staging, the approved endpoint, and region auto
- Prepare the local site staging configuration and request explicit approval before changing Worker Builds, pushing the site branch, or merging backend workflows

## Resume preflight

- Read this checkpoint and the current Package 2B.0 implementation record
- Confirm backend branch claude/phase2b0&#45;green&#45;isolation contains e774fa5 plus only this expected checkpoint delta and the site repository remains clean
- Run gh auth status and stop if authentication or repository authority is absent
- Confirm the second R2 profile still has region auto and mode 600 without printing its values
- Read back the isolated staging Worker and stop if any route, domain, schedule, or binding differs

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260811T225610Z_phase2b0-github-auth.md`. Read it first and revalidate repository and live state. Missing capability: Valid local GitHub CLI authentication with permission to manage repository Environments, secrets, and variables. Required activation: The user runs gh auth login for github.com locally and completes authentication without sharing any token in chat. Exact target: GitHub repository santibravocmcc/Araripe Environment v2-staging only.

Continue only Package 2B.0 from this newest checkpoint after the user has renewed GitHub CLI authentication with gh auth login for github.com. Revalidate both repositories, gh access, both non-secret profile regions, and the isolated Cloudflare staging Worker first. Never read, print, or paste the R2 credential values. Create only GitHub Environment v2-staging in santibravocmcc/Araripe. Pipe the access key ID and secret access key directly from local profile araripe-r2-github-staging into Environment secrets R2_STAGING_ACCESS_KEY_ID and R2_STAGING_SECRET_ACCESS_KEY, and set Environment variables R2_STAGING_BUCKET to araripe-v2-staging, R2_ENDPOINT_URL to the approved account endpoint, and AWS_REGION to auto. Verify secret names and variables without retrieving secret values. Do not change Worker Builds, push either repository, merge a branch, dispatch a workflow, publish an object, or touch production. Then prepare the local site staging configuration and present the exact trigger and merge changes for explicit user approval. If authentication is still unavailable or state differs, stop safely and create another immutable checkpoint with the araripe-safe-handoff skill.</pre>
