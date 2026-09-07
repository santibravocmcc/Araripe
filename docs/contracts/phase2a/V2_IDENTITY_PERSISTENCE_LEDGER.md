# Phase 2A.6A v2 identity, persistence, and ledger contracts

**Contract version:** `2.0.0`

**Scope:** local candidate-generation identity, lineage, persistence, and
manifest-bound acquisition accounting

**Production mutation:** none

## Contract boundary

This directory defines the coherent v2 family selected by
`config/phase2a_candidate_generation_decisions_v2.json`:

- `acquisition-v2`: one physical Sentinel-2 platform/datatake/timestamp scene
  set;
- `observation-v2`: one immutable raw polygon from one v2 acquisition;
- `event-v2`: a durable grouping of raw observations;
- `lineage-v2`: a standalone continuation, split, or merge relationship;
- `persistence-contribution-v2`: at most one contribution for an event and UTC
  observation date;
- `persistence-state-v2`: one chronological manifest generation counted by
  distinct finalized dates; and
- `processing-ledger-v2`: one expected-acquisition row plus a reconciled daily
  summary.

All schemas use JSON Schema Draft 2020-12, fix `schema_version` to `2.0.0`,
reject unknown object fields, require v2 ID prefixes, and require UTC
timestamps ending in `Z`. Every acquisition/run artifact binds the immutable
manifest that admitted it through `run_manifest_id` (`run-v2-` plus 64
lowercase hexadecimal characters) and `run_manifest_sha256`.
`persistence-state-v2` additionally binds a `generation_id` for rebuild
isolation. Its top-level manifest is the most recent transition actually
applied, not a permanent manifest for the whole generation: later dates may be
admitted by later manifests after the watermark. Historical finalized dates,
contributions, and lineage preserve their own manifest binding; the current
event snapshots are resealed to the latest applied manifest.

This package defines no release-manifest v2 and performs no publication. The
later Package 2B.2 consumes this exact processing-ledger contract; it does not
redefine its acquisition unit, statuses, or reconciliation rules.

## Canonical identity framing

Identity inputs are UTF-8 strings joined with ASCII Unit Separator (`U+001F`),
then SHA-256 hashed. Lists participating directly in an identity are unique,
UTF-8 ascending, and joined with line feed (`U+000A`). JSON checksums and
geometry checksums use the same stable RFC 8785 and canonical EPSG:4326
geometry primitives as the runtime.

The identities are:

```text
acquisition_digest = SHA256_US(
  "acquisition-v2",
  collection_id,
  platform,
  datatake_id,
  acquisition_timestamp_utc,
  LF(UTF8_SORT(scene_ids)),
  monitoring_extent_id,
  composite_method_id,
  grid_id
)
acquisition_id = "acq-v2-" + acquisition_digest

observation_digest = SHA256_US(
  "observation-v2",
  acquisition_id,
  canonical_geometry_sha256,
  algorithm_version,
  baseline_version
)
observation_id = "obs-v2-" + observation_digest

origin_event_digest = SHA256_US(
  "event-v2", "origin", first_observation_id
)

split_or_merge_event_digest = SHA256_US(
  "event-v2",
  kind,
  LF(UTF8_SORT(parent_event_ids)),
  LF(UTF8_SORT(trigger_observation_ids))
)
event_id = "evt-v2-" + event_digest

lineage_digest = SHA256_US(
  "lineage-v2",
  relation,
  LF(UTF8_SORT(parent_event_ids)),
  LF(UTF8_SORT(child_event_ids)),
  effective_acquisition_id,
  effective_timestamp_utc,
  LF(UTF8_SORT(trigger_observation_ids)),
  algorithm_version
)
lineage_id = "lin-v2-" + lineage_digest

contribution_digest = SHA256_US(
  "persistence-contribution-v2", event_id, observed_on
)
contribution_key = "pc-v2-" + contribution_digest

ledger_digest = SHA256_US(
  "processing-ledger-v2",
  run_manifest_id,
  run_manifest_sha256,
  monitoring_extent_id,
  algorithm_version,
  canonical_sha256(expected_acquisitions)
)
ledger_id = "pl-v2-" + ledger_digest

state_digest = SHA256_US(
  "persistence-state-v2",
  generation_id,
  run_manifest_id,
  run_manifest_sha256,
  monitoring_extent_id,
  algorithm_version,
  baseline_version,
  canonical_sha256(transition_policy),
  canonical_sha256(finalized_dates),
  canonical_sha256(events),
  canonical_sha256(lineage),
  canonical_sha256(contributions),
  canonical_sha256(watermark)
)
state_id = "state-v2-" + state_digest
```

The ledger identity therefore cannot be reused across monitoring extents or
algorithm versions even when its manifest and expected-acquisition bytes are
otherwise equal. State identity additionally seals its extent, algorithm,
baseline, and complete transition policy. The fixed policy includes a
180-day event-reconnection grace window and minimum overlap fraction `0.05`,
alongside the 15-distinct-date confirmation threshold.

The acquisition identity deliberately excludes the run manifest so that the
same physical datatake keeps its ID in a reviewed rebuild. Manifest bindings
still travel on every document and are validated before records are combined.
Method and grid identifiers have independent version suffixes; the selected
`coverage-ranked-first-valid-v1` method may therefore be bound by an
acquisition-v2 document without becoming a v1 data record. Package 2A.6B
implements that already selected method.
State identity includes finalized dates and the watermark, so a terminal
zero-alert or rejected date advances the state even when it creates no
persistence contribution.

## Physical acquisitions and chronological order

An acquisition is not a calendar date. Its physical grouping key is
`platform + datatake_id + acquisition_timestamp_utc`; all provider-native
scenes for that datatake are retained in sorted `scene_ids`. Method and grid
IDs are identity inputs. The ledger and chronological replay order is always:

```text
(acquisition_timestamp_utc, acquisition_id)
```

The examples contain two datatakes on `2026-04-07`, ten minutes apart. They
have distinct acquisition IDs, occupy two expected-acquisition rows, and may
produce independent raw observations. The daily summary groups the rows only
after preserving those independent records.

## Raw observations, events, and lineage

An observation is immutable and binds exactly one acquisition. Its identity is
independent of later event assignment and persistence: `event_id` and
`contribution_key` are intentionally absent from `observation-v2`. Context may
annotate a raw detection but cannot erase it or change its identity.

An event records its sorted observation, acquisition, contribution, and
incoming/outgoing standalone lineage IDs. It counts
`n_distinct_observation_dates`, not acquisitions. Thus two same-day datatakes
cannot advance persistence twice.

The representative geometry in a persisted event is not a free snapshot. At
least one pairing of its `acquisition_ids` and `representative_geometry_sha256`
must recompute, with the state's algorithm and baseline versions, to an
`observation_id_v2` present in that event's `observation_ids`. This makes the
geometry traceable to an immutable raw observation and rejects geometries that
are internally canonical but disconnected from event evidence.

Origin identity is likewise anchored to first-date evidence. For
`identity_basis.kind="origin"`, `first_observation_id` equals the sole trigger
and must appear in the source observations of the same event's contribution at
`event.first_observed_on`. A later observation therefore cannot be substituted
to re-key an existing origin while its earlier contribution remains in state.

Lineage records preserve all parents, children, trigger observations, and the
effective acquisition. Cardinality is explicit:

- continuation: exactly one parent and one child, with identical parent and
  child IDs (a self-edge);
- split: exactly one parent and at least two triggers/children. Each trigger
  maps to exactly one child whose ID is
  `child_event_id_v2("split", parent_event_ids, [trigger_observation_id])`, and
  that trigger observation belongs to that child; and
- merge: at least two parents and exactly one child. Its ID is
  `child_event_id_v2("merge", parent_event_ids, all_trigger_observation_ids)`,
  and every trigger observation belongs to the merged child.

These equality and membership rules are semantic because JSON Schema cannot
derive and compare hash identities across arrays. The standalone validator
recomputes them against the complete state fixture. Thus a cardinality-valid
but disconnected lineage record is rejected.

All identity-bearing timestamps are normalized, not merely parseable. In
particular, lineage `effective_timestamp_utc`, state `generated_at`, and the
watermark acquisition timestamp must equal the runtime's canonical UTC form:
explicit `Z`, an explicit seconds field, and—when present—fractional seconds without
trailing zeroes. Alternate but equivalent encodings are rejected.

All referenced raw observations remain immutable. A split or merge creates
deterministic child identity and lineage without rewriting parent identity or
discarding superseded history. The example family demonstrates a split;
runtime regressions cover both split and merge.

Event status has exactly two values. An event is `superseded` if and only if
it is the parent of an outgoing `split` or `merge` lineage edge; every other
event is `active`. Continuation lineage therefore does not supersede an event.

## Manifest-bound acquisition ledger

The ledger top level binds `monitoring_extent_id` and `algorithm_version` in
addition to its run-manifest identity. Every embedded expected acquisition
must use that monitoring extent, and every observation supplied for daily
finalization must use that algorithm version.

`expected_acquisitions` embeds the complete sorted acquisition-v2 records
frozen by the run manifest. `terminal_rows` is ordered by the same timestamp/ID
key and contains exactly one row for every expected acquisition. Replaying a
byte-equivalent terminal row is a no-op; a different terminal row for the same
acquisition fails closed.

The seven terminal meanings are preserved from the reviewed v1 vocabulary but
now apply to acquisitions, never dates:

- `complete_with_alerts`;
- `complete_zero_alerts`;
- `rejected_low_coverage`;
- `rejected_quality`;
- `failed_download`;
- `failed_missing_input`; and
- `failed_processing`.

Complete rows have no reason. A nonzero-alert row has one or more sorted
observation IDs. Zero-alert rows explicitly record an empty output. Rejection
and failure rows create no observations and carry a structured reason. The
semantic validator reconciles counts, record checksums, IDs, dates, and
timestamps with the expected acquisition.

One `daily_summary` exists only when every manifest-bound expected acquisition
for its UTC date has one terminal row. It contains the sorted expected and
terminal acquisition sets, all sorted observation IDs, status counts, the
checksum of its terminal rows, and
`persistence_finalization_allowed=true`. Its self-binding digest is canonical
SHA-256 of the summary with `daily_summary_sha256` omitted.

Finalization time is monotonic with terminal evidence. For a UTC date, neither
any contribution's `finalized_at` nor the persistence transition instant may
precede the maximum `terminal_at` across every expected acquisition for that
date. State serializes the transition instant as top-level `generated_at`; for
a non-empty state the validator compares it with the maximum terminal time of
the latest finalized date. This prevents a state from claiming finalization
before its manifest-bound daily input was fully terminal.

For retry and late-arrival comparison, state records this deterministic daily
input digest:

```text
terminal_inputs = [
  {
    "acquisition_id": acquisition_id,
    "status": status,
    "observation_ids": UTF8_SORT(observation_ids),
    "observation_records_sha256": canonical_sha256(
      stable_scientific_projection_of_observation_v2_records
      // ordered by observation_id
      // each record excludes run_manifest_id, run_manifest_sha256, created_at
    ),
    "artifact_sha256": artifact_sha256_or_null,
    "reason_code": reason_code_or_null
  }
  // ordered by acquisition timestamp, then acquisition ID
]

date_input_digest = canonical_sha256({
  "observed_on": observed_on,
  "expected_acquisition_ids": UTF8_SORT(expected_acquisition_ids),
  "terminal_inputs": terminal_inputs
})
```

The digest excludes operational `terminal_at`, free-text reason messages, and
manifest identity. The per-acquisition observation-record hash likewise
excludes `run_manifest_id`, `run_manifest_sha256`, and `created_at`, while
retaining IDs, acquisition timestamp, geometry, area, versions, extent, and
raw-preservation policy. A retry or rolling-window overlap with different
attempt provenance is therefore a no-op when its scientific inputs are
unchanged. It
includes the complete expected acquisition set, statuses, observation IDs,
canonical hashes of stable scientific observation-v2 projections grouped by
acquisition, artifact checksums, and stable reason codes. Consequently, a
change to geometry, area, baseline/algorithm binding, or any other observation
field changes the digest even if an observation ID list were improperly
reused; a late datatake or scientific output change cannot masquerade as a
retry.

## Daily persistence finalization

A persistence contribution is keyed only by `event_id + observed_on`. It is
finalized only from a terminal daily summary and binds that summary's digest,
all source v2 acquisition IDs, and all source v2 observation IDs. Source lists
are unique and UTF-8 sorted. Consequently:

- multiple observations of one event on a date remain visible but yield one
  contribution;
- an exact retry finds the same contribution key and input digest and is a
  no-op;
- a conflicting duplicate fails closed; and
- a late acquisition for a finalized date cannot be appended to that
  generation.

The late acquisition changes the expected acquisition set and daily input
digest. It therefore requires a new `gen-v2-*` generation rebuilt from empty
state in timestamp/ID order. A later manifest containing only dates after the
watermark is ordinary incremental progress within the same generation. The
earlier generation remains immutable audit material.

`persistence-state-v2` embeds complete event and lineage records so the next
chronological match is executable without consulting mutable external state.
It also stores complete contribution records, finalized-date digests, an
acquisition watermark, and integrity hashes for every collection. Empty state
is representable with empty arrays and a null watermark; a zero-alert terminal
date is representable with a finalized date, no contribution, and an advanced
watermark. Persistence tiers are `first_observation`, `candidate`, and
`confirmed`; confirmation requires 15 distinct contributed dates.

Canonical collection order is:

- ledger expected acquisitions and rows: timestamp, then acquisition ID;
- ledger daily summaries and state finalized dates: UTC date;
- state events: event ID;
- state lineage: lineage ID; and
- state contributions: contribution key.

## Replay and no-op rules

Idempotence means identical input produces an identical semantic state. It is
not permission to accept conflicting bytes under one ID.

- Duplicate terminal acquisition row with identical canonical bytes: no-op.
- Duplicate event/date contribution with identical canonical bytes: no-op.
- Duplicate finalized date with the same `date_input_digest`: no-op, including
  a rolling-window manifest with different attempt metadata.
- Reused ID or key with different bytes: reject fail closed.
- Acquisition older than the live watermark: reject; use a new chronological
  generation.
- Newly discovered same-day acquisition after date finalization: its expected
  set changes the digest; preserve the old generation and rebuild a new
  generation.

`last_transition` records only state-producing transitions: `initialized` for
an empty state or `applied` for a non-empty state. A manifest rebuild ends with
the `applied` record of its last finalized date. `no_op_replay` is the external
transition result returned to the caller; it does not rewrite the persisted
state. The returned state, including `last_transition`, remains byte-identical
to the input state. Applied zero-alert batches are valid with
`new_contribution_count=0` and still change the state through the finalized
date and watermark.

## v1 audit-only boundary

V1 schemas and artifacts remain unchanged for audit. They cannot represent
more than one physical acquisition on a date and their contribution identity
uses acquisition rather than UTC date. No v2 document may be serialized into a
v1 schema, v1 persistence state, v1 time-series database, or v1 sidecar.

The v2 schemas require v2 prefixes and reject unknown v1-shaped fields. The
local validator additionally submits every corresponding v2 example to the
available v1 schema and requires rejection. It also rejects v1 identity
prefixes anywhere in v2 examples. There is no compatibility writer or silent
upgrade path.

## Local validation

From the backend repository:

```bash
/opt/anaconda3/envs/araripe/bin/python \
  docs/contracts/phase2a/validate_v2_contracts.py
```

The validator checks all seven schemas and examples, recomputes every fixture
identity and payload hash, verifies manifest/reference coherence, chronological
and UTF-8 ordering, ledger/daily reconciliation, the event/date uniqueness
rule, lineage reciprocity, state integrity, and v1 rejection. It has no network,
R2, GEE, publication, workflow-dispatch, or production dependency.

## Deliberate exclusions

These contracts do not implement `scl-explicit-allowlist-v2`, datatake-scoped
pixel composition, a baseline rebuild, or a Collection 10.1 export. Those are
Packages 2A.6B through 2A.6D. They also do not mutate production, R2, GEE,
workflows, credentials, canonical pointers, or the public site.
