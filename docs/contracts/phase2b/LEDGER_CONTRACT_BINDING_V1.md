# Phase 2B.2A — the processing-ledger contract this repository consumes

**Binding version:** `1`
**Recorded:** 2026-09-07
**Consumed contract:** `processing-ledger-v3`, contract version **`3.0.0`**
**Production mutation:** none

Package 2B.2 owns publication integration, not a second ledger definition
(canonical roadmap, Package 2B.2, first bullet). This document is the whole of
what this repository decides about the ledger: **which** contract it consumes,
**from where**, and **at exactly which bytes**. Every rule the ledger enforces
is defined by the producer, in the two contract documents pinned below, and is
not restated here.

The machine-readable form of this binding is
[`ledger_contract_pin.json`](ledger_contract_pin.json). It is not
documentation: `src/publication/ledger_binding.py` reads it, verifies every
digest in it, and refuses to build a validator if any artifact has moved. The
digests in §3 and the digests in that file are checked against each other by
`tests/test_ledger_contract_binding.py`, so the prose and the pin cannot
silently disagree.

---

## 1. The decision: the v3 family, not v2

**Chosen: `processing-ledger-v3` at contract version `3.0.0`.**

The roadmap bullet for Package 2B.2 reads *"consume the exact version and
checksum of the **v2** ledger contract/schema and backend producer owned by
Package 2A.6"*. That wording is correct about the mechanism and stale about
the major, because it **predates the Sentinel-2C amendment of 2026-09-01**.
The bullet was written when v2 was the only closed family; the amendment
created v3 afterwards. Reading "v2" as a live instruction today would bind the
publication layer to a contract that cannot represent the data the pilot
already holds.

The basis, verified rather than assumed:

- **The v2 family cannot represent 20 of the 70 retained Phase 2A.4 pilot
  scenes.** Those are Sentinel-2C datatakes (`GS2C_*`) — valid constellation
  data — and the v2 `platform` enum admits only `S2A` and `S2B`.
- **An enum change is a major change** under the Phase 1 compatibility policy
  (`docs/contracts/phase1/DATA_CONTRACTS_V1.md` §9), and consumers never
  silently coerce an unknown enum value. So the v2 family was *not* edited: it
  stands closed at `2.0.0`, and **no `S2C -> S2A` relabelling exists anywhere**.
- **The owner authorized the new major on 2026-09-01**, recorded in
  `config/phase2a_sentinel2c_contract_amendment_v3.json`, and Package 2A.6B.1
  re-issued the whole seven-contract family at major 3.
- **Binding 2B.2 to v2 would leave the publication layer structurally unable to
  account for 20/70 of the pilot's acquisitions**, or would force exactly the
  relabelling the contract forbids.
- **Choosing v3 costs nothing now.** Neither family is wired into the runtime:
  `contracts_v2.py`/`_v3.py`, `ledger_v2.py`/`_v3.py` and
  `persistence_v2.py`/`_v3.py` exist in parallel on the producer branch and
  none of them is imported by `run_detection*.py`. The producer holds tests for
  major separation and for structural equivalence between the two families.

`tests/test_ledger_contract_binding.py::test_a_sentinel_2c_acquisition_is_representable`
holds this decision to its reason: the pinned acceptance fixture must contain
an `S2C` acquisition and must pass the gate. If the binding ever slipped back
to a family that cannot represent `S2C`, that test fails.

`test_a_v2_ledger_is_refused_rather_than_coerced` covers the other direction: a
document declaring `schema_version` `2.0.0` is rejected with
`contract_binding_mismatch`, not read as if it were v3.

## 2. Where the producer lives, and why the artifacts are copied here

Package 2A.6 is **closed and deliberately not merged into `main`**. Its
contracts, schemas and runtime modules live on
`claude/phase2a6d-mapbiomas` at commit
`64fd781f1551a45914a7db32960b923c05056955`. The publication gate runs from
`main`, so it needs the consumed schema present on `main` to validate anything
at all.

The four artifacts in §3 are therefore **byte-identical copies taken from that
commit, at the producer's own paths**. Copying to the producer's paths rather
than to a `phase2b/` mirror is the load-bearing choice:

- there is exactly one copy of the ledger schema in the repository, so nothing
  can fork it (`test_the_ledger_schema_is_vendored_only_at_the_producers_own_path`);
- `src/detection/contracts_v3.py` resolves schemas from
  `docs/contracts/phase2a/schemas/`, so when Package 2A.6 does reach `main`,
  producer and consumer read the *same file*; and
- a later 2A.6 merge that changes the ledger contract lands on these exact
  paths, which either leaves the bytes identical or breaks the pin. The gate
  then stops until the binding is re-reviewed — it does not keep validating
  against a superseded contract.

Only machine-consumed artifacts and the two contract documents are copied. No
producer runtime module is copied: the gate re-derives digests through the
restricted canonicalizer in `src/publication/canonical_json.py`, whose
agreement with the producer is executed against real producer output rather
than asserted.

## 3. The pin

Producer: `santibravocmcc/Araripe`, ref `claude/phase2a6d-mapbiomas`, commit
`64fd781f1551a45914a7db32960b923c05056955`.

| Artifact | Role | SHA-256 | Bytes |
| --- | --- | --- | --- |
| `docs/contracts/phase2a/schemas/processing-ledger-v3.schema.json` | consumed schema | `fde07d7b03b5caf43c01c7a4ee1ab0c0d4f60d2bd71151129ada872cda5f2ad0` | 12130 |
| `docs/contracts/phase2a/examples/processing-ledger-v3.example.json` | producer acceptance fixture | `fd2db1efd8ac79563f498677bb9c8eccf9f32e8e177958e196a8f1e4353a2e87` | 6668 |
| `docs/contracts/phase2a/V3_IDENTITY_PERSISTENCE_LEDGER.md` | contract document | `a6a96c03db02d561eb8f768b143351d102966bff3cfa92cc4c7420fd32b39487` | 5105 |
| `docs/contracts/phase2a/V2_IDENTITY_PERSISTENCE_LEDGER.md` | contract document | `3ea36cfe50a91dd73aa0fb9f7b7100ec27d6f40dc1a849eb2d07a2054aa8f377` | 17780 |

Both contract documents are pinned because both are load-bearing: the v3
document defines the major and its complete delta, and it names the v2 document
as *"the authoritative description of every rule this family enforces"*. A
prose change to either is a change to the contract and must be re-reviewed, not
absorbed.

Re-run the pin at any time:

```bash
/opt/anaconda3/envs/araripe/bin/python scripts/check_processing_ledger.py --binding
```

### What the pin is derived from, and what it is not

The pin records the producer identity, the artifact digests, and two contract
constants the schema does not carry — the identity domain strings
(`acquisition-v3`, `processing-ledger-v3`), their ID prefixes, and the `U+001F`
/ `U+000A` join separators from *Canonical identity framing* in the v2
document.

Everything else about the ledger's shape is **read back out of the pinned
schema**, never copied into the pin or into code: the `schema_version`
constant, the seven-value terminal status vocabulary, and the acquisition,
observation, run-manifest and ledger ID patterns. The schema stays the single
source of truth and its digest protects all of it at once. The pin's declared
version is cross-checked against the schema's own constant, so a pin that
disagrees with its bytes fails closed rather than being believed
(`test_a_pin_that_disagrees_with_its_schema_is_refused`).

### What "fails closed on a silent producer change" means, exactly

Four distinct properties, because they catch different things and only some can
run everywhere:

| Property | Catches | Available |
| --- | --- | --- |
| Pinned-byte integrity | an edited vendored artifact; a 2A.6 merge that changes the contract | always |
| Document binding | a producer that emits a different major | always, at run time |
| Producer-blob agreement, at the pinned **commit** | a pin that was typed rather than taken | only where that commit is in the clone |
| Ref drift, at the producer **branch** | the producer moving away from what we consume | only where that ref is in the clone |

Producer-blob agreement earns its place for one specific reason: on 2026-09-07
a commit message asserted a "verified base" carrying a 40-character SHA whose
last 33 characters were invented from the 7 that were known. Review did not
catch it, because a plausible identifier reads exactly like a checked one. The
pin is machine-checked against the producer's own bytes so that cannot recur
here.

When a revision is absent from the clone, these two checks report
`unverifiable` and say so out loud. They never report success they did not
establish.

## 4. What the consumer requires, and where the producer promises it

Each rule in `src/publication/ledger_gate.py` re-derives a property
`src/detection/ledger_v3.py` already guarantees. The gate re-derives; it does
not re-decide.

| Requirement | Promised by |
| --- | --- |
| Identical run-manifest binding and monitoring extent on every expected acquisition | `ProcessingLedgerV3.__init__` |
| Unique acquisition IDs; unique physical `platform`/`datatake_id`/timestamp keys | `ProcessingLedgerV3.__init__` |
| `(acquisition_timestamp_utc, acquisition_id)` order, by parsed instant | `acquisition_order_key` |
| `observed_on` is the UTC date of the acquisition instant | `create_acquisition_v3` (`observed_on=timestamp[:10]`) |
| `acquisition_id` recomputes from its own identity inputs | `create_acquisition_v3` |
| A terminal row only for an acquisition in the bound manifest | `record_terminal` → `UnexpectedAcquisitionError` |
| At most one row per acquisition; a conflicting row fails closed | `record_terminal` (`self._rows` keyed by acquisition) |
| Row restates the expected acquisition's timestamp and date | `record_terminal` |
| `terminal_at` never precedes the acquisition instant | `record_terminal` |
| `observation_count` equals the listed IDs; IDs unique and UTF-8 ascending | `record_terminal` → `sorted_v3_ids` |
| `terminal_record_sha256` over the row without that field | `record_terminal` |
| One daily summary per UTC date, only when every expected acquisition for it is terminal | `daily_summary` → `IncompleteDateError` |
| Summary sets, union of observation IDs, status recount, and both summary digests | `daily_summary` |
| A serialized ledger is fully terminal and fully reconciled | `_document_unvalidated` → `IncompleteDateError` |
| `ledger_id` recomputes from manifest, extent, algorithm version and expected-set digest | `ProcessingLedgerV3.__init__` |

## 5. Deliberate non-requirements

On 2026-09-07 a fail-closed validator required `first_seen <= last_seen`,
which `update_tracks` never promised, and stopped the production pipeline over
0.10% of rows. A validation that encodes an assumption becomes the outage. The
following are therefore **not** required, each because the producer does not
promise it:

1. **Canonical bytes on disk.** `serialize_v3_document` writes
   `canonical_json_bytes(payload) + b"\n"`, but `generate_v3_examples.py`
   writes `json.dumps(..., indent=2)`. The producer's own committed fixture is
   pretty-printed, so a gate requiring canonical *file* bytes would reject it.
   The gate parses JSON and verifies the embedded digests instead. Pinned as a
   negative result in `test_the_gate_verifies_digests_rather_than_file_bytes`.
2. **A null `artifact_sha256` on rejection and failure rows.** The producer
   requires a checksum for the two success statuses only; for the five
   rejection/failure statuses `artifact_sha256` may be present or null, and the
   schema's conditional branch does not constrain it. The gate does not either.
3. **A uniform `collection_id`, `composite_method_id` or `grid_id` across the
   expected set.** `ProcessingLedgerV3.__init__` checks the manifest binding and
   the monitoring extent, and deliberately not these. Requiring uniformity
   would fail closed on a mixed-method manifest the contract permits.

A fourth boundary is not a non-requirement but a division of labour: the
**pinned schema** owns field shape, types, the status enum, the per-status
output/reason combinations and the `terminal` /
`persistence_finalization_allowed` / `integrity` constants. The gate owns only
what JSON Schema cannot express — comparing arrays, recomputing digests,
checking chronological order, relating counts to lengths, and relating rows to
the manifest-bound expected set. Both layers read the same pinned file, so
re-checking a schema rule would be an unreachable branch that looks like
protection. Several such branches were written and then removed for that
reason.

## 6. Scope boundary — where 2B.2A stops

This slice consumes a ledger. It publishes nothing.

Still Package **2B.2B**: immutable release/staging identity, validation before
green pointer promotion, conditional writes so an older or racing job cannot
replace a newer release, keeping the last complete release live on partial
failure, and explicit representation of zero-alert dates and stale-object
tombstones. Package **2B.2C**: taking operational publication off the git pull
request lane.

> **Delivered 2026-09-07 by Package 2B.2B**, in
> [`GREEN_RELEASE_CONTRACT_V1.md`](GREEN_RELEASE_CONTRACT_V1.md) and
> `docs/implementation/PHASE_2B2B_2026-09-07.md`. Both consequences below were
> answered there and neither answer changed this document: `RELEASE.json`
> stays blue, and the green release is published to R2 rather than to a git
> path, so no `detect_gee.yml` guard was touched. 2B.2C is still open.

Two consequences of stopping here are worth recording, because they are the
first questions 2B.2B will face:

- **`data/timeseries/RELEASE.json` is untouched.** The Package 2B.1 release
  signal keeps its schema `araripe.timeseries.release/1`, its writer
  `scripts/write_release_signal.py` and its consumer
  `site/scripts/check_backend_release.py`. The roadmap has Package 2B.2 absorb
  that signal's role, but absorbing it means replacing the artifact the site
  validates — and the site consumer must migrate in the same change or the
  site fails on the next run. That is a publication change, so it belongs to
  2B.2B, and no part of it is started here.
- **Where a ledger is published is unresolved, and the answer is probably not
  git.** The `detect_gee.yml` publish step refuses to stage anything outside
  `data/timeseries/`; Package 2B.1 used that to make `RELEASE.json` atomic with
  the database for free. Publishing a ledger or manifest at another git path
  would require changing that guard, which is a **blue** workflow file and
  needs explicit human approval. The roadmap's "keep operational data
  publication automatic without PRs or manual merges" points at R2 instead.
  2B.2A changes no workflow.
