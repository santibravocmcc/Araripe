# Phase 2B.4B — the site alert index: who produces it, and what its numbers mean

**Contract version:** `araripe.site.alert_index/1`
**Statistics policy version:** `1`
**Recorded:** 2026-09-08
**Production mutation:** none
**Verified base:** backend `origin/main` `ed6c253493ea0ef71d1abb70831a39b45f647e7e`,
site `origin/main` `32f90494dfb1af1f8c0b7d826548045115958f62`

Package 2B.4A built the route that serves a green release
(`worker/data_route.js`, 19 conformance vectors). This document answers the
question that package left open and that the 2B.4B briefing calls its central
decision: **the site reads `/data/alerts/manifest.json`, the green release does
not contain that document, so who produces it?**

Machine-readable forms:
[`schemas/site-alert-index-v1.schema.json`](schemas/site-alert-index-v1.schema.json)
owns *shape*; [`site_artifact_conformance_vectors.json`](site_artifact_conformance_vectors.json)
owns the *policy*, across two implementations in two repositories;
`src/publication/site_artifact.py` owns only the relations neither can express.

---

## 1. The decision

**A green preparation step in the site repository composes the index from the
objects the live release declares. The index is a derived build artifact, not a
release object, and not a committed file.**

The statistics *definitions* live here, in the backend, versioned as
`STATS_POLICY_VERSION`. The site executes them and is checked against the
vectors. That is the same division Package 2B.3 and 2B.4A reached for the
delivery boundary: policy in one repository, an adapter in the other, vectors
as the referee — *"Não invente política no Worker."*

This is the briefing's option 3, and it was reached by ruling out option 1
on measured grounds rather than by preference. Option 2 (the site derives the
index from `release.json`) was ruled out by schema.

## 2. Why not option 2 — the ledger does not seal these numbers

Measured against the pinned schemas, not inferred:

| The index needs, per date | Does the ledger seal it? |
| --- | --- |
| `count` — alert features with an areal geometry | **No.** The ledger seals `observation_count` per *acquisition*; a date has several, and the index counts features after the geometry filter. |
| `area_ha` | **No.** |
| `high` / `medium` / `low` | **No.** `status_counts` counts the seven *scene* terminal statuses (`complete_with_alerts`, `rejected_quality`, `failed_download`, …), not feature confidence. |
| `first_obs` / `candidate` / `confirmed` | **No.** These bin `persistence_count` per feature. |
| `strong` | **No.** Needs `confidence_label`, `persistence_count` *and* `lc_natural_frac_10m`. |
| `pcount_max` | **No.** |

Sources: `docs/contracts/phase2a/schemas/processing-ledger-v3.schema.json`
(`$defs.status_counts`, `$defs.terminal_output`, `$defs.daily_summary`) and
`docs/contracts/phase2b/schemas/green-release-v1.schema.json`
(`$defs.release_date`). **Every number in the index comes from reading alert
features**, which is what `site/scripts/prepare_data.py` does today. So the
briefing's warning applies in full: the statistics are not derivable from the
sealed material, and any option that avoids reading the features is impossible,
not merely expensive.

## 3. Why not option 1 — an immutable prefix and a mutable-by-plan policy

Publishing the index as a `date_product` would put it under the release's
checksum. Three findings rule it out.

**a. The release prefix is a function of the ledger alone, so a re-render
collides with itself.** `green_release.release_identity` derives `release_id`
from `ledger_id`, `run_manifest_id`, `run_manifest_sha256` and
`document_sha256` — and `document_sha256` is documented in that function as
"a digest over the whole ledger body", not a digest of the release document.
`GREEN_RELEASE_CONTRACT_V1.md` §2 states the consequence itself: *"a
`date_product` is computed by the publisher, not sealed by the ledger, so the
same ledger with a different renderer yields the same prefix and different
bytes. `If-None-Match: *` catches that and fails closed
(`ImmutableObjectConflict`)."*

**b. The thresholds are mutable by plan.** Roadmap Phase 5 validates the
accepted defaults and says *"Change a default only with recorded qualified
evidence"*; Phase 3 regenerates *"persistence tiers, strong subsets,
statistics"*. Combining (a) and (b): the first threshold change after a
release is published would make every affected release unrepublishable. That
is a designed-in conflict, not a risk.

**c. A `date_product` names one date; the index spans all of them.**
`green-release-v1.schema.json` requires `provenance.observed_on` on every
object and forbids `acquisition_id` on a `date_product`. The index carries
`runs[]` for every date in the release plus `totals`, `last_run` and
`pcount_max`. Published as a single `date_product` it would have to name one
`observed_on` and be wrong about the other 39.

**The briefing anticipated (c) implicitly and asked not to decide by its own
sentence. It was not decided by that sentence: (a) is read out of
`green_release.py`, (b) out of the roadmap, and (c) out of the schema.**

## 4. What replaces the checksum

A sealed object would have supplied integrity for free. A derived one needs an
argument, and it is **reproducibility**:

1. **The inputs are immutable.** The release prefix is write-once and the route
   resolves only what the live release declares — a path is served *"porque o
   manifesto o lista, nunca porque parece seguro"*.
2. **The function is pure.** `run_statistics` and `compose_alert_index` read no
   clock, no network and no object store.
3. **The rounding is contractual.** `area_ha` is rounded once per run, and
   `totals.area_ha` sums the *already rounded* values. Rounding later would
   give a different total from the same release, so the order is pinned by
   vector, including the cross-language trap that 7.25 is 7.2 under Python's
   `round` and 7.3 under JavaScript's `toFixed(1)`.
4. **The policy version travels in the document.** `stats_policy_version` is
   the cheap version of the provenance a sealed object would have carried: two
   indexes built by different threshold generations are distinguishable.

So two builds of one release produce identical bytes, and a reviewer can
re-derive the index instead of trusting it.

## 5. Totals are aggregations, and that is load-bearing

Every field of `totals` is a function of `runs[]` and nothing else, and every
per-run row carries its own `pcount_max` so that this holds. The consequence is
the one that matters operationally: **a consumer can verify the whole document
without reading a single one of the 429,946 features.**

`prepare_data.py` tracked one global `max_pcount` across all runs. Carrying it
per run and taking the maximum is only a safe replacement if the two agree
including the floor, so that equality is asserted rather than assumed
(`tests/test_site_artifact.py::test_the_per_run_maximum_aggregates_to_the_old_global_maximum`).

## 6. The statistics policy, version 1

A **port** of what `site/scripts/prepare_data.py` computes at site `origin/main`
`32f90494dfb1af1f8c0b7d826548045115958f62`, not a redesign. The published
numbers must not move because the producer changed.

| Constant | Value | Meaning |
| --- | --- | --- |
| `CONFIRMED_MIN_SIGHTINGS` | 15 | streak at or above which an alert is *confirmed* |
| `CANDIDATE_MIN_SIGHTINGS` | 2 | at or above which it is a *candidate*; below is a first observation |
| `STRONG_MIN_NATURAL_FRACTION` | 0.5 | MapBiomas 10 m natural fraction floor for strong membership |
| `STRONG_CONFIDENCE_LABEL` | `high` | the label strong membership requires |
| `CONFIDENCE_LABELS` | high, medium, low | any other label, including a missing one, counts as `low` |
| `COUNTED_GEOMETRY_TYPES` | Polygon, MultiPolygon | so `count` is **not** `len(features)` |
| `MIN_PCOUNT_MAX` | 1 | floor, so an empty run does not collapse the UI slider range |

The streaks are gap-tolerant (`persistence_count` is a tolerant streak, not a
run of consecutive dates), and `lc_natural_frac` is read as a fallback for
`lc_natural_frac_10m` because the tracked alert files span two annotation
schemas.

**Verified against real published data**, 2026-09-08, offline: across the 40
runs and 429,946 features in the site's committed
`public/data/alerts/manifest.json`, every invariant this policy asserts holds —
both partitions, `strong <= high`, every total aggregating, `last_run` naming
the last row — and `strong` equals the feature count of the committed
`run-<date>.strong.geojson` in **all 40 runs**. The port is faithful to the
numbers already public.

## 6b. Which release objects a date's row is built from

The composer is handed the release's `dates[]`, each with a `paths` list of
logical paths, and has to find that date's two alert objects. That
classification is a **convention**, and a convention invented independently in
the site repository is exactly the drift the vectors exist to stop — so it is
stated here and carried across by vector like a threshold.

| Object | Requirement |
| --- | --- |
| the strong subset | exactly one declared path ending `.strong.geojson` |
| the full run | exactly one declared path ending `.geojson` and **not** `.strong.geojson` |

Deliberately a **suffix and not a full path**: the weakest requirement that
works, so the run assembler stays free to choose its own prefix. Everything
else a date declares — acquisition artifacts, charts — is ignored.

**The order of the two tests is load-bearing.** `run-<date>.strong.geojson`
also ends in `.geojson`, so testing the full suffix first classifies the subset
as the full run *silently*, and the page's default view becomes all 429k
candidate alerts while still reporting the strong count. The vectors pin both
the correct classification and its independence from declaration order.

`classify_run_objects` **fails closed** on anything but exactly one of each,
including zero. Two full objects for a date has no obvious winner, and picking
one would make the index depend on how the release happened to serialise its
list. A date whose `alert_state` is `alerts` must publish at least one object
(`GREEN_RELEASE_CONTRACT_V1.md` §3, product completeness), so an empty list
means the release and the index disagree and the composer must stop.

### And what the strong object must contain

**The strong subset is exactly the counted features that are strong** —
`strong_features`, not `is_strong`. The two are different, and the difference
is geometry: `is_strong` reads *properties* and says nothing about geometry,
while `count` and therefore `strong` include only areal features. A producer
that filters on the property predicate alone publishes an object with *more*
features than the `strong` number printed beside it, and the page loads that
object and prints that number.

This was found rather than reasoned: the site's fixture carries a `Point`
with `confidence_label: high` and a streak of 30, which satisfies `is_strong`
and is not a counted alert. The composer's cross-check refused the release, and
the refusal was correct — the fixture was wrong. The vectors now pin the subset
membership per case (`expected_strong_indices`) beside the statistics, because
the two must agree.

`site/scripts/site_artifact.py` verifies this against every release it composes
from, by downloading the strong object and comparing its feature count. That
check can be disabled with `--skip-strong-check` to save bytes, and disabling
it is the only way to publish an index whose `strong` disagrees with the object
the page loads — so the flag says so.

**This is a requirement ON the run assembler, which does not exist yet** — not
a description of something running. It is the first written requirement on that
producer, and §9 records the gap.

## 6c. Where the per-run objects live — and why they never enter the deploy

`object_base` is required, and it is `/data/green/`. `file` and `file_strong`
are the paths the release **declares**, so `object_base + file` is exactly a
request `worker/data_route.js` resolves: it maps `/data/green/<declared path>`
to `release_prefix + <declared path>`. A bare filename would force the page to
know the release's own prefix, which is the thing the route exists to hide.

**The per-run objects are never copied into the deploy.** They stay in the
immutable release and the page reads them through the route. That single choice
is what removes both site-side problems at once: the Cloudflare Workers 25 MiB
per-asset limit (the full run files exceed it, which is why they were pushed to
`pub-…r2.dev` in the first place) and the 247 MiB of committed alert history
that grows ~600 MiB/year.

`strong_points_file` is the exception and is deliberately shaped differently:
it is computed by the same green step that writes the index, so it is a build
artifact sitting *beside* the index rather than a release object. The schema
holds it to one path segment so it cannot accidentally be resolved against
`object_base`.

**Wiring the page to `object_base` is Phase 6, not this package.** The roadmap
bullet is explicit — *"Verify the main domain, same-origin data route, CORS,
full/strong modes, downloads"* — and touching `src/js/alertas.js` would change
what the production deploy serves. §9 records what that leaves untested.

## 7. Where each half of the check lives

Following the division Package 2B.2A reached by deleting code:

| Rule | Enforced by |
| --- | --- |
| Field presence, types, per-field bounds, path shape | the schema |
| Chronological order and no repeated date | `check_alert_index` |
| `last_run` names the last row | `check_alert_index` |
| The tier partition and the label partition | `check_alert_index` |
| `strong <= high` | `check_alert_index` |
| `file` and `file_strong` are different objects | `check_alert_index` |
| Every total aggregates its rows | `check_alert_index` |
| `pcount_max >= 1` | **the schema only** |

That last row is a deletion, and it was found rather than reasoned:
`test_every_rejection_case_would_pass_the_schema` failed on the case for it,
proving the code branch was unreachable — protection that reads like
protection. The check was removed and
`test_the_validator_does_not_restate_a_schema_bound` keeps it removed.
**Consequence: both halves must run.** Validating against the schema without
calling `check_alert_index` misses every relation; calling `check_alert_index`
without the schema misses the bound.

## 8. Deliberate non-requirements

1. **No checksum of the index is stored anywhere.** Its integrity is §4. A
   stored digest would have to live in a mutable object, and the release
   contract keeps exactly one of those.
2. **No `built_utc`, run id or actor.** Same reason `green_release.py` refuses
   them: they would make the bytes non-reproducible and destroy the property
   §4 rests on.
3. **`totals` is not a superset of the per-run keys.** `medium` and `low` are
   per run only, because the page shows them per run only. Adding them in
   aggregate would imply an element that does not exist.
4. **The index does not restate the release.** No `release_id`, no
   `release_prefix`. A consumer that wants provenance reads
   `/data/green/current.json`, which is one request and always current; copying
   it here would create a second answer that can go stale.
5. **`source` is free text.** It is a caption; constraining it would make a
   wording fix a contract change.
6. **No second ledger producer.** Nothing in this contract reads or writes a
   ledger.

## 9. What this contract does not yet have

**No producer deposits `runs/<run-id>/`**, so no green release contains real
alert objects; the live staging release holds hand-assembled proof data (two
small April geojsons). The composer is therefore exercisable against fixture,
not against a real run. This is the known condition of gate P2B, unchanged by
this package.

**The first v1 index does not exist yet.** The committed
`public/data/alerts/manifest.json` is the pre-contract format: it lacks
`schema`, `stats_policy_version` and per-run `pcount_max`. The v1 document is a
**superset** of it, so every field the page reads is still present and the
front-end needs no change — which is what keeps this package's site changes out
of the production deploy.
