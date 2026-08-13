# Concurrency lanes for the blue/green transition

**Defined:** 2026-08-11 (Package 2B.0)

Package 2B.0 separates automation into three concurrency lanes so that green
candidate work and future staging-pointer promotion can never race, cancel, or
block the blue production schedules. Package 2B.1 builds its workflow
coordination on these lanes.

## Lane 1 — legacy live mutation (blue)

- Members: `detect_gee.yml` (cron Mon/Thu 06:00 UTC + manual),
  `update_data.yml` (manual fallback) in this repository, and the site
  repository's `update-data.yml` (cron Mon/Thu 07:30 UTC + manual).
- Concurrency key: none declared. GitHub's implicit isolation applies —
  concurrent runs of the same workflow are possible, exactly as today.
- Policy: these files, their schedules, secrets (`R2_ACCESS_KEY`,
  `R2_SECRET_KEY`, `GEE_SA_KEY`, …), bot-push behavior, and implicit
  concurrency remain **unchanged through Phases 2B–5**. The blue lane is the
  production fallback until the Phase 6 cutover.

## Lane 2 — green candidate/replay

- Members: `v2_candidate_replay.yml` and future v2 candidate workflows.
- Concurrency key: `araripe-green-candidate`, `cancel-in-progress: false` so
  long replays queue instead of killing each other.
- Authority: GitHub Environment `v2-staging` only — a bucket-scoped R2 identity
  for `araripe-v2-staging` with object permissions and nothing else. No
  production secret name is referenced in this lane.
- Writes: immutable per-run prefixes only (`green-isolation-proof/run-<id>/`,
  later `runs/<run-id>/…`); no deletes, no overwrites, no pointers.

## Lane 3 — serialized green staging-pointer promotion

- Members: `v2_promotion_lane.yml` (placeholder until the Package 2B.2
  publication contract).
- Concurrency key: `araripe-green-promotion`, `cancel-in-progress: false`.
  GitHub serializes this group to at most one running plus one queued run,
  which is the single serialized lock required by the roadmap.
- Authority: none in the placeholder. Real promotion will use a separate
  protected identity — never the candidate identity, never Claude's local
  credential — and still only moves the isolated green/staging pointer before
  Phase 6.

## Distinctness argument and proof

The three lanes share no concurrency group: the green groups use explicit
names (`araripe-green-candidate`, `araripe-green-promotion`) that no legacy
workflow declares, and GitHub scopes implicit (undeclared) concurrency to each
individual workflow file. Cross-lane queueing is therefore impossible by
construction.

Runnable proof after the v2 workflows reach the default branch through a
reviewed merge: dispatch two promotion runs with `hold_seconds > 0` while one
candidate run is active and a legacy manual run executes. Expected result: the
promotion runs serialize against each other only; candidate and legacy runs
proceed unaffected. Record the four run URLs in the Package 2B.0 gate note.

## Inertness of the v2 route

Both v2 workflows trigger on `workflow_dispatch` only, carry
`permissions: contents: read`, and guard on the repository name. They cannot
inherit the blue cron, cannot push commits, and reference no production
credential. Even a premature manual dispatch fails closed while the
`v2-staging` environment is absent, because the bucket/endpoint guards reject
missing variables before any object operation.
