# Phase 1 discovery and contract package

**Evidence captured:** 2026-07-24

**Local validation last run:** 2026-07-28

**Roadmap phase:** Phase 1 — whole-system discovery and contract design

**Phase status:** Closed and accepted on 2026-07-28

**Production mutation:** none

This directory is the review package for Phase 1 of `ROADMAP.md`. It records
the current cross-repository boundary, separates historical evidence from
unverified live cloud state, and defines the version-1 scientific/publication
contracts before implementation.

## Package inventory

| Roadmap requirement | Artifact | Disposition |
| --- | --- | --- |
| 1.1 workflow inventory and dependency map | `SYSTEM_BOUNDARY_AND_WORKFLOWS_2026-07-24.md` | Complete against all three default-branch workflows and relevant local code |
| 1.2 Cloudflare/R2 before-state and rollback | `CLOUDFLARE_BEFORE_STATE_AND_ROLLBACK_2026-07-24.md` | Core live control-plane, deployment provenance/rollback targets, public routes, R2 policies, and all 141 object records refreshed on 2026-07-28; connector-limited zone settings and exact token scope are mandatory pre-implementation rechecks |
| 1.3 extent, identity, lineage, persistence, ledger, and release contracts | `DATA_CONTRACTS_V1.md`, `schemas/`, `examples/` | Six Draft 2020-12 schemas and fixtures complete; deterministic and semantic validation passes |
| 1.3 artifact ownership and client/cache migration | `ARTIFACT_OWNERSHIP_AND_CLIENT_MIGRATION_V1.md` | Draft ownership, immutable release topology, dual-read migration, cache, and rollback rules complete |
| 1.4 names-only configuration/credential register | `CONFIGURATION_REGISTER_2026-07-24.md` | Complete: GitHub names/presence, Actions policy, workflow-token authority, environments, variables, branch controls, R2 token metadata, owner, role split, preflights, and safe handling of irrecoverable legacy-token ambiguity are recorded |
| 1.4 data-source and attribution register | `DATA_SOURCE_AND_ATTRIBUTION_REGISTER_2026-07-24.md` | Exact acquired MapBiomas URLs, access date, checksums, identities, headers, NoData, proposed transforms, and CC-BY attribution recorded; remaining provenance gates explicit |

The versioned schema set is:

- `monitoring-extent-v1`
- `observation-v1`
- `event-v1`
- `persistence-state-v1`
- `processing-ledger-v1`
- `release-manifest-v1`

Every schema is self-contained and uses JSON Schema Draft 2020-12. The matching
fixtures are illustrative non-production records.

## Local validation

Run from the `Araripe` repository:

```bash
/opt/anaconda3/envs/araripe/bin/python \
  docs/contracts/phase1/validate_contracts.py
```

The validator:

- checks the exact six-schema/six-fixture inventory;
- validates each schema and fixture, including date/date-time formats;
- recomputes the extent, acquisition, observation, event, contribution, ledger,
  and artifact-inventory hashes used by the fixtures;
- reconciles observation/event/state references and replay contribution keys;
- reconciles expected dates, terminal statuses, counts, and release
  eligibility;
- verifies immutable release ownership, canonical prefixes, authoritative
  record references, and exact same-origin public URLs.

Schema validation cannot prove cloud permissions, conditional-write behavior,
scientific accuracy, provider availability, or a deployed rollback. Those are
later implementation/rehearsal gates.

## Review decisions

Reviewers should explicitly accept or change:

1. extent ID `araripe-implementation-rectangle-v1` and its implementation-
   derived rectangle;
2. deterministic acquisition, observation, event, lineage, and persistence
   contribution identities;
3. the seven terminal processing-ledger statuses and the policy that any
   `failed_*` status blocks promotion;
4. the immutable `releases/{release_id}/...` ownership model and conditional
   `/data/releases/current.json` pointer;
5. separate alert, rainfall, and site freshness clocks;
6. private processing/public release security boundaries and proposed
   least-privilege roles;
7. dual-read migration, cache behavior, rollback retention, and legacy
   retirement gates;
8. MapBiomas identities, class-0/NoData interpretation gates, attribution, and
   wider-extent crop transform.

### Decision record

| Decision | Status | Owner record |
|---|---|---|
| 1. Monitoring extent | **Approved as drafted** | Project owner approved `araripe-implementation-rectangle-v1` as version 1 on 2026-07-28. The approval versions the scheduled-production rectangle as the initial operational footprint; it does not claim that a rectangle is the permanent scientifically preferred boundary. |
| 2. Deterministic identities | **Approved with safeguards** | Project owner approved the deterministic acquisition/observation/event/lineage/contribution model on 2026-07-28, with `baseline_version` included in observation identity and exactly one canonical acquisition per expected date in each release. Corrected same-date acquisitions require a new processing generation. |
| 3. Processing-ledger statuses | **Resolved by delegated technical review** | Retain the seven terminal statuses. Any `failed_*` blocks promotion; documented scientific rejections remain visible and may advance assessment coverage but never masquerade as a successful observation date. |
| 4. Immutable releases and pointer | **Resolved by delegated technical review** | Use immutable `releases/{release_id}/...` artifacts and the conditional same-origin pointer `/data/releases/current.json`. Only the small pointer is mutable. |
| 5. Freshness clocks | **Resolved by delegated technical review** | Keep alert, rainfall, and site clocks independent, each recording assessed-through time, latest attempt, last successful completion, and source release. |
| 6. Private/public boundary and roles | **Resolved by delegated technical review** | Use separate private processing and public release buckets with private-reader, science-writer, and public-publisher roles. The Worker build/deploy credential receives no R2 authority. |
| 7. Migration, cache, rollback, and retirement | **Resolved by delegated technical review** | Use a 30-day minimum dual-read window, at least four successful monitoring releases and two rainfall refreshes, immutable caching, at least three complete rollback releases retained for at least 90 days, and no legacy deletion during initial retirement. |
| 8. MapBiomas interpretation and crop | **Resolved by delegated technical review** | Preserve exact source identities and CC-BY attribution; treat 10 m class `0` as NoData and 30 m class `0` as unknown/NoData until fixture-backed official verification; use nearest-neighbour wider-extent crops and never let MapBiomas erase raw observations. |

## Phase 1 disposition

Phase 1 is closed as an evidence-backed discovery and contract-design package:

- the working Cloudflare connector and owner-supplied dashboard evidence
  complete the Phase 1 Cloudflare/R2 boundary inventory. Zone settings, Page
  Rules, DNSSEC, and connector credential introspection are explicitly
  recorded as connector-limited mandatory pre-implementation rechecks, not as
  a request to reconnect the working plugin;
- refreshed GitHub authentication completed the read-only names-and-settings
  inventory for both repositories. Secret names/presence, variables,
  environments, workflow state, Actions policy, `GITHUB_TOKEN` authority,
  artifact retention, and default-branch enforcement are recorded without
  reading a secret value;
- GitHub cannot reveal which historical Cloudflare access-key ID is stored
  behind an existing repository secret. The exact March backend-token match
  and the likely July site-token match are documented as before-state
  ambiguity; role-specific replacement and recorded mapping are required
  before implementation instead of exposing old credentials;
- current backend SQLite, R2, and the production/default-branch site manifest
  are reconciled; the before-state register records five database-only dates
  that later ledger/replay work must classify;
- all eight contract decisions are resolved. The project owner is accountable
  for commissioning the qualified provenance/scientific follow-up gates; those
  later gates remain open without blocking Phase 1 acceptance.

The next change package may start Phase 2A. No production write, deployment,
rotation, or data replay was performed to close Phase 1.
