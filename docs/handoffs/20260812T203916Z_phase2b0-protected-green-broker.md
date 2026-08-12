# Recoverable handoff — Activate the protected green broker and finish the remaining Package 2B.0 GitHub gates

- Created (UTC): <code>2026-08-12T20:39:16Z</code>
- Status: **BLOCKED — SAFE CHECKPOINT**
- Missing capability: Renewed GitHub CLI authentication and user installation of the protected Cloudflare green credential in GitHub
- Exact target: GitHub Environments v2&#45;staging and cloudflare&#45;green&#45;control in santibravocmcc/Araripe only
- Required activation: The user authenticates GitHub CLI locally, creates the restricted Cloudflare user API credential, and pastes it directly into the protected GitHub Environment without sharing it in chat or local files

## Safety state

- Last atomic step completed: Committed the restricted green broker and owner&#45;review boundaries locally in both repositories
- Canonical pointer changed: false — No release pointer, manifest, ledger, or canonical object was written
- Partial artifact exposed publicly: false — The broker is local and inactive, no branch was pushed, and the staging Worker has no public route
- Legacy/current production changed: false — No production Worker, route, domain, workflow, bucket, object, DNS record, site artifact, or GitHub setting was changed
- Rollback state: No rollback is required because this step produced only local documentation, tests, workflow code, and commits

## Repository state

Captured immediately before the exclusive checkpoint installation. The checkpoint itself is the expected new Git delta: ?? docs/handoffs/20260812T203916Z&#95;phase2b0&#45;protected&#45;green&#45;broker.md.

- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/Araripe</code> — branch <code>claude/phase2b0&#45;green&#45;isolation</code>, commit: 1fb1591763e34f5ad8b71ff12471aa2ff6dfc879, status:

<pre>clean</pre>
- <code>/Users/sbravo/Documents/Projetos/Observatorio&#95;Chapada&#95;do&#95;Araripe/site</code> — branch <code>codex/workspace&#45;consolidation</code>, commit: 49f6af9e8bb721f9bcb3f18770468050e1d71780, status:

<pre>clean</pre>

## Completed

- Implemented a manual default&#45;branch&#45;only Cloudflare green broker with three fixed operations and no arbitrary resource or command inputs
- Added tests and validated the broker fail&#45;closed behavior
- Documented the minimum Cloudflare permission set and protected GitHub Environment setup
- Reinforced the production freeze in shared AGENTS.md, Claude&#45;specific CLAUDE.md, both repositories, and the safe&#45;handoff skill
- Added CODEOWNERS protection for workflows, deployment configuration, broker code, and agent instructions
- Committed backend changes locally and committed site boundary changes locally

## External mutations already made

- Created local commits only; nothing was pushed, merged, deployed, or dispatched
- Previously created green staging bucket and unrouted staging Worker remain unchanged
- No production resource or public artifact was changed

## Verification performed

- Thirty&#45;five focused broker tests passed
- The complete backend suite passed with 387 tests
- Workflow structure and repository diffs were validated
- No credential value was added to repository files
- Both repositories were clean immediately before this checkpoint

## Remaining work

- User renews GitHub CLI authentication without sharing a credential in chat
- User creates the restricted Cloudflare user API credential and installs it only as a protected GitHub Environment secret
- Install and verify the separate R2 identity in GitHub Environment v2&#45;staging without reading or printing secret values
- Review and publish the local branches only after explicit user approval
- Run the broker audit first and request separate approval before disabling the unsafe site branch deploy
- Complete the Package 2B.0 lane distinctness and inertness proofs

## Resume preflight

- Read this checkpoint, ROADMAP.md, the Phase 2B.0 record, the broker operating document, both AGENTS.md and CLAUDE.md files, and the safe&#45;handoff skill
- Confirm GitHub CLI authentication and exact repository authority before any GitHub mutation
- Revalidate both repository branches and commits and stop on an unexpected delta
- Verify only Environment names and variable names, never retrieve or print secret values
- Confirm the staging Worker remains unrouted and production remains unchanged before any broker request
- Do not approve your own Environment request or bypass a refusal with a direct Cloudflare command

## Codex handoff prompt

<pre>Continue the Araripe task from checkpoint `docs/handoffs/20260812T203916Z_phase2b0-protected-green-broker.md`. Read it first and revalidate repository and live state. Missing capability: Renewed GitHub CLI authentication and user installation of the protected Cloudflare green credential in GitHub. Required activation: The user authenticates GitHub CLI locally, creates the restricted Cloudflare user API credential, and pastes it directly into the protected GitHub Environment without sharing it in chat or local files. Exact target: GitHub Environments v2-staging and cloudflare-green-control in santibravocmcc/Araripe only.

Continue Package 2B.0 for the Observatorio da Chapada do Araripe from the newest protected green broker checkpoint. Read that checkpoint first, then the roadmap, Phase 2B.0 record, restricted broker guide, both repositories' AGENTS.md and CLAUDE.md files, and the araripe-safe-handoff skill. The user has renewed GitHub CLI authentication with gh auth login for github.com. Confirm gh auth status and repository authority, then revalidate both repositories and the documented green Cloudflare state before mutation. Never read, print, paste, or store credential values in chat or repository files. Install only the existing separate R2 GitHub identity from local profile araripe-r2-github-staging into GitHub Environment v2-staging by direct non-printing transfer, with the names specified in the Phase 2B.0 record; verify names only. Confirm that the user, not Claude, created and protected Environment cloudflare-green-control and directly installed its restricted Cloudflare credential and documented variables. Do not retrieve that credential, use a direct Cloudflare API command, approve your own deployment request, or broaden an operation. Review the local backend broker commits and site boundary commits, but do not push, merge, dispatch, or modify GitHub or Cloudflare until presenting the exact action and receiving explicit user approval. After approval and protected merge, the first broker run must be audit. Treat disable-site-branch-deploy as a separate mutation requiring separate user approval. Never alter the production Worker, final domain, routes, DNS, araripe-cogs, blue workflows, canonical pointers, or public artifacts. If authentication, protection settings, or live state differs, stop safely and create a new immutable checkpoint with the araripe-safe-handoff skill.</pre>
