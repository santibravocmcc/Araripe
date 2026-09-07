# Phase 2B.2B — the green release and the green staging pointer

**Contract version:** `araripe.green.release/1`, `araripe.green.pointer/1`
**Recorded:** 2026-09-07
**Production mutation:** none

Package 2B.2A bound the contract this repository *consumes* and stopped at
consumption. This document is the contract this repository *publishes*: what
an immutable green release is, what must hold before the green staging pointer
may move, and what deliberately is not claimed.

Machine-readable forms:
[`schemas/green-release-v1.schema.json`](schemas/green-release-v1.schema.json)
and [`schemas/green-pointer-v1.schema.json`](schemas/green-pointer-v1.schema.json).
They own *shape*; `src/publication/green_release.py` and
`src/publication/atomic_publish.py` own only the relations JSON Schema cannot
express. Re-checking a shape rule in code would be an unreachable branch that
looks like protection — the division Package 2B.2A reached by deleting code
(`docs/implementation/PHASE_2B2A_2026-09-07.md` §4).

---

## 1. The object layout

    releases/<release_id>/release.json    the manifest, written LAST
    releases/<release_id>/ledger.json     the ledger it was published from
    releases/<release_id>/<logical path>  its products
    pointers/green/current.json           the ONLY mutable object

Everything under `releases/` is write-once. `pointers/green/current.json` is
the single mutable object, and every write to it is a compare-and-swap. All of
it lives in `araripe-v2-staging`; `assert_staging_target` refuses
`araripe-cogs` by name and refuses any endpoint but the approved account one,
*before* a credential is read.

## 2. Identity is derived, never minted

    release_id = "rel-g1-" + SHA256_US(
        "araripe.green.release/1",
        ledger_id, run_manifest_id, run_manifest_sha256, document_sha256)

`SHA256_US` is the contract's own unit-separator identity primitive
(`V2_IDENTITY_PERSISTENCE_LEDGER.md`, *Canonical identity framing*), reused
rather than reinvented; the domain string only stops a release identity from
colliding with an acquisition or ledger identity. **No clock, no run id, no
actor, no counter.** `document_sha256` alone would determine the release — the
manifest and ledger identities are joined in so the inputs read as what they
are.

Three properties follow, and the immutability argument is all three together:

1. **Idempotence.** The same ledger maps to the same prefix, so republishing is
   a byte-exact no-op rather than a conflict.
2. **Immutability by construction.** Any change to the ledger — one row, one
   digest — lands on a *different* prefix. An existing release cannot be
   rewritten because there is no way to address it with different content.
3. **Defence behind the precondition.** Even a conditional write that failed to
   guard could only overwrite byte-identical content, because the bytes and the
   prefix are functions of the same inputs.

Property 3 does not cover everything, and the gap is exactly what the
conditional write is for: a `date_product` is computed by the publisher, not
sealed by the ledger, so the same ledger with a different renderer yields the
same prefix and different bytes. `If-None-Match: *` catches that and fails
closed (`ImmutableObjectConflict`).

### The manifest carries no publication provenance

No `built_utc`, no run id, no actor. Those describe a promotion *event*, which
is the pointer's subject, and putting them in the manifest would make its bytes
non-reproducible and destroy property 1. The manifest is stored as canonical
JSON plus a newline, so its bytes are a function of its content.

**Requiring canonical file bytes here is legitimate and was refused for the
ledger, and the difference is authorship.** The ledger's file bytes come from
the producer, whose example generator writes `json.dumps(indent=2)`
(`LEDGER_CONTRACT_BINDING_V1.md` §5, non-requirement 1). These bytes come from
`src/publication/green_release.py`. A validation may require what its own
producer promises — and only that.

The stored `ledger.json` is re-encoded canonically rather than copied
byte-for-byte, for the same reason: the producer's digests cover the parsed
structure and its runtime writer `serialize_v3_document` emits exactly these
bytes, so two differently formatted files holding the same ledger are the same
release and store the same bytes.

## 3. What must hold before the pointer moves

`check_green_release` **requires the ledger** and re-runs
`check_processing_ledger` on it, from the bytes stored beside the release. The
roadmap bullet — *validate schemas, checksums, expected dates, state watermark
and product completeness* — is therefore composed with the Package 2B.2A gate,
not duplicated over it.

| Requirement | Where it is enforced |
| --- | --- |
| Schemas | the two pinned schemas; the ledger's own pinned schema, again |
| Ledger checksums, completeness, reconciliation | `check_processing_ledger`, re-run at promotion |
| Release identity and prefix | recomputed from the ledger's seals |
| The stored ledger is the validated ledger | canonical re-encoding compared by digest and length |
| **Expected dates** | every reconciled UTC date appears exactly once in `dates[]`, in chronological order, and no date outside the reconciled set appears |
| Per-date accounting | `status_counts`, `observation_count`, `max_terminal_at`, `daily_summary_sha256` and the classification all recomputed from the ledger's daily summary |
| **Product completeness** | an `acquisition_artifact`'s `sha256` must equal its ledger row's `artifact_sha256`; a date reporting `alerts` must publish at least one object; every declared object is claimed by exactly one date and every claimed path is declared |
| **State watermark** | `finalized_through` and `finalized_dates` are derived from the ledger, never supplied |
| Objects actually present | `verify_release` re-reads every declared object and compares size and checksum |

**Where "expected dates" comes from, and why not from a calendar.** The
expected dates are the UTC dates of the manifest-bound expected acquisitions —
the ledger's own expected set. A revisit calendar was rejected: it would be a
second source of truth and would fail closed on legitimate gaps (cloud,
rejected scenes) that the ledger already represents as terminal states.

**Where the watermark is read.** `finalized_through` is the latest UTC date
whose every manifest-bound acquisition is terminal and whose daily summary
reconciles — which is precisely what the ledger already establishes, and what
its `persistence_finalization_allowed` marks per date. It is derived, so a
caller cannot overclaim it.

## 4. Deliberate non-requirements

Following `LEDGER_CONTRACT_BINDING_V1.md` §5 and for the same reason: on
2026-09-07 a validator required `first_seen <= last_seen`, which
`update_tracks` never promised, and stopped the production pipeline over 0.10%
of rows. A validation that encodes an assumption becomes the outage.

1. **No claim about the persistence state's contents.**
   `persistence_state_sha256` and `persistence_state_bytes` are provenance
   only. In particular **`max(last_seen)` is not a watermark**:
   `update_tracks` overwrites `last_seen` with the date being processed, and a
   run re-covering the `SEARCH_DAYS_BACK = 16` window can move it *backwards*
   (`tests/test_update_tracks.py::test_last_seen_can_move_backwards`). Nothing
   here asserts monotonicity of it, and nothing reads the production state.
2. **No requirement that every sealed artifact be published.** For the two
   complete statuses the contract guarantees a checksummed artifact *exists*;
   it does not promise the publication includes it, and a release of
   date-level products only is a shape the contract permits. The CLI reports
   the coverage and offers `--require-sealed-artifacts` for pipelines that do
   produce one artifact per acquisition.
3. **`artifact_sha256` is never read for the five rejection and failure
   statuses.** The schema leaves it unconstrained there
   (`LEDGER_CONTRACT_BINDING_V1.md` §5, non-requirement 2), so an object may
   not claim provenance from such an acquisition and its value is not even
   compared.
4. **A ledger file need not be canonical on arrival.** Inherited unchanged
   from the binding; see §2 for why the *stored* copy is canonical anyway.
5. **No ordering claim from `generated_at` or `terminal_at`.** They record
   when processing happened, not what the data covers. See §6.

## 5. Zero-alert dates and the four kinds of day

`complete_zero_alerts` is a first-class terminal state in the consumed
contract, so the publication layer must preserve the distinction rather than
guess it. Both axes are derived from the pinned schema's own per-status
conditionals (`ledger_binding.pinned_status_semantics`), not from a second
vocabulary:

* `artifact_sealing` — the statuses whose branch constrains
  `output.artifact_sha256` to a sha256. Those acquisitions are *usable*.
* `alert_bearing` — the statuses whose branch requires
  `output.observation_count >= 1`. A date with one of those holds alerts as a
  matter of contract.

| `alert_state` | `coverage` | Means |
| --- | --- | --- |
| `alerts` | `complete` | fully observed, alerts found |
| `alerts` | `partial` | alerts found, and part of the extent was not observed |
| `zero_alerts` | `complete` | fully observed, and nothing was found — a positive observation of absence |
| `zero_alerts` | `partial` | nothing found where it could be looked, and part could not be looked at |
| `no_valid_coverage` | `none` | nothing was observed at all |

Collapsing rows 3–4 into row 5 would make a clear sky and a cloud bank look
alike. Collapsing row 4 into row 3 would claim a quiet day the data does not
support. `classify_date` is a total function over the contract's vocabulary,
and `no_valid_coverage` ⟺ `coverage == "none"` is asserted so the one place the
two axes overlap cannot drift.

## 6. Two axes, deliberately not conflated

* `sequence` counts pointer **writes**. It increases by one on every accepted
  write, promotion and rollback alike.
* `coverage.last_observed_on` says what **data** the release covers.

**A replay of an old window is a later write of older data.** Any recency test
based on write order, sequence or clock would wave it through, so `promote`
compares *coverage* and refuses to move to strictly older coverage
(`coverage_regression`). Equal coverage is not a regression — that is the
normal case of a re-run that produced a better release.

There is **no override flag** on `promote`. Going backwards is `rollback`, a
named operation that appears as `action: "rollback"` in the pointer, with
`rolled_back_from` recorded. "Rollback" is therefore the general name for a
deliberate non-monotonic move, and it is also how an operator promotes older
coverage on purpose. `rollback` re-reads and fully revalidates its target from
the store, including its ledger, and verifies every object is still present:
the pointer may only ever name a release that is still complete.

## 7. Conditional writes, and what R2 actually offers

* `If-None-Match: *` for every write-once object. `412` is not yet an error:
  the bytes are read back, an identical object is an idempotent no-op, and a
  differing one fails closed.
* `If-Match: <etag>` for the pointer. A failed precondition **is never
  retried** — the decision behind the write was made about a version that is no
  longer live.
* The first pointer write uses `If-None-Match: *` but does *not* forgive an
  identical-bytes `412`: for a mutable object that is a lost race, not
  idempotence.

Both are R2 extensions of the S3 API failing with `412 PreconditionFailed`
(`https://developers.cloudflare.com/r2/api/s3/extensions/`).

**Measured 2026-09-07 — no custom-header workaround is needed for these two.**
The Package 2B.2B briefing carried Cloudflare's recipe for per-request custom
headers: register `before-parameter-build.s3.PutObject` and
`before-call.s3.PutObject` and move the header into the request context,
because botocore's parameter validation rejects unknown arguments. That
warning is true — verified, and pinned as a negative result in
`test_an_arbitrary_extra_argument_really_is_rejected` — but it does not apply
here. The Cloudflare example predates AWS S3's own conditional writes, and in
botocore 1.42.42 `IfMatch` and `IfNoneMatch` are **native members of the
`PutObject` input shape**. They travel as ordinary parameters and this package
reaches into no botocore internals. `require_conditional_write_support` asks
the loaded service model whether the members exist *before* any object is
touched, so an older botocore refuses to publish rather than issuing an
unconditional `PutObject` — the one failure mode the design exists to prevent.

Destination conditions on `CopyObject` (`cf-copy-destination-if-match` and
siblings) are in **beta**, and nothing here is built on them.

**An ETag is a compare-and-swap token, never a checksum.** From a single
`PutObject` it is the MD5 of the body; from a multipart upload it is the MD5 of
the concatenated part MD5s with a `-N` suffix. It is therefore never comparable
to the scientific `sha256` a release declares. This package reads it, keeps it,
hands it back in `If-Match`, and parses nothing.

## 8. Tombstones: staleness is a relation, not a property

A tombstone is recorded on the **pointer**, not in either manifest, because a
release is immutable and is built before anything is known about what it will
supersede — and what counts as stale depends on which release is live when it
is promoted. The pointer is the only object that knows both.

| Reason | Means |
| --- | --- |
| `absent_from_successor` | the successor publishes nothing at that logical path |
| `superseded_content` | same logical path, different bytes |
| `date_reclassified` | the successor reports a different `alert_state` for that UTC date |

`date_reclassified` is the one that matters scientifically: a replay that
retracts a date's alerts, or turns an observed quiet day into one nobody could
observe, must never be silent. A date that published no object still records
its reclassification against the superseded manifest, because it retires a
*claim* even when it retires no bytes.

**Nothing is deleted.** `ConditionalStore` has no delete operation and no
unconditional put. Retention and lifecycle are Package 2B.3.

## 9. Why a compare-and-swap when the lane is already serialized

`docs/operations/GREEN_CONCURRENCY_LANES.md` lane 3 gives at most one running
promotion. The CAS sits *behind* that, not instead of it: concurrency groups
are per repository, so a local operator run, a re-dispatch from another ref, or
a future second promoter is outside the lane entirely.

## 10. Scope boundary — where 2B.2B stops

**`data/timeseries/RELEASE.json` is untouched and stays blue.** The Package
2B.1 signal keeps its schema `araripe.timeseries.release/1`, its writer
`scripts/write_release_signal.py` and its consumer
`site/scripts/check_backend_release.py`, which validates only that schema and
mentions no ledger, manifest or contract. The green release is built beside it.
The blue signal serves the blue lane and the green release serves the green
lane; the two meet at the **Phase 6** cutover. The site repository is not
touched by this package.

Still open, by package:

* **2B.2C** — taking operational publication off the git pull-request lane.
  Where a ledger is published in the automated flow is still unresolved; the
  `detect_gee.yml` publish step refuses to stage anything outside
  `data/timeseries/`, and changing it is a blue workflow change.
* **2B.3** — the private/public R2 boundary, least-privilege credentials, the
  staged `/data/...` route, and retention and deletion policy.
* **2B.4** — the green site artifact and deployment.
* **The protected promotion identity.** Moving the pointer from CI needs an R2
  identity that is *not* the green candidate identity and not any locally held
  credential. Creating a GitHub Environment is a repository configuration
  change and is owner-approved work. `v2_promotion_lane.yml` therefore runs
  everything that needs no credential and stops, naming that capability.
