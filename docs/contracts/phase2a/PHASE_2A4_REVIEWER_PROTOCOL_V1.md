# Phase 2A.4 isolated reviewer protocol v1

This local package contains provisional, blinded method-comparison evidence.
It does not contain an accepted observation or event identity, a qualified
human label, a scientific accuracy estimate, or a selected method. Technical
checksum and workflow results establish package integrity only.

## Reviewer eligibility and isolation

Use only the assigned `reviewer-a/` or `reviewer-b/` directory. Do not open or
receive the coordinator directory, candidate registry, true option key, the
other reviewer's work, legacy alert attributes, or desired aggregate totals.
Before the interface reveals a comparison, do not inspect page source, the
`method-evidence/` file tree, or panel files directly. This is a procedural
offline isolation boundary, not an adversarial file-access control system.
The reviewer must attest that they are qualified to interpret the assigned
land-change evidence and that the review is independent.

## Required order for every case

1. Inspect the original Phase 2A.3 evidence. Treat every case and all system
   attributes as provisional audit inputs.
2. Complete the primary change, temporal, and land-cover assessments, including
   every required reason and evidence-sufficiency field.
3. Save and reveal the method comparison. The tool locks the primary fields
   and only then renders the A/B panel paths.
4. Compare opaque A and B alternatives for cloud mask, daily composition, and
   drought adjustment. Each alternative contains the four paired strata formed
   by the other two factors. Do not infer a method name from option order.
5. Record preference, confidence, and reason. `equivalent`, `inconclusive`, and
   `unreviewable` are valid results. Missing or partial evidence must stay
   missing or partial; it is not a zero, no-change result, or permission to
   substitute another case.
6. Export the package-bound review JSON. Its reveal state and locked primary
   snapshot must remain intact for resume or coordinator validation. Do not
   edit checksummed package files or the exported envelope by hand.

The primary assessment must never be revised after method panels are revealed
within that review record. If a material primary error is discovered, stop and
return the exported record to the coordinator for a documented re-assignment;
do not silently reopen or tune the case.

## Decision boundary

A reviewer preference is evidence for a later qualified decision process. It
does not select, activate, lock, replay, publish, or release a method. The
MapBiomas and contextual-signature comparison fields remain Package 2A.5 work
and are not generated or modified here.
