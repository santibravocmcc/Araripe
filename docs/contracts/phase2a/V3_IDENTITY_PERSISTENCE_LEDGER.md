# Phase 2A.6B.1 v3 identity, persistence, and ledger contracts

**Contract version:** `3.0.0`

**Scope:** the same local candidate-generation identity, lineage, persistence,
and manifest-bound acquisition accounting as the v2 family, re-issued as a
coherent new major so the Sentinel-2C platform is representable

**Production mutation:** none

## Why a new major exists

The 2026-09-01 owner authorization
(`config/phase2a_sentinel2c_contract_amendment_v3.json`) corrects a
pre-replay representation gap: 20 of the 70 retained Phase 2A.4 pilot scenes
are Sentinel-2C (`GS2C_*` datatakes), valid constellation data that the
closed v2 contracts cannot represent (`platform` enum `S2A`/`S2B`). Under the
Phase 1 compatibility policy (`docs/contracts/phase1/DATA_CONTRACTS_V1.md`
§9) an enum change is a **major** change and consumers never silently coerce
an unknown enum, so the v2 (`2.0.0`) family is not edited and no
`S2C -> S2A` relabeling exists anywhere. Instead the whole seven-contract
family is re-issued at major 3.

## Inheritance and the exact delta

`V2_IDENTITY_PERSISTENCE_LEDGER.md` remains the authoritative description of
every rule this family enforces — canonical identity framing, physical
acquisitions and chronological order, raw observations/events/lineage, the
manifest-bound ledger, daily persistence finalization, and the replay/no-op
rules. The v3 family changes none of those semantics. The complete delta is:

- `platform` accepts `S2A`, `S2B`, and `S2C`; any other unit (for example a
  future Sentinel-2D) fails closed until a recorded review adds it;
- every identity domain string moves to the v3 major
  (`acquisition-v3`, ..., `processing-ledger-v3`), so a v3 identity can never
  collide with a v2 identity even for byte-identical physical inputs;
- every ID prefix moves to the v3 major (`acq-v3-`, `obs-v3-`, `evt-v3-`,
  `lin-v3-`, `pc-v3-`, `state-v3-`, `pl-v3-`, `run-v3-`, `gen-v3-`);
- `schema_version` is fixed to `3.0.0`; and
- the persistence transition policy declares
  `"legacy_serialization": "v1_v2_forbidden_audit_only"`, making explicit
  that neither v1 nor v2 is a serialization target for v3 data.

That this is the *complete* delta is executable, not prose:
`tests/test_v3_structural_equivalence.py` holds the enumerated replacement
pairs and requires every v3 runtime module, the standalone validator, and
every v3 schema to equal its byte-identical v2 source after applying exactly
those pairs. Any other divergence fails the pytest gate.

## Artifacts

- Runtime: `src/detection/identity_v3.py`, `src/detection/ledger_v3.py`,
  `src/detection/persistence_v3.py`, `src/detection/contracts_v3.py`, and the
  Package 2A.6B producer re-bound to v3 in
  `src/detection/composition_run_v3.py` (the mask and composition science in
  `src/processing/` is consumed unchanged).
- Schemas: `schemas/*-v3.schema.json` (seven).
- Examples: `examples/*-v3.example.json` (seven), regenerated through the v3
  runtime by `generate_v3_examples.py` rather than text-ported, because every
  identity changes with the major. The example family reproduces the v2
  fixture scenario — two same-day physical datatakes whose second datatake's
  observations split the origin event — with the second datatake deliberately
  Sentinel-2C. The pytest gate requires the committed examples to equal the
  generator's output byte for byte.
- Standalone validator: `validate_v3_contracts.py`, the mechanical port of
  the v2 validator plus a v2-isolation section: every v3 example must be
  rejected by all seven v2 schemas and by the four available v1 schemas, and
  may contain no `-v1-` or `-v2-` identity.

Local validation:

```bash
/opt/anaconda3/envs/araripe/bin/python \
  docs/contracts/phase2a/validate_v3_contracts.py
```

## v1 and v2 audit-only boundary

V1 remains exactly as the v2 contract described it. The v2 family now holds
the same status one major up: its schemas, examples, validator, and runtime
modules are byte-unchanged and still executable for audit, its validator
still passes, and no v3 document may be serialized into a v2 (or v1) schema,
state, or writer. Cross-major rejection is enforced from both sides by the
prefix and `schema_version` guards and is regression-tested in
`tests/test_v3_major_separation.py`; the runtime guards added by Package
2A.6A for v1 writers are inherited unchanged.

The science selected by the 2026-08-11 decision record is untouched:
`scl-explicit-allowlist-v2` and `coverage-ranked-first-valid-v1` are method
identifiers with their own version axis and are bound by acquisition-v3
documents exactly as before, with the same fail-closed policy for missing,
unexpected, or unreviewed SCL and processing-baseline metadata.

## Deliberate exclusions

This amendment implements no baseline rebuild, no 2026 replay, no MapBiomas
Collection 10.1 export, no persistence integration with production paths, and
no mutation of production, R2, GEE, workflows, Environments, or credentials.
Package 2A.6C remains not started and gated on this amendment's local gates,
which are part of the standard backend pytest run.
