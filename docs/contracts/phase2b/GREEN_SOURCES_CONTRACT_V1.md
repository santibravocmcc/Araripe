# The sources and attributions of a green publication

**Contract versions:** `araripe.green.sources/1` (document),
`araripe.green.sources-pointer/1` (pointer), `araripe.green.sources-spec/1`
(the reviewed records), `araripe.green.sources-derivation/1` (the rendering
rule)
**Recorded:** 2026-10-07
**Status:** designed and implemented on a branch; **nothing published**. Publishing
is the owner's decision (`docs/implementation/PHASE_6V_2026-10-07.md` §5).
**Code:** `src/publication/green_sources.py`, `src/publication/sources_pointer.py`,
`scripts/plan_green_sources.py`; records in `config/green_sources_v1.json`;
schema `schemas/green-sources-v1.schema.json`; vectors
`sources_conformance_vectors.json`

---

## 1. Why a document beside the release, and not a field in it

The register asks the release manifest to carry its sources
(`DATA_SOURCE_AND_ATTRIBUTION_REGISTER_2026-07-24.md` §3.3, §6.1; gap A4.1 of
the 2026-10-04 addition). Measured on 2026-10-07 (`tests/test_green_sources.py`,
first block):

1. **A release's id does not read its manifest.** Version 1:
   `release_identity` = f(ledger id, run manifest id and digest, ledger
   digest). Version 3: `reference_release_identity` = f(each member's id and
   the digest of its `release.json`). Adding `sources` to an existing release
   leaves its id — and so its key — unchanged, with different bytes;
   `ConditionalStore.put_if_absent` raises `ImmutableObjectConflict`.
2. **Every release schema is closed.** `green-release-v{1,2,3}` all set
   `additionalProperties: false`; the gate refuses the field before the store
   is reached.
3. **Attribution is a rule that changes.** Between 2026-07-24 and 2026-10-04
   the MapBiomas terms URL began answering 404 and the Esri credit changed
   wording; the lineage of the 2023 crops is an open gate that may close. A
   source list sealed into a release identity makes every correction a new
   release of the same data — a second citable name for the same alerts —
   which is the case `SITE_ARTIFACT_CONTRACT_V1.md` §3 already rules out and
   the land-cover context (`GREEN_CONTEXT_CONTRACT_V1.md` §1) already avoids.

A new release version (`release/4`) whose identity includes the sources was
compared and not recommended (PHASE_6V §3): it leaves the live `rel-g3-`
release without sources forever, re-mints the same history under a second id,
and changes the schema every consumer reads.

## 2. Identity

`sources_id = "src-g1-" + SHA256_US("araripe.green.sources.identity.v1",
release_id, context_id or "", spec_sha256)`, where `spec_sha256` is the
canonical-JSON digest of the **sealed** spec: the records of
`config/green_sources_v1.json`, minus the context records when the document
covers no context.

The document is a function of its identity inputs: the release id fixes the
release's bytes (and so its dates and ledgers), the context id fixes the
context, the spec is in the document. That holds **only while the rendering
rule is fixed**, so the rule is named in the spec (`derivation`) and pinned by
the vectors: two full documents, byte for byte. A change to how a document is
rendered must bump `derivation` — a new id — never produce new bytes under an
old one. The vectors embed their own copy of the spec, so editing the records
does not touch them.

## 3. Layout

    sources/<sources-id>/sources.json    the document
    sources/current.json                 mutable, compare-and-swap (sources_pointer.move)

One small document per (release, context, spec); nothing is copied. The
pointer is not beside the release pointer: that namespace has one writer
(`tests/test_promotion_history.py`, H2), and
`tests/test_green_sources.py` asserts, on the AST, that `sources_pointer.py`
names no key under `pointers/`.

Pointer: `{schema, sequence, sources_id, release_id, context_id, sources_path,
sources_document_sha256, written_utc, written_by}`. Nothing calls
`sources_pointer.move` yet.

## 4. The document

`{schema, sources_id, sources_prefix, release_id, context_id, spec,
spec_sha256, derived, attribution}`, closed (`additionalProperties: false`).

- **`spec`** — the reviewed records. Each carries provider, dataset, edition or
  collection and year, resolution, official URL, licence (name and link),
  terms URL, origin URL, access date, source checksum, the crop it was read
  through (path, bytes, sha256), the citation in the provider's own format,
  the modification made, the alert properties it fed (`applies_to_fields`),
  and `open_gaps`.
- **`derived`** — `detection.collection_ids` (every `collection_id` in the
  ledgers' expected acquisitions), `observation_years` (years of the release's
  dates with at least one usable acquisition), `baseline_years` (from the
  record), `notice_years` (`first–last` of their union), and the release's
  coverage.
- **`attribution`** — one entry per record, in spec order: `{source_id,
  applies_to: release | context, text, licence, modified: true}`. For
  Sentinel-2 the text is the Copernicus notice with `notice_years`; for
  MapBiomas it is the citation. This list is what a consumer shows.

### What is proven and what is asserted

| record | role | how `check_sources` binds it |
| --- | --- | --- |
| Sentinel-2 L2A | `detection` | **derived**: the ledgers must be the release's own, in order (`ledger_id`, `document_sha256`), and must read exactly the declared collection |
| MapBiomas 10 m Coleção 2 (beta) 2023; legacy ≈300 m 2023 | `release_annotation` | **asserted**: no identity input of a release seals them. `plan_green_sources.py` refuses unless each record matches the replay freeze (path, bytes, baseline years, collection) and the tracked crop (sha256) |
| MapBiomas 10 m Coleção 4 2025; Coleção 11 2025 | `context_annotation` | **bound to the context**: collection, year, origin URL, crop sha256 and source MD5 must equal the context recipe's |

### Unknown provenance is written down, not omitted

Register §6.4. A required field may be `null` only when `open_gaps` names it
(`"<field>: <reason>"`); a gap may not name a field that has a value, nor a
field the role does not have; source id, licence, crop, citation and the
notice can never be gaps. The shipped records carry seven gaps, all on the two
2023 crops (origin URL, access date and national checksum of both; the
collection of the ≈300 m crop).

## 5. What `check_sources` refuses

A wrong schema or any schema violation; a document naming another release, or
a context other than the one offered (`context_mismatch`, including a context
document checked without a context); an invalid sealed spec (codes above);
2025 records that differ from the context recipe (`context_binding`); ledgers
that are not the release's (`ledgers_mismatch`) or that read another
collection (`detection_collection`); and any key whose value is not what the
inputs determine (`does_not_derive`) — so no line of attribution can be edited
by hand.

## 6. Exposure and retention today

`sources/` is classified by neither policy, so it is **private** in the
delivery boundary and **review, never eligible** in retention — both asserted
by test. A document can therefore be written to staging without becoming
public or deletable. Serving it is a delivery-boundary change (`delivery/3`:
`/data/green/sources.json`, the same rule as the context — served only while
the pointer names the live release **and** the live context) and a site route
change; both are the next package, not this contract.

## 7. What this contract does not do

- It changes no release, ledger, run, context, schema of any of them, or the
  detector's annotation.
- It does not state the licence of the project's own data products (owner
  decision, PHASE_6T §4.5).
- It covers what the green publication serves. The site's basemaps, terrain,
  rainfall and boundaries keep their credits on the page (`observatorio-site`
  `src/js/creditos.js`).
- It carries no accuracy claim (Phase 5).
