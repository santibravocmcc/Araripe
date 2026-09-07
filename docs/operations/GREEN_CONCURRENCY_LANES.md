# Concurrency lanes for the blue/green transition

**Defined:** 2026-08-11 (Package 2B.0)

Package 2B.0 separates automation into three concurrency lanes so that green
candidate work and future staging-pointer promotion can never race, cancel, or
block the blue production schedules. Package 2B.1 builds its workflow
coordination on these lanes.

## Lane 1 — legacy live mutation (blue)

- Members: `detect_gee.yml` (cron Mon/Thu 06:00 UTC + manual) and
  `update_data.yml` (manual fallback) in this repository. The site
  repository's `update-data.yml` is a separate lane in a separate repository
  (see "The site lane" below).
- Concurrency key: **`araripe-legacy-state`, `cancel-in-progress: false`**,
  shared by both members.
- Policy: these files, their schedules, secrets (`R2_ACCESS_KEY`,
  `R2_SECRET_KEY`, `GEE_SA_KEY`, …) and bot-push behavior remain **unchanged
  through Phases 2B–5**. The blue lane is the production fallback until the
  Phase 6 cutover.

### Why Lane 1 now declares a group (Package 2B.1)

Package 2B.0 recorded "concurrency key: none declared … implicit concurrency
remains unchanged". Package 2B.1's roadmap bullet — separate green and legacy
lanes — supersedes that specific sentence, deliberately and for a safety
reason; every other Lane 1 guarantee above is untouched.

Both members read-modify-write the **same** R2 object
(`persistence_state.geojson`), and detection is **not idempotent**: a second
overlapping run inflates `n_sightings` for every track it re-observes. With no
key declared, GitHub scopes implicit concurrency to each workflow *file*, so a
manual `update_data.yml` dispatch during a scheduled `detect_gee.yml` run — or
a re-run started before the first finished — could interleave their read and
write of that object and corrupt the counters.

Hence **one** group covering both files rather than one group each: two
separate keys would serialize each file against itself and still allow exactly
the cross-file interleaving that matters.

`cancel-in-progress: false` because cancelling mid-run is the dangerous
direction: alerts are uploaded to R2 before the state is, so a killed run can
leave published alerts whose track updates never landed.

Queue semantics worth knowing: GitHub holds at most one running plus one
pending run per group and cancels any *earlier* pending run when a newer one
arrives. A third concurrent trigger is therefore dropped rather than queued.
That is acceptable here — `SEARCH_DAYS_BACK = 16` (`config/settings.py`) means
the next scheduled run re-covers the dropped run's window, so a missed cycle
self-heals, exactly as it did for the 2026-08-17 incident.

## The site lane (separate repository)

Concurrency groups are per repository, so the site's `update-data.yml` cannot
share `araripe-legacy-state`. It carries its own group and does not touch the
persistence state; it consumes the backend's published products. Package 2B.1
replaced the fixed clock offset between the two repositories with a validated
release signal (`data/timeseries/RELEASE.json`) — see `ROADMAP.md` §6.

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

- Members: `v2_promotion_lane.yml`.
- Concurrency key: `araripe-green-promotion`, `cancel-in-progress: false`.
  GitHub serializes this group to at most one running plus one queued run,
  which is the single serialized lock required by the roadmap.
- Authority: **still none.** Real promotion needs a separate protected
  identity — never the candidate identity, never Claude's local credential —
  and that Environment does not exist yet, because creating one is a
  repository configuration change.

### What Package 2B.2B put in the placeholder

The publication contract now exists
(`docs/contracts/phase2b/GREEN_RELEASE_CONTRACT_V1.md`), so the lane runs
every part of promotion that needs no credential and stops where authority
begins:

- `contract-check` (default) verifies the pinned ledger contract and runs the
  completeness gate against the producer's own fixture;
- `plan` builds and validates a whole green release from a ledger committed in
  this repository — identity, schemas, checksums, expected dates, state
  watermark, product completeness, zero-alert classification — and contacts no
  object store;
- `promote` and `rollback` **stop and name the missing capability**, per the
  Package 2B.0 handoff rule, rather than substituting a broader credential;
- `lane-proof` is the original Package 2B.0 behaviour, preserved so the
  outstanding four-concurrent-run proof can still be run.

The lane still declares **no `environment:` and references no secret**, so it
carries no authority at all and stays dispatchable from any ref.
`environment: v2-staging` would not help even as a stopgap: its identity is
the candidate identity, which this lane must never use, and its deployment
branch policy admits only `main`. `tests/test_promotion_lane.py` pins each of
those properties, including that no mode reachable from the file performs an
object operation.

## Distinctness argument and proof

The three lanes share no concurrency group: the green groups use explicit
names (`araripe-green-candidate`, `araripe-green-promotion`) that no legacy
workflow declares, and GitHub scopes implicit (undeclared) concurrency to each
individual workflow file. Cross-lane queueing is therefore impossible by
construction.

**The v2 workflows are already on the default branch**, so the proof below is
dispatchable now. This sentence used to read "after the v2 workflows reach the
default branch through a reviewed merge", which stopped being true and stayed
on the page; both files landed by squash
`8daa1812f8c2f89d6fa13be44c38283242c103bd` ("Package 2B.0: isolated green
broker and inert workflows (#10)"), verified by
`git show --stat 8daa181 -- .github/workflows/`. What the proof still needs is
the dispatch itself.

Runnable proof: dispatch two promotion runs with `mode=lane-proof` and
`hold_seconds > 0` while one candidate run is active and a legacy manual run
executes. Expected result: the promotion runs serialize against each other
only; candidate and legacy runs proceed unaffected. Record the four run URLs in
the Package 2B.0 gate note.

Statically, `tests/test_workflow_lanes.py` asserts the same property from the
workflow files: the two blue state writers share `araripe-legacy-state`, each
green group belongs to exactly one workflow, no group is shared across lanes,
and no lane cancels a run in progress.

## Inertness of the v2 route

Both v2 workflows trigger on `workflow_dispatch` only, carry
`permissions: contents: read`, and guard on the repository name. They cannot
inherit the blue cron, cannot push commits, and reference no production
credential.

The two lanes are inert for *different* reasons, and the distinction matters
when reading a dispatch that failed:

- **Lane 2** holds the staging identity, so its inertness is a guard: the
  bucket and endpoint checks reject a missing or wrong variable before any
  object operation, and a premature dispatch fails closed there.
- **Lane 3** holds nothing. It names no secret and declares no Environment, so
  no mode reachable from it performs an object operation at all; the two modes
  that would need one stop and name the missing capability. Its inertness is
  structural rather than guarded.
