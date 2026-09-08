# Phase 2A.5 context-comparison contract v1

Status: technical comparison package only. All MapBiomas, strong-subset, and
contextual-signature choices remain provisional until qualified review and an
explicit acceptance record resolve them.

## Immutable inputs

The package derives from the provenance-bound, provisional 60-case Phase 2A.3
pilot and the exact provisional Phase 2A.4 blinded derivative. The generator
validates both before copying any material. Phase 2A.4's candidate registry,
coordinator blinding map, drought
candidate, cloud-mask candidates, daily-composition candidates, reviewer
assignments, original case evidence, and existing opaque comparison metadata
are preserved byte-for-byte. They are not parsed to construct the new A/B
mapping and are never exposed through the reviewer trees.

The new inputs are the fixed Phase 2A.5 context-candidate registry, the
versioned regional-context manifest, and a checksum-complete 60-case evidence
artifact. The evidence checksum inventory is the coordinator-only key for an
order-invariant, exactly balanced 30/30 A/B mapping in each new family.

## New comparison families

- `mapbiomas` compares the two fixed natural-vegetation strong-subset rules.
- `contextual_signature` compares the two fixed, non-causal aggregation rules.

Reviewer material contains only opaque A/B identifiers and generic evidence
availability. True candidate IDs, numeric thresholds, class mappings, raw
MapBiomas summaries, sample IDs, and the coordinator mapping remain under
`coordinator/`.

The package retains all raw valid detections and every missing or partial case.
MapBiomas annotation and strong-subset membership cannot erase, invalidate, or
relabel a detection and are not an omission or recall reference. Contextual
signatures do not assert fire, mechanical clearing, or any other cause.

## Decision boundary

Successful construction and validation establish only deterministic technical
integrity. They do not produce a qualified label, accepted observation/event
identity, accuracy estimate, threshold choice, frozen contextual-signature
policy, wording approval, Phase 2A.4 method decision, release, replay, or Phase
2A exit-gate closure.
