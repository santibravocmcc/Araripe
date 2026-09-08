# Artifact Ownership and Client Migration Contract v1

**Status:** Phase 1 design accepted on 2026-07-28; not implemented
**Version:** 1.0.0
**Date:** 2026-07-24
**Scope:** backend monitoring, site preparation, rainfall, public data delivery,
and release recovery

## 1. Purpose and boundaries

This document assigns canonical ownership to the artifacts that cross the
backend, site, GitHub Actions, Cloudflare R2, and browser boundaries. It also
defines a non-destructive client migration from the current mixed Git/R2 layout
to immutable releases served under a same-origin `/data/...` route.

This is a contract design only. It does not create buckets, copy or delete
objects, change a route, deploy a Worker, alter a workflow, or promote a
release. Current production and all current/2026 audit material remain
unchanged.

Identity, ledger, release, and compatibility semantics are defined by
`DATA_CONTRACTS_V1.md`. This document assigns their storage and mutation
ownership and must not introduce a second schema, pointer path, or identity
rule.

The following roadmap constraints are normative:

- monitoring covers the APA **and its surroundings**; the processing extent
  must be named, versioned, checksummed, and must not be silently narrowed to
  the APA polygon;
- raw scientifically valid detections are retained even when they do not enter
  a public strong subset;
- routine monitoring, time-series, rainfall, and public-data publication remain
  automated;
- release artifacts are immutable and promotion is atomic;
- an incomplete run never replaces the last complete release;
- public and private storage are separate security boundaries, not prefixes in
  one public bucket;
- current products and the eventual corrected 2026 generation remain
  recoverable audit material;
- initial migration copies and verifies; it does not delete.

Delegated technical review on 2026-07-28 selected these implementation
targets:

- private bucket: `araripe-processing-private`;
- public release bucket: `araripe-public-releases`;
- public contract base: `/data/releases`;
- mutable pointer: `/data/releases/current.json`.

Bucket availability must be verified before creation. A necessary physical
bucket rename is deployment configuration and does not change the same-origin
public contract. These paths and names are targets, not evidence that a route
or object already exists.

## 2. Terms and ownership roles

| Term | Meaning |
|---|---|
| Canonical artifact | The authoritative representation from which derivatives are reproducibly generated. A cache, browser bundle, or convenience copy is not canonical. |
| Producer | Code or workflow that deterministically creates an artifact. |
| Mutation owner | The single role permitted to create or advance a canonical mutable reference. Consumers never mutate their inputs. |
| Release publisher | The future automated publication step that validates a complete release and conditionally advances a pointer. |
| Immutable | Content is written once at a versioned or release-specific key. A correction creates a new version; it does not overwrite the old object. |
| Working state | Private state used to continue routine processing. It may advance only through a validated, conditional update and always has immutable input/output snapshots. |
| Release pointer | A small, conditionally updated public object that selects one verified immutable release. It is the only mutable public data object. |
| Rollback | Repointing public consumers to an already verified retained release. Rollback never edits an immutable artifact. |
| Cache/staging | Reconstructable, non-canonical material. It may be deleted only under a reviewed lifecycle policy after canonical inputs and outputs are verified. |

Logical roles used below:

- **Science producer:** the backend detection code in `Araripe`.
- **Rainfall producer:** the GPM ingestion and territory preparation code in
  `site`.
- **Public-product builder:** deterministic preparation code that converts
  canonical private artifacts into reviewed browser/download products.
- **Release publisher:** a future serialized automation step with conditional
  promotion authority.
- **Site client:** the browser application; read-only.
- **Deployment owner:** the reproducible Worker/static-assets deployment
  process; it deploys code and routes, not scientific state.

## 3. Current boundary

The current implementation has no authoritative release manifest, processing
ledger, or release pointer. The sanitized live inventory refreshed on
2026-07-28 records:

- `baselines/`: 72 objects, approximately 13.408 GB;
- `alerts/`: 31 objects, approximately 1.251 GB;
- `site-full/`: 37 objects, approximately 0.641 GB;
- `persistence_state.geojson`: one object, approximately 0.132 GB.

Those families currently share one R2 bucket. Representative baseline, source
alert, state, and full-product objects were publicly retrievable during the
review. CORS, lifecycle, public-domain state, storage class, and object
metadata are recorded in the Cloudflare before-state; the exact application
secret-to-historical-token identity cannot be recovered through names-only
GitHub metadata and is recorded as a replacement prerequisite. The site
repository also tracks large generated strong-alert GeoJSON in ordinary Git.

Current mutation sequence:

1. a backend workflow fetches fixed-key baselines and the single persistence
   state object;
2. detection writes `alerts/alerts_YYYY-MM-DD.geojson`, overwrites
   `persistence_state.geojson`, and commits `data/timeseries/timeseries.db`;
3. a clock-delayed site workflow rereads the alert archive, overwrites
   `site-full/run-YYYY-MM-DD.geojson`, commits strong/public products, and then
   commits rainfall products;
4. Cloudflare Worker Builds deploys after a site `main` push using
   `npm run build` and `npx wrangler deploy`.

There is no atomic boundary across these mutations. R2 and Git can therefore
describe different generations.

## 4. Ownership and classification matrix

“Private” means inaccessible through the public bucket/domain. “Public” means
approved for unauthenticated delivery. “Audit” means preserved even after it is
superseded. “Ephemeral” means reconstructable and non-canonical.

| Artifact family | Current location and access | Current producer / mutation owner | Current consumers | Target canonical class and logical location | Target producer / mutation owner | Retention, immutability, and rollback |
|---|---|---|---|---|---|---|
| Monitoring-extent definition | Backend Git under `data/aoi/`; scheduled GEE code also embeds an implementation-derived rectangle | Human-maintained source plus backend code; no single versioned mutation owner | GEE/STAC processing, baseline generation, site AOI preparation | **Private + audit:** `inputs/extents/{extent_version}/` containing geometry, bounds, CRS, area, checksum, and provenance | Science producer reads; a reviewed configuration change creates a new version | Immutable by `extent_version`. Retain every extent used by a release. A release always names and checksums its exact wider extent. |
| APA and FLONA reference boundaries | Backend Git `data/aoi/*.gpkg`; site also has vendored shapefiles and simplified public GeoJSON | Human/import process; site preparation creates copies | Context maps, territory products, public downloads | **Private reference + public derivative:** versioned source boundary package; release-specific `/data/releases/{release_id}/aoi/apa.geojson` and `flona.geojson` | Reviewed reference-data owner; public-product builder for simplified derivatives | Source versions immutable. Public derivatives live with the release. They describe protected-area context and do not redefine the wider monitoring extent. |
| Raw/national MapBiomas inputs | Ignored/local national 2024 rasters; tracked older/cropped layers under backend `data/landcover/` | External-source acquisition plus human preparation | Land-cover annotation and crop generation | **Private + audit:** `inputs/mapbiomas/{collection_version}/source/` with source URL, access date, checksum, CRS, NoData, resolution, and redistribution terms | Reviewed data-ingestion process only | Preserve national/raw inputs and checksums. Never place raw national rasters in Git or a public bucket without a reviewed redistribution decision. |
| MapBiomas processing crops | Backend tracked/local `data/landcover/*.tif` | Backend preparation/import process | Alert annotation and public overlay preparation | **Private + audit:** `inputs/mapbiomas/{collection_version}/crops/{extent_version}/` | Science producer or reviewed preprocessing job | Immutable by collection, year, resolution, extent, transformation, and checksum. Rebuilds create a new version. |
| Public MapBiomas overlays | Site Git `public/data/mapbiomas/` | Site preparation and direct Git commits | Browser territory/alert maps | **Public release derivative:** `/data/releases/{release_id}/mapbiomas/` | Public-product builder; no browser mutation | Immutable with release. Long immutable cache. Roll back with the component/release pointer. |
| Baseline COGs | R2 `baselines/`, currently in the same public bucket as public data | Baseline build/upload utilities; fixed prefix | Backend detection and site time-series baseline extraction | **Private + audit:** `baselines/{baseline_version}/` plus a checksum/coverage manifest | Reviewed baseline-build process creates; detection reads only | Immutable by version. Retain every baseline referenced by any retained release, including the current audit generation. Rollback selects an older complete baseline only through a new processing release. |
| Satellite scenes, GEE tiles, STAC downloads, CHIRPS inputs | GEE/external providers and local `data/scene_cache`, CHIRPS, temporary download directories | Acquisition code | Baseline/detection/drought processing | Source provenance in the private ledger; retained raw inputs only where licensing, reproducibility, and cost policy require; otherwise **ephemeral cache** | Science producer | Cache can expire after checksums/scene IDs and reconstructability are verified. Source needed for an audit or replay follows an approved retention policy. Never treat cache presence as release completeness. |
| Source alert observations | R2 `alerts/alerts_YYYY-MM-DD.geojson`, mixed with public families | Backend detection workflows overwrite date keys | Persistence, site preparation, validation | **Private + audit:** `releases/{release_id}/source/alerts/{date}.geojson` | Science producer creates immutable candidates; release publisher never edits them | Retain all scientifically valid raw observations, including zero-alert records represented in the ledger. A correction creates a new release. Never delete a raw detection because it fails MapBiomas or strong-subset criteria. |
| Persistence working state | R2 root `persistence_state.geojson`, one mutable fixed key | Both backend detection paths can overwrite it | Next detection run | **Private working state:** a conditionally updated state reference plus immutable `releases/{release_id}/state/input.*` and `output.*` snapshots | One serialized science-state publisher | Only explicit missing-state initialization may start empty. Auth, network, parse, schema, and service failures fail closed. Every accepted update records the previous version/ETag and release identity. Public rollback does not silently rewind working scientific state. |
| Time-series SQLite database | Backend Git `data/timeseries/timeseries.db`, bot-mutated on `main` | Backend detection workflows | Site preparation and scientific review | **Private + audit:** `releases/{release_id}/timeseries/timeseries.db` plus schema/checksum/QA metadata | Science producer; release publisher accepts only a validated snapshot | Immutable release snapshot. Mixed-generation or failed-QA rows are quarantined. A corrected database is a new release, not an in-place historical rewrite. |
| Processing ledger | Absent | None | None | **Private authoritative:** `releases/{release_id}/processing-ledger.json`; optional sanitized public status included or referenced by the manifest | Science producer records per-date status; release publisher validates terminal completeness | Immutable. Includes every expected date with exactly one v1 terminal status: `complete_with_alerts`, `complete_zero_alerts`, `rejected_low_coverage`, `rejected_quality`, `failed_download`, `failed_missing_input`, or `failed_processing`. Retained with the release. |
| Release manifest | Current site product manifests are partial and unversioned; no cross-system manifest | Site preparation writes product-specific manifests | Browser | **Public authoritative:** `/data/releases/{release_id}/manifest.json`; private copy may include additional internal provenance | Release publisher writes only after schema, checksums, ledger, state, and product gates pass | Immutable. Contains component versions, commits, workflow runs, algorithms, input/output checksums, extent, freshness, validation, and rollback metadata. Incomplete releases are never eligible for a pointer. |
| Release pointer | Absent | None | None | **Public mutable:** proposed `/data/releases/current.json` under the final same-origin route | Release publisher only, using a conditional compare-and-swap | Keep prior pointer documents and ETags in audit logs. The pointer selects one complete release whose manifest records monitoring, rainfall, and site freshness separately. Rollback atomically restores a retained verified pointer. The V1 path remains subject to review with the contract package before implementation. |
| Full browser alert products | R2 `site-full/run-YYYY-MM-DD.geojson`, public development hostname hard-coded in site code | Site preparation unconditionally reuploads fixed keys | Browser full mode and downloads | **Public release derivative:** `/data/releases/{release_id}/alerts/run-{date}.full.geojson` | Public-product builder; release publisher validates/publishes | Immutable with release; content type, checksum, byte ranges, and download behavior validated. Never served from the private bucket. |
| Strong alert subsets | Site Git `public/data/alerts/run-*.strong.geojson` | Site preparation and bot push | Default browser mode | **Public release derivative:** `/data/releases/{release_id}/alerts/run-{date}.strong.geojson` | Public-product builder | Immutable with release. Strong membership is a derivative classification and never controls retention of the raw observation. Remove routine generated blobs from source Git only after verified migration; do not rewrite Git history without separate approval. |
| Alert point index and alert UI manifest | Site Git `public/data/alerts/all-strong-points.json` and `manifest.json` | Site preparation and bot push | Browser overview, filters, and downloads | **Public release derivative:** release-relative point index; release manifest is authoritative | Public-product builder; release publisher validates | Immutable with release. Client must use only files named by the selected release manifest. |
| Public time-series JSON | Site Git `public/data/timeseries/series.json` | Site preparation from backend DB and baseline data | Browser charts/downloads | **Public release derivative:** `/data/releases/{release_id}/timeseries/series.json` | Public-product builder | Immutable with release. Carries source, algorithm, baseline, coverage, schema, QA, and freshness versions. |
| Public AOI/extent downloads | Site Git `public/data/aoi/` | Site preparation | Browser maps and downloads | **Public release derivative:** release-relative wider extent plus APA/FLONA context files | Public-product builder | Immutable with release. The wider extent and protected-area boundaries are separately named to prevent semantic substitution. |
| Rainfall source rasters | Site Git `scripts/territorio-src/GPM/*.tif` | Rainfall workflow | Territory preparation | **Private source or controlled audit input:** `rainfall/inputs/{source_version}/{date}/` | Rainfall producer | Preserve according to NASA terms and the approved replay/audit policy. Stop routine source-data commits to a code branch after migration. |
| Rainfall incremental caches | Site Git `scripts/territorio-src/gpm_monthly_series.json` and `gpm_recent_late.json` | Rainfall workflow | Historical-rainfall derivation | **Private reconstructable cache + release provenance:** cache outside source Git; release records source granules/checksums and accepted periods | Rainfall producer | Cache is resumable but not canonical. It may be rebuilt. A missing/incomplete period gets an explicit status and cannot advance freshness. |
| Public rainfall products | Site Git `public/data/territorio/rain/`, `chuva-historico.json`, and figures | Rainfall/territory preparation and bot push | Browser maps and charts | **Public release derivative:** `/data/releases/{release_id}/rainfall/` | Rainfall producer builds; release publisher validates a complete release with independent rainfall status and freshness | Immutable with release. A release may preserve the prior verified monitoring component while advancing validated rainfall, or conversely, but it never claims freshness for the unchanged component. |
| Static site/Worker bundle | Local/generated `dist/`; Cloudflare Worker Builds deploys site `main`, but the repository does not reproducibly script health/rollback | Cloudflare Worker Builds runs Vite/Wrangler; accountable human owner and credential scope are unassigned | Browser and `/api/chat` | **Public deployment artifact:** code deployment keyed by site commit and deployment ID, separate from data releases | Deployment owner | Retain enough deployment metadata to roll code back independently. A code rollback must continue to understand the selected public manifest compatibility range. |
| Local caches and staging | Backend scene/temp directories; site `.cache/alerts` and `.cache/full`; runner temporary directories | Individual scripts and CI runners | Same run only | **Ephemeral private:** `staging/{run_id}/` or local cache | Producing step only; release publisher reads staged outputs but does not treat them as canonical | A failed staging prefix is quarantined or expires only under a reviewed lifecycle policy. No promotion by rename/copy until validation passes. Cache deletion never deletes canonical source or audit material. |
| Current and 2026 audit generations | Git history, current R2 keys, technical-review evidence | Existing workflows | Audit/recovery | **Audit preservation set:** checksummed snapshot or immutable legacy release record | Migration owner copies and verifies; no initial deletion | Retain through the correction/replay and for the approved rollback period. “Fresh start” creates a new canonical generation; it does not erase the old one. |

## 5. Target release topology

### 5.1 Private boundary

The private storage boundary contains source, state, baseline, database,
processing, and staging material. A logical layout is:

```text
inputs/
  extents/{extent_version}/
  mapbiomas/{collection_version}/
baselines/{baseline_version}/
releases/{release_id}/
  source/alerts/
  state/
  timeseries/
  processing-ledger.json
  private-manifest.json
working/
  persistence-state-pointer.json
rainfall/
  inputs/{source_version}/
staging/{run_id}/
```

This is a logical namespace. Separate buckets and least-privilege credentials,
not prefixes alone, enforce the private/public boundary.

### 5.2 Public boundary

The proposed public shape is:

```text
/data/releases/current.json
/data/releases/{release_id}/manifest.json
/data/releases/{release_id}/alerts/run-{date}.strong.geojson
/data/releases/{release_id}/alerts/run-{date}.full.geojson
/data/releases/{release_id}/alerts/all-strong-points.json
/data/releases/{release_id}/timeseries/series.json
/data/releases/{release_id}/aoi/monitoring-extent.geojson
/data/releases/{release_id}/aoi/apa.geojson
/data/releases/{release_id}/aoi/flona.geojson
/data/releases/{release_id}/mapbiomas/manifest.json
/data/releases/{release_id}/mapbiomas/...
/data/releases/{release_id}/rainfall/manifest.json
/data/releases/{release_id}/rainfall/...
```

The public pointer selects one complete release:

```json
{
  "schema_version": "1.0.0",
  "release_id": "example-only",
  "manifest": "/data/releases/example-only/manifest.json"
}
```

The identifier above is illustrative, not a live value. The selected manifest
records alert, rainfall, and site status/freshness separately. When only one
product advances, the new complete release preserves the prior verified
component and its older freshness rather than falsely advancing it.

### 5.3 Mutation rules

1. A producer writes only to a unique staging or release identity.
2. Producers never overwrite an immutable release artifact.
3. The release publisher validates the manifest schema, all declared
   checksums, the ledger, expected dates, state watermark, and required browser
   products.
4. Promotion conditionally updates the small release pointer against the
   previously read version/ETag.
5. An older or racing run cannot replace a newer accepted pointer.
6. A valid zero-alert date is a terminal successful ledger state with an empty
   artifact or explicit representation; it is not an omitted object.
7. A partial, rejected, or failed run remains inspectable in private staging
   but never becomes current.

## 6. Client dual-read migration

Migration must be reversible and must not mix generations.

### Stage A — Publish without switching clients

1. Finalize and version the release-manifest and ledger schemas.
2. Copy one reviewed legacy generation into private/public release-specific
   paths.
3. Verify object counts, checksums, content types, byte-range behavior, public
   downloads, CORS/route behavior, and browser strong/full modes.
4. Create the proposed same-origin route in staging first.
5. Keep all existing Git and R2 paths unchanged.

### Stage B — Add dual-read behavior

The site client gains a release resolver with these rules:

1. Fetch the proposed same-origin pointer.
2. Accept only a supported `schema_version` and a component marked complete.
3. Fetch the selected immutable manifest, then only artifacts named by that
   manifest.
4. Validate required fields and, where practical in the browser, declared size
   or checksum metadata.
5. Never combine a legacy manifest, a new strong file, and an older full file.
   One rendered view is bound to one release identity.
6. During a bounded migration window only, use legacy locations when the new
   pointer is explicitly absent or its schema predates client support.
7. On a malformed pointer, checksum failure, incomplete manifest, or missing
   required artifact, keep the last successfully validated release. Do not
   silently construct a mixed release from legacy paths.
8. Record which path and release identity supplied the view, without exposing
   secrets or private object names.

The client decision table is:

| Condition | Client action during migration | Action after legacy retirement |
|---|---|---|
| Pointer and manifest are compatible, complete, and validated | Use same-origin release artifacts | Same |
| Pointer is explicitly absent because rollout has not reached this environment | Use legacy contract and report legacy mode | Fail visibly or use last validated release; do not revive retired paths |
| Pointer schema is newer than the client supports | Keep last validated release; legacy fallback allowed only while the migration flag is active | Keep last validated release and prompt code upgrade |
| Network/transient route failure | Use the last validated cached pointer/release when available; legacy only within the bounded migration window | Use last validated release |
| Manifest is incomplete, malformed, or fails validation | Reject it; keep the last validated release | Same |
| One required artifact is missing or mismatched | Reject the whole release; never mix files | Same |
| Ledger declares valid zero alerts | Render a successful empty result with the declared date/freshness | Same |
| Monitoring advances but rainfall does not, or conversely | Publish/select only a complete release that preserves the prior verified unchanged component and its older freshness while advancing the validated component | Same |

### Stage C — Shadow comparison

For a representative set that includes zero-alert, non-empty, large-full,
strong, time-series, AOI, MapBiomas, and rainfall artifacts:

- compare legacy and release-specific counts, bounds, dates, schemas, and
  checksums or deterministic normalized hashes;
- run browser tests for default strong mode, full mode, all dates, downloads,
  charts, map overlays, rainfall, and failure fallback;
- confirm the final public domain serves the new files under `/data/...`;
- confirm private baseline, state, database, and source paths are not publicly
  retrievable;
- verify a deliberately incomplete candidate does not replace current;
- verify pointer rollback restores the previous complete view.

Any unexplained difference blocks cutover.

### Stage D — Prefer the release contract

After the shadow gate:

1. switch the client default to the same-origin pointer;
2. retain bounded legacy fallback and the prior public pointer;
3. stop creating new routine generated alert/rainfall commits only after the
   R2 publication path is proven automatic;
4. remove the hard-coded public development R2 hostname from client code;
5. keep legacy objects and Git history during the approved rollback window.

### Stage E — Retire legacy reads

Legacy reads may be removed only after:

- the dual-read path has run for at least 30 consecutive days;
- at least four stable automated monitoring releases and two stable rainfall
  refreshes have advanced their respective components;
- browser, download, freshness, and rollback checks pass in production;
- monitoring shows no required fallback caused by a release-contract failure
  during that window;
- the project owner approves the retention and cutover decision.

Retirement initially disables reads/writes; it does not delete historical
objects. Any later deletion requires an inventory, checksum comparison, dry
run, explicit targets, and separate approval.

## 7. Cache and invalidation contract

Versioned URLs provide cache invalidation. Publication must not rely on a broad
cache purge.

| Object type | Cache behavior |
|---|---|
| Release pointer | Revalidate on every session/navigation that needs freshness; proposed `Cache-Control: no-cache, must-revalidate` with ETag support. Do not give it an immutable TTL. |
| Immutable manifest | Long public cache is allowed because its URL contains `release_id`; proposed `public, max-age=31536000, immutable`. |
| Immutable GeoJSON, JSON, PNG, COG, and downloads | Long public cache with immutable release URL, correct `Content-Type`, `Content-Encoding` where used, ETag, and byte ranges for large downloads. |
| Legacy `/data/...` aliases during migration | Short cache only. They must not outlive the migration window or mask pointer advancement. |
| Failed/private staging | Never public-cache. It is not addressable through the public route. |

The client may cache the last validated pointer and manifest for transient
recovery, but it must surface their recorded freshness rather than claiming
they are current.

## 8. Rollback and retention classes

| Class | Included artifacts | Rule |
|---|---|---|
| Permanent scientific/audit | Raw valid observations, release manifests, processing ledgers, extent identity, algorithms/commits, input/output checksums, current and corrected 2026 generations | Preserve. Corrections create a new release and lineage record. |
| Version-dependent scientific | Baseline versions, MapBiomas crops, state snapshots, database snapshots | Retain while referenced by any retained release and for the later approved scientific-retention period. |
| Public rollback release | All artifacts selected by current and retained prior pointers | Retain at least the three most recent complete releases and every complete release from the preceding 90 days, whichever preserves more. |
| Source/provider input | National MapBiomas and retained satellite/rainfall inputs | Follow provenance, licence, replay, and cost policy; never delete solely because a derived release exists. |
| Ephemeral | CI downloads, local caches, failed staging, derived scratch files | Delete only through a scoped lifecycle rule after proving reconstructability and excluding audit/canonical material. |
| Legacy migration | Existing `alerts/`, `site-full/`, state, Git-generated files, and current public products | Copy and verify first. No initial deletion or history rewrite. |

The current/2026 audit generations are permanent under the Roadmap and do not
count toward the three-release/90-day rollback minimum. The initial planning
envelope is USD 1/month for R2 storage; if a preflight estimate exceeds that
amount, implementation pauses for an explicit cost decision. No lifecycle
deletion is enabled merely because an object exceeds the rollback window.

Public rollback updates only the public pointer. If processing must continue
from an older scientific state, create an explicit recovery/replay operation
that selects the matching immutable state snapshot and produces a new release.
Never make a public UI rollback silently mutate or rewind the live persistence
state.

## 9. Acceptance gate for implementation

Implementation may begin only when:

- the live Cloudflare/R2 before-state and credential scopes are recorded
  without secret values;
- the target buckets `araripe-processing-private` and
  `araripe-public-releases`, plus `/data/releases` and
  `/data/releases/current.json`, pass availability/routing preflight;
- manifest, ledger, extent, observation/event identity, and compatibility
  schemas are versioned;
- every artifact has one canonical producer and one mutation owner;
- private and public credentials cannot cross their intended bucket boundary;
- staging validation, conditional promotion, valid-zero handling, and rollback
  tests are specified;
- the client dual-read and cache rules have browser tests;
- retention duration and rollback-count decisions are surfaced before any
  lifecycle or deletion rule is enabled.
