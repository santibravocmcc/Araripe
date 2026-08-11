# Phase 2A.5 isolated reviewer protocol v1

Review the assigned package independently. Do not open or request any file
under `coordinator/`, and do not compare outputs with another reviewer before
submitting the isolated export.

For every case:

1. Inspect the unchanged primary case evidence first.
2. Record the change label and reason, evidence sufficiency, temporal confidence
   and reason, land-cover context/confidence/reason, and the non-causal
   contextual-signature label/reason.
3. Save and reveal the blinded panels. Reveal permanently locks all of those
   primary fields for that case.
4. Assess A/B for all available or partial families. A preference is review
   evidence only; it never selects or activates a candidate.
5. Record incomplete, conflicting, or unusable evidence explicitly. Do not
   replace a case or interpret missing evidence as no change, zero, or failure.

Use contextual labels descriptively. `fire_like` and
`exposed_soil_or_clearing_like` are spectral appearances, not causal findings.
Do not infer cause from a legacy label, land-cover context, visual appearance,
MapBiomas agreement/disagreement, or package-integrity result.

A complete record requires the reviewer pseudonym and both qualification and
independence attestations, every primary field and reason, review duration, and
an evidence-backed assessment for every generated comparison family. Export
the package-bound JSON and return it only through the coordinator's isolated
workflow.
