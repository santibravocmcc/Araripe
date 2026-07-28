# Phase 1 Data Contracts, Version 1

**Status:** Phase 1 design accepted on 2026-07-28; not implemented

**Contract version:** `1.0.0`

**JSON Schema dialect:** Draft 2020-12

**Scope:** Contract design only; this document does not change production
processing, persistence, R2, publication, or client behavior.

## 1. Purpose and non-negotiable invariants

These contracts provide the versioned design required by Phase 1 of
`ROADMAP.md`. They cover the current wider monitoring extent, raw
observations, persistent events, split/merge lineage, replay-safe state,
per-date processing completeness, and authoritative releases.

Every implementation of version 1 must preserve these invariants:

1. The monitoring product covers the APA **and its surroundings**. The
   implementation rectangle is versioned as an honest description of current
   behavior; it is not silently replaced by the APA polygon.
2. A scientifically valid raw detection is immutable and retained. MapBiomas,
   persistence, contextual labels, and strong-subset membership annotate or
   select observations but never erase or invalidate the raw observation.
3. An acquisition contributes to an event's persistence count at most once.
   Replaying the same contribution key is a no-op.
4. An out-of-order acquisition never mutates canonical live state. Live
   processing fails closed; historical corrections rebuild a new state and
   release chronologically.
5. Authentication, network, parse, schema, checksum, or service failures while
   loading state fail closed and prohibit a replacement write. Only an
   explicitly confirmed missing object may initialize empty state.
6. Every expected acquisition date has exactly one terminal processing-ledger
   status. A missing date is not equivalent to zero alerts.
7. Published artifacts live below an immutable release prefix. Public URLs use
   `https://observatoriodachapadadoararipe.com` rather than an infrastructure
   hostname. Promotion changes only a small pointer using a conditional write.
8. An incomplete or failed release never replaces the last complete canonical
   release, and the prior release remains an explicit rollback target.

## 2. Files and schema identifiers

The schemas are self-contained: they use only local `$defs` and require no
network resolution during validation.

| Contract | Schema file | Canonical `$id` |
|---|---|---|
| Monitoring extent | `schemas/monitoring-extent-v1.schema.json` | `https://observatoriodachapadadoararipe.com/data/schemas/monitoring-extent-v1.schema.json` |
| Observation | `schemas/observation-v1.schema.json` | `https://observatoriodachapadadoararipe.com/data/schemas/observation-v1.schema.json` |
| Event and lineage | `schemas/event-v1.schema.json` | `https://observatoriodachapadadoararipe.com/data/schemas/event-v1.schema.json` |
| Persistence state | `schemas/persistence-state-v1.schema.json` | `https://observatoriodachapadadoararipe.com/data/schemas/persistence-state-v1.schema.json` |
| Processing ledger | `schemas/processing-ledger-v1.schema.json` | `https://observatoriodachapadadoararipe.com/data/schemas/processing-ledger-v1.schema.json` |
| Release manifest | `schemas/release-manifest-v1.schema.json` | `https://observatoriodachapadadoararipe.com/data/schemas/release-manifest-v1.schema.json` |

Each matching file under `examples/` is a non-production validation fixture.

## 3. Canonicalization and deterministic identities

All hashes use SHA-256 over UTF-8 bytes and are written as 64 lowercase
hexadecimal characters. Structured JSON used as a hash input is serialized
with RFC 8785 JSON Canonicalization Scheme (JCS). Lists used in identity inputs
are deduplicated, sorted by their UTF-8 byte representation, and joined with
line feed (`U+000A`). Identity components are joined with ASCII Unit Separator
(`U+001F`) and are not surrounded by whitespace.

Geometry canonicalization additionally requires:

- EPSG:4326 longitude/latitude axis order;
- finite coordinates without negative zero;
- closed polygon rings;
- counter-clockwise exterior rings and clockwise holes;
- each ring rotated so its lexicographically smallest coordinate is first;
- polygons and holes sorted by their canonical JCS byte representation.

### 3.1 Acquisition identity

A daily composite has:

```text
acquisition_hash = sha256(
  "acquisition-v1" U+001F
  collection_id U+001F
  observed_on U+001F
  sorted_scene_ids_joined_by_LF U+001F
  monitoring_extent_id U+001F
  composite_method_id
)
acquisition_id = "acq-v1-" + acquisition_hash
```

The scene list must contain the provider-native immutable scene identifiers.
Changing a contributing scene, extent, date, collection, or composition method
therefore creates a different acquisition.

### 3.2 Observation identity

An observation is one raw polygon detected for one acquisition:

```text
observation_hash = sha256(
  "observation-v1" U+001F
  acquisition_id U+001F
  canonical_geometry_sha256 U+001F
  algorithm_version U+001F
  baseline_version
)
observation_id = "obs-v1-" + observation_hash
```

The ID does not depend on presentation order, release path, MapBiomas
annotation, persistence tier, or site filtering.

Including `baseline_version` prevents two detections derived from different
historical baselines from sharing an immutable observation ID merely because
their final polygon geometry happens to be identical. MapBiomas remains
excluded because it annotates raw detections and cannot control their
existence.

### 3.3 Event identity

An origin event uses:

```text
event_hash = sha256(
  "event-v1" U+001F "origin" U+001F first_observation_id
)
```

A split or merge child uses:

```text
event_hash = sha256(
  "event-v1" U+001F operation U+001F
  sorted_parent_event_ids_joined_by_LF U+001F
  sorted_trigger_observation_ids_joined_by_LF
)
event_id = "evt-v1-" + event_hash
```

Existing events keep their IDs. A split produces at least two new child events
from one parent. A merge produces one new child event from at least two
parents. Parent events become `superseded`; their observations remain
immutable.

### 3.4 Lineage identity

Every append-only continuation, split, or merge edge has:

```text
lineage_hash = sha256(
  "lineage-v1" U+001F relation U+001F
  sorted_parent_event_ids_joined_by_LF U+001F
  sorted_child_event_ids_joined_by_LF U+001F
  effective_acquisition_id U+001F effective_on U+001F
  sorted_trigger_observation_ids_joined_by_LF U+001F
  algorithm_version
)
lineage_id = "lin-v1-" + lineage_hash
```

Changing either side of the edge, its effective acquisition/date, triggers,
relation, or algorithm version creates a different lineage edge. The
human-readable reason is audit metadata and does not alter the edge identity.

### 3.5 Persistence contribution key

```text
contribution_hash = sha256(
  "persistence-contribution-v1" U+001F
  event_id U+001F acquisition_id
)
contribution_key = "pc-v1-" + contribution_hash
```

The canonical state has a uniqueness constraint on `contribution_key`.
Reapplying a known key returns success with `no_op=true` and does not change
counts, dates, geometry, lineage, or the output state checksum.

Each release has exactly one canonical acquisition per expected observation
date. A different scene set or composite for the same date is a corrected
acquisition and requires a new chronological processing generation; it cannot
be added as a second live persistence contribution for that date.

## 4. Version-1 wider monitoring extent

Version 1 records the scheduled-production implementation rectangle rather
than narrowing processing to the APA. The project owner approved this choice
on 2026-07-28 as the initial operational footprint, not as a claim that a
rectangle is the permanent scientifically preferred boundary:

| Field | Value |
|---|---|
| `extent_id` | `araripe-implementation-rectangle-v1` |
| Scope | APA and surroundings |
| Geometry CRS | EPSG:4326 |
| Bounds | `[-40.89236812577142, -7.840780758480428, -38.95208146319247, -6.957104781339829]` |
| Planar area | `2092576.6787705552` ha in EPSG:32724 |
| Source APA file SHA-256 | `2bff31afa6cb74630a437b4fffb96ad88f7f873a3aa1461f337c66f61c209881` |
| Canonical geometry SHA-256 | `b4986ef80d8a0d6e65bbb41b575dbd952c010415bf3aee93a88412b3b657e8c7` |
| Canonical bounds SHA-256 | `93f254373d6b203bca33aa5c356bd03fec3bff7f43c9c15b368cc2bdb7029f28` |

The geometry checksum is the SHA-256 of the RFC 8785 representation of the
GeoJSON geometry object. The bounds checksum is the SHA-256 of the RFC 8785
representation of the four-number bounds array. A future scientifically
defined surrounding area requires a new extent ID and a new historical
generation; it must not mutate this record.

The scheduled GEE path already processes this rectangle. The manual streaming
fallback currently queries the rectangle and then clips to the APA polygon.
Implementation must resolve that inconsistency in favor of the approved
version-1 extent before the paths are treated as equivalent.

## 5. Observation, event, and lineage semantics

`observation-v1` is the immutable scientific detection. Its acquisition block
retains scene provenance, its quality block retains valid coverage and the
accepted scene decision, and its MapBiomas block explicitly states that land
cover does not affect existence.

`event-v1` groups observations interpreted as the same changing place. Event
area is not a cumulative deforestation total. Observation IDs and contributing
acquisition IDs are unique arrays. The event record carries an
`identity_basis` and explicit incoming/outgoing lineage edges.

A lineage edge is valid only when:

- `continuation` has exactly one parent and one child;
- `split` has exactly one parent and at least two children;
- `merge` has at least two parents and exactly one child;
- its trigger observations belong to its effective acquisition;
- every referenced event and observation exists in the same release;
- the current event appears on the appropriate side of each edge.

Lineage is append-only. Corrections create a new generation rather than
rewriting lineage in an immutable prior release.

## 6. Persistence-state transition policy

The persistence-state schema carries stable event, acquisition, observation,
and contribution IDs. Before applying an acquisition, an implementation must:

1. authenticate and download the expected input object;
2. verify transport metadata and checksum;
3. validate the complete document against its declared schema;
4. confirm that the input state ID, ETag, and watermark match the requested
   write precondition;
5. reject an acquisition date or ID at or before the watermark unless every
   proposed contribution key is already present;
6. treat a replay containing only known keys as a no-op;
7. apply a genuinely newer acquisition exactly once; and
8. conditionally write the new immutable state object, then update its pointer.

Any uncertainty in steps 1-4 is a fail-closed result with no state write. A
backfill or correction starts from an explicitly selected empty/snapshot state
and replays accepted observations chronologically into a new release namespace.

## 7. Processing-ledger terminal statuses

Each expected date has exactly one of these terminal statuses:

| Status | Meaning |
|---|---|
| `complete_with_alerts` | Processing and QA completed and produced one or more raw observations. |
| `complete_zero_alerts` | Processing and QA completed successfully and produced zero observations. |
| `rejected_low_coverage` | Input existed but valid coverage was below the versioned threshold. |
| `rejected_quality` | Input existed but failed a versioned scientific quality rule. |
| `failed_download` | An expected remote input could not be downloaded or verified. |
| `failed_missing_input` | No required input existed for the expected date. |
| `failed_processing` | Processing failed after inputs were available. |

No other terminal value is allowed. `complete_zero_alerts` must never be
represented by an absent row or a stale prior artifact. Rejections carry a
structured rejection reason; failures carry a structured failure reason.
Summary counts must exactly reconcile with the entry array, and
`terminal_count == expected_date_count`.

An all-terminal ledger may still be ineligible for publication. Under version
1, any `failed_*` entry blocks release eligibility. The release policy may
accept documented quality rejections, but cannot omit them. A rejection may
advance the component's `assessed_through` date and must set
`status=complete_with_rejections`; it does not advance the last successful
observation date or claim that usable observation data were produced.

## 8. Authoritative release manifest

The release manifest is the sole inventory used to construct public products.
It records:

- backend and site commits and the workflow runs that produced the release;
- algorithm, baseline, MapBiomas, extent, and all schema versions;
- authoritative extent, ledger, input/output state, validation, and artifact
  checksums;
- immutable paths, visibility, media types, sizes, and public URLs;
- alert, rainfall, and site freshness as separate clocks;
- validation status and contract checks;
- conditional promotion metadata and retained rollback releases.

All release artifact keys have this form:

```text
releases/<release_id>/<artifact-relative-path>
```

Every public URL is the exact same-origin equivalent:

```text
https://observatoriodachapadadoararipe.com/data/releases/<release_id>/<artifact-relative-path>
```

Private artifacts have `public_url: null`. Infrastructure URLs such as
`r2.dev` are forbidden in a canonical manifest.

The mutable public pointer is:

```text
https://observatoriodachapadadoararipe.com/data/releases/current.json
```

The public contract base is `/data/releases`. Physical bucket names are
deployment configuration and never appear in browser URLs or canonical
manifests.

Immutable release artifacts should be served with long-lived immutable cache
headers. The pointer and any mutable readiness document must use revalidation
(`no-cache` or a short TTL with ETag). Clients invalidate in-memory release
data whenever the pointer's `release_id` changes. Rollback is the same
conditional pointer operation targeting a retained prior release.

Each component freshness record distinguishes:

- `assessed_through`: the latest date with a terminal ledger assessment;
- `latest_attempt_at`: the most recent processing attempt;
- `last_successful_at`: the most recent complete-with-alerts or
  complete-zero-alerts result for alerts, or the equivalent successful
  component build;
- `source_release_id`: the immutable release supplying the selected data.

Carrying one component forward never advances its freshness timestamps.

## 9. Semantic-version compatibility

All `schema_version` and component-version fields use Semantic Versioning:

- **major:** incompatible meaning, identity input, required-field, or enum
  change;
- **minor:** backward-compatible optional information or a new capability that
  preserves all existing meanings;
- **patch:** clarification or validation tightening that does not change valid
  data meaning or deterministic identity.

These version-1.0 schemas validate the exact value `1.0.0`. A producer using a
later schema must publish that schema beside the artifact. Consumers must parse
the version before parsing the payload:

1. reject an unknown major version;
2. accept a later minor version only when the client explicitly advertises
   support for it;
3. never silently coerce an unknown enum or required field;
4. validate against the exact advertised schema before state mutation or
   publication; and
5. preserve unknown-major canonical data for audit without treating it as
   usable state.

Changing acquisition, observation, event, lineage, or contribution identity
inputs requires a new major version.

## 10. Validation and review gate

Before Phase 1 is considered reviewed:

- every JSON file must parse;
- every example must validate against its matching Draft 2020-12 schema;
- the extent geometry and bounds hashes must be recomputed from their canonical
  representations;
- example deterministic IDs must be recomputed from the rules above;
- cross-document references, summary arithmetic, release-prefix ownership, and
  public URL equivalence must be checked in addition to JSON Schema;
- the workflow/cloud boundary, configuration register, provenance register, and
  rollback checklist must reference these exact version identifiers.

The local fixture gate implements those checks:

```bash
/opt/anaconda3/envs/araripe/bin/python \
  docs/contracts/phase1/validate_contracts.py
```

It validates all six schemas/examples and recomputes the deterministic
fixture identities, ledger reconciliation, release paths, and same-origin
public URLs without network or cloud access.

Schema validation alone cannot prove checksum correctness, chronological order,
cross-file reference existence, arithmetic reconciliation, or conditional
write safety. Those are mandatory semantic validation steps for later
implementation.
