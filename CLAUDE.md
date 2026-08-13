@AGENTS.md

# Claude-specific Cloudflare boundary

Do not accept or use `CLOUDFLARE_API_TOKEN`, a Wrangler login, a global API
key, or any other direct Cloudflare control-plane credential for this project.
For green control-plane work, Claude may only dispatch the reviewed
`cloudflare_green_control.yml` workflow from the trusted default branch and
only with an operation already present in its fixed choice list. The protected
GitHub Environment owns the token; Claude must not try to read it.

Treat every production identifier as read-only until the explicitly approved
Phase 6 cutover. If a task would touch production, change the broker itself,
or require an operation not already allowlisted, stop and use the
`araripe-safe-handoff` skill.

Autonomy follows the risk-based policy in `AGENTS.md`: staging-scoped object
work, manual green workflows with staging-only credentials, read-only checks,
commits, branch pushes, pull requests, and a proven-inert minimal merge
proceed without repeated approval. Anything with production authority or
effect waits for explicit human approval. Never approve your own
`cloudflare-green-control` run and never work around a pending approval,
failure, or refusal.
