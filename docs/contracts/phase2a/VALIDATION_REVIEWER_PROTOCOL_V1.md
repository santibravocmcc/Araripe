# Phase 2A.3 desktop-review protocol, version 1

## Scope

This package is a usability and method-selection pilot built from provisional
alert audit inputs. It is not a final accuracy study. Do not report its labels
as accuracy, precision, recall, commission, or omission, and do not use them to
activate a method without the later scientific decision gate.

## Reviewer eligibility and independence

Before reviewing, enter a pseudonymous reviewer ID and attest that you have the
remote-sensing/land-change interpretation competence needed for the assigned
cases. Review independently. Do not inspect another review, the coordinator
crosswalk, system confidence, persistence, legacy land-cover label, or method
key before submitting the primary assessment.

## Case order

Use the assigned order. Do not reorder cases by date, place, or apparent
difficulty. Reviewer A assesses every case. Reviewer B assesses only the
separately ordered agreement subset and must not be told which prior judgement,
if any, exists.

## Per-case sequence

1. Confirm that required pre-date and post-date panels load and that dates,
   spatial coverage, clouds/shadows, and registration are usable.
2. Inspect the target at local scale, then the wider context. Use the polygon as
   a location cue, not as proof of change.
3. Inspect the provenance-valid raw location series when available. Do not use
   the quarantined regional SQLite series as location evidence.
4. Inspect independent-sensor corroboration when available. Same-sensor
   Sentinel-2 imagery is supporting evidence, not an independent sensor.
5. Make and save the primary change, temporal-confidence, and land-cover
   assessments before revealing or comparing any blinded A/B method panels.
6. Compare A/B panels only for method families marked available. Record the
   visible evidence and confidence; do not guess when a panel is missing.
7. Record clouds, shadow, haze, seam, misregistration, phenology, fire-like
   appearance, low resolution, or other evidence problems and any tool issue.

## Labels

### Change

- `real_change`: the temporal evidence supports a persistent physical land-
  surface/vegetation change at the target.
- `no_change`: adequate temporal evidence supports no physical change; an
  artifact, phenology, or other non-change explanation is more consistent.
- `uncertain`: required evidence is present, but ambiguity or conflict prevents
  a real-change/no-change judgement.
- `unreviewable`: required evidence is missing, obscured, corrupt, badly
  registered, or otherwise insufficient.

Missing or unusable required before **or** after imagery normally requires
`unreviewable`. Do not replace the case or use an undated basemap as temporal
proof. Independent corroboration may be missing while a case remains
`uncertain`; explain the effect on confidence.

### Temporal confidence

Use `high`, `medium`, `low`, or `not_assessable`. Consider temporal gaps,
seasonal comparability, clouds/shadows, registration, and corroborating dates.
Explain the rating.

### Land-cover context

Choose one of `natural_vegetation`, `anthropic_agriculture_pasture`,
`built_or_extractive`, `water_or_wetland`, `bare_or_other_natural`, `mixed`,
`unknown`, or `not_assessable`, then give confidence and evidence. MapBiomas is
context only and does not determine whether the raw detection exists.

### Contextual signature

Choose `fire_like`, `exposed_soil_or_clearing_like`, `mixed_or_uncertain`, or
`not_assessed`. These are spectral/contextual appearances, not causal findings
or legal conclusions.

## Method comparisons

Complete the primary assessment first. For an available family, compare only
the blinded A/B panels and choose `A`, `B`, `equivalent`, `inconclusive`, or
`unreviewable`, with confidence and reason. A preference is evidence for later
analysis; it does not activate or canonize an option. Families without panels
remain `not_generated_in_2a3`.

## Saving and handoff

Export the JSON after each working session and retain it under the assigned
reviewer slot. Do not edit sample, evidence, assignment, case, manifest, or
checksum files. The coordinator validates review JSON separately and reports
completion/agreement as reviewer-process findings, not scientific accuracy.

The coordinator validation command is:

```bash
/opt/anaconda3/envs/araripe/bin/python scripts/validate_validation_reviews.py \
  <package-root> <reviewer-export.json>
```
