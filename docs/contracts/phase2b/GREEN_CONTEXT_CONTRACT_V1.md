# The land-cover context of a green release

**Contract versions:** `araripe.green.context/1` (document),
`araripe.green.context-pointer/1` (pointer), `araripe.green.context-labels/1`
(labels), `araripe.green.context-spec/1` (recipe); delivery boundary
`araripe.green.delivery/2`
**Recorded:** 2026-10-06
**Decision:** the owner, 2026-10-06 — re-label the published history with the
MapBiomas 2025 collections through a separate layer (path 1 of three offered)
**Code:** `src/publication/green_context.py`, `scripts/publish_green_context.py`,
`src/publication/delivery_boundary.py` (`_resolve_context`)

---

## 1. Why a layer, and not a new release

A green release's prefix is a function of its ledger alone
(`green_release.release_identity`), and the ledger does not seal an alert's
land-cover columns: they are written at detection time
(`scripts/replay_2026.py`, `annotate_alerts_all_collections`) and appear in no
identity input. Re-running the history with the 2025 crops therefore offers the
**same** immutable keys with **different** bytes, and `ConditionalStore`
refuses that by design (`ImmutableObjectConflict`). The project already ruled
on the general case in `SITE_ARTIFACT_CONTRACT_V1.md` §3: an artifact computed
by a rule that may change does not belong inside the sealed release — and
MapBiomas publishes a new collection every year.

The alternatives the owner was offered and declined: put the land-cover
version into the release identity and re-run the whole history (every future
MapBiomas update would repeat it), or annotate only future dates (one release
would carry two land-cover versions, and the strong subset would change rule
in the middle of the series).

## 2. Identity

`context_id = "ctx-g1-" + SHA256_US("araripe.green.context.identity.v1",
release_id, spec_sha256)`, where `spec_sha256` is the canonical-JSON digest of
the recipe: each collection's crop by **sha256** and its provenance (origin
URL, national MD5, collection, year), both class tables, the rounding, and the
strong rule's constants (as strings — canonical JSON refuses floats).

So the same release and recipe always give the same id and the same bytes, and
`put_if_absent` makes republication a no-op; a new crop or a new table gives a
new id. A context never changes in place.

## 3. Layout

    contexts/<context-id>/context.json   the document: declares logical paths
    contexts/objects/<sha256>            every declared object, stored by content
    contexts/current.json                mutable, compare-and-swap (context_pointer.move)

Each date with alerts declares two logical paths, `alerts/run-<date>.lc.json`
and `alerts/run-<date>.strong.geojson`; the stored key of each is
`contexts/objects/<its sha256>`. **By content, deliberately**: consecutive
promotions re-declare every unchanged date, and a per-context prefix would copy
the whole layer — 309 MB for the live release of 2026-10-06, 84 objects — on
every promotion, which is the duplication the project removed from releases
with option H. By content, identical bytes are one object (`put_if_absent`
answers `unchanged`) and a promotion stores only the dates that are new.

The pointer is **not** beside the release pointer: that namespace has one
writer, which keeps the promotion history (`tests/test_promotion_history.py`,
H2). `context_pointer.move` is the only writer of `contexts/current.json`.

- **`run-<date>.lc.json`** — `{"schema", "observed_on", "fields", "labels"}`;
  `labels` maps every `observation_id` of the date's **full** run to its values
  in `fields` order (`lc_class_10m`, `lc_group_10m`, `lc_natural_frac_10m`,
  `lc_class_30m`, `lc_group_30m`, `lc_natural_frac_30m`). No geometry. A value
  is `null` where the raster had no pixel under the alert.
- **Merging** (the only rule a consumer needs): replace those six properties
  and set `lc_class`, `lc_group`, `lc_natural_frac` to the `_10m` values — the
  copy `landcover.annotate_alerts_all_collections` has always written. Every
  other property is the release's.
- **`run-<date>.strong.geojson`** — the full run's features, relabelled, filtered
  by `site_artifact.strong_features`. A new object, because the release's own
  strong object was filtered under the old labels and the page loads the strong
  object by default.
- **`context.json`** — the id, the release it describes, the recipe, one
  `dates[]` entry per date with alerts (`source_path`, `source_sha256` of the
  release's full object the labels were computed from, `feature_count`,
  `strong_count`), and `objects[]` with sha256, bytes and content type.
- **The pointer** — `{schema, sequence, context_id, release_id, context_path,
  context_document_sha256, written_utc, written_by}`.

## 4. What `check_context` refuses

Against the release it names: a different `release_id`; an id or spec digest
that is not the function of §2; dates other than exactly the release's dates
with alerts; labels computed from a full object other than the one the release
declares (`source_mismatch`); a missing, mis-dated or unexpected object; a
`strong_count` outside `[0, feature_count]`. `relabel` refuses, in both
directions, labels and features that do not cover each other exactly — a
missing label or an extra one means the labels belong to a different run.

## 5. Serving (`araripe.green.delivery/2`)

Under the same allowlist rule as a release: `/data/green/context/<path>` maps
to `contexts/objects/<sha256>`, where the sha256 is the one the **context
document declares** for that path — never the request, and refused
(`context_unusable`) if it is not a 64-hex digest; `/data/green/context/context.json` is the document. The resolver
needs the live release, the context pointer and the context document, and
refuses:

| code | when | status |
| --- | --- | --- |
| `context_absent` | no context pointer | 404 |
| `context_not_live` | the pointer describes another release — the normal state right after a promotion | 404 |
| `context_unusable` | the pointer's `context_id` is not a context id | 500 |
| `context_document_mismatch` | the document is not the one the pointer names | 503 |
| `not_declared_by_the_live_context` | an undeclared path | 404 |

A release may not declare a product under `context/` (`product_shadows_context`).
Responses carry `X-Araripe-Context-Id` beside `X-Araripe-Release-Id`.
`classify_key`: `contexts/<live id>/…` public, every other context private, the
pointer private (the resolver reads it; no mount name serves it). Retention
sees `contexts/` as unclassified → review, never eligible.

## 6. Consumers

- **The site composer** applies a live context before counting, sets
  `file_strong` to `context/alerts/run-<date>.strong.geojson`, and records
  `land_cover: {context_id, collections}` in the index (additive in
  `site.alert_index/1`). Without a live context the index is composed exactly
  as before and carries no `land_cover`.
- **The page** merges `run-<date>.lc.json` into a full run when the index names
  a context, and captions the natural-vegetation fractions from
  `land_cover.collections`; without it the captions name the 2023 crops.

## 7. Order after a promotion

promote → `publish_green_context.py fetch / plan / apply` for the new release →
site compose. Between the first and second steps the context is
`context_not_live` and the site, if rebuilt then, falls back to the release's
labels and says so.

The lane is `.github/workflows/v2_green_context.yml` (`plan` | `publish`),
Environment `v2-promotion`, runnable only from `main`, with its own concurrency
group `araripe-green-context`. It does not share the promotion group: `apply`
refuses unless the live pointer still names the context's release, and losing
that race leaves at worst a `context_not_live` pointer, which is the fallback,
not an error. Wiring it to run after every promotion is part of the deploy-order
work (`PACKAGE_P6_DEPLOY_ORDER_PROMPT.md`).

## 8. What this contract does not do

- It does not change any release, ledger, run, or the detector's annotation
  (`config/settings.py` `LANDCOVER_RASTERS` still names the 2023 crops).
- It does not make the blue path, or the 2023 captions it shows, change.
- It carries no accuracy claim: the strong subset under 2025 labels is a
  different subset, not a validated one (Phase 5).
