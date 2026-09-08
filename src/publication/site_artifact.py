"""The site's alert index: who computes it, and what the numbers mean.

Package 2B.4B, bullet 1 — *decide and record who produces the manifest the
site reads*.  The decision and its measured basis are in
``docs/contracts/phase2b/SITE_ARTIFACT_CONTRACT_V1.md``; this module is the
policy that document describes, and
``docs/contracts/phase2b/site_artifact_conformance_vectors.json`` is the
reference between this implementation and the site's.

Why the statistics are policy, and therefore live here
------------------------------------------------------
``site/public/data/alerts/manifest.json`` carries a per-run row and a totals
block, and every number in both is a *binning* of alert features: which
confidence label, which persistence tier, whether the feature belongs to the
"strong" subset the site loads by default.  Those bin boundaries are the same
kind of thing as the delivery boundary Package 2B.3 placed here — a decision
about what the public sees — so they are stated once, in this repository, and
the site executes them.  Package 2B.4A reached the same division for the data
route: "A POLÍTICA não é decidida aqui — ela é do backend" (``worker/data_route.js``).

Why the artifact is NOT published inside a green release
--------------------------------------------------------
The 2B.4B briefing's preferred option was to publish the index as a
``date_product`` of the release, which would put it under the release's
checksum and immutability.  Two measured facts rule it out, and both are
recorded in the contract:

1. ``release_prefix`` is a function of the **ledger alone**.
   ``green_release.release_identity`` derives it from ``ledger_id``,
   ``run_manifest_id``, ``run_manifest_sha256`` and ``document_sha256``, and
   that last input is "a digest over the whole ledger body" — not a digest of
   the release document.  So the same ledger rendered by a different renderer
   lands on *the same prefix with different bytes*, which
   ``If-None-Match: *`` refuses as ``ImmutableObjectConflict``
   (``GREEN_RELEASE_CONTRACT_V1.md`` §2).  Any later change to a threshold
   below would therefore make the affected releases unrepublishable.
2. Roadmap Phase 5 explicitly reserves the right to change those defaults
   ("Change a default only with recorded qualified evidence"), and Phase 3
   regenerates "persistence tiers, strong subsets, statistics".  So the
   thresholds are mutable *by plan*, and binding them into an object that is
   immutable by construction would be a designed-in conflict.

There is also a plain shape argument: a ``date_product``'s provenance requires
exactly one ``observed_on`` (``green-release-v1.schema.json``, ``release_object``),
and the index spans every date in the release.  Publishing it as one
``date_product`` would have to name one date and be wrong about the others.

So the index is **derived**, not sealed: a green preparation step computes it
from the objects the live release declares.  Its integrity argument is
reproducibility rather than a stored checksum — the inputs are immutable, the
function is pure, and the vectors pin it.

No second ledger producer appears anywhere in this: nothing here reads or
writes a ledger, and the run statistics are computed from alert features only.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .findings import Finding, Rejected

#: Bumped when any threshold or derivation below changes.  It travels in the
#: composed index so a stored artifact says which policy produced it — the
#: cheap version of the provenance a sealed object would have given for free.
STATS_POLICY_VERSION = "1"

#: The document kind, for the schema and for the consumer's own pin.
INDEX_SCHEMA = "araripe.site.alert_index/1"

# ── the thresholds, and where each already lives ─────────────────────────────
#
# These are ports of what ``site/scripts/prepare_data.py`` computes today, at
# `origin/main` 32f90494dfb1af1f8c0b7d826548045115958f62.  Porting rather than
# inventing is the point: the site's published numbers must not move because
# the producer changed, so the first release of this policy reproduces them
# exactly, and ``tests/test_site_artifact.py`` pins that with the vectors.

#: ``persistence_count`` at or above which a feature is a *confirmed* alert.
CONFIRMED_MIN_SIGHTINGS = 15
#: ``persistence_count`` at or above which it is a *candidate* (below is a
#: first observation).  A gap-tolerant streak, not a run of consecutive dates.
CANDIDATE_MIN_SIGHTINGS = 2
#: Minimum MapBiomas 10 m natural-vegetation fraction for strong membership.
STRONG_MIN_NATURAL_FRACTION = 0.5
#: The confidence label a strong feature must carry.
STRONG_CONFIDENCE_LABEL = "high"

#: The confidence labels counted per run.  A feature with any other label is
#: counted under ``low``, which is what ``prepare_data.py`` does by defaulting
#: a missing ``confidence_label`` to ``"low"``.
CONFIDENCE_LABELS = ("high", "medium", "low")

#: Geometry types that carry an area and therefore a countable alert.  A
#: feature of any other type is skipped, so ``count`` is *not* simply
#: ``len(features)`` — the difference is a number the site displays.
COUNTED_GEOMETRY_TYPES = ("Polygon", "MultiPolygon")

#: ``pcount_max`` never reports less than this, even for an empty run: it feeds
#: a UI slider whose range must not collapse.
MIN_PCOUNT_MAX = 1

#: Per-run keys in the order the index writes them.
RUN_STAT_KEYS = (
    "count",
    "area_ha",
    "high",
    "medium",
    "low",
    "first_obs",
    "candidate",
    "confirmed",
    "strong",
    "pcount_max",
)

#: Totals the index carries.  Each is an aggregation of the per-run rows and
#: nothing else — that is the property that lets the index be composed without
#: re-reading a single feature, and ``test_totals_need_no_features`` pins it.
TOTAL_KEYS = (
    "count",
    "area_ha",
    "high",
    "first_obs",
    "candidate",
    "confirmed",
    "strong",
    "pcount_max",
)


class SiteArtifactRejected(Rejected):
    """A composed index is not an acceptable site artifact."""

    subject = "site alert index"


# ── which release objects a date's row is built from ─────────────────────────
#
# The composer is handed a release's ``dates[]``, each with a ``paths`` list of
# logical paths, and has to find that date's two alert objects.  Classifying
# them is a *convention*, and a convention invented independently in the site
# repository is exactly the drift the vectors exist to stop — so it is stated
# here, once, and carried across by vector like everything else.
#
# No producer deposits ``runs/<run-id>/`` yet, so this is a requirement ON the
# run assembler when it is built rather than a description of something
# running.  It is deliberately the weakest requirement that works: a suffix,
# not a full path, so the assembler stays free to choose its own prefix.

#: Suffix marking the strong subset.  Checked BEFORE the full suffix, because
#: ``run-<date>.strong.geojson`` also ends in ``.geojson`` — testing in the
#: other order classifies every strong subset as a full run, silently, and the
#: page would then load 429k features as its default view.
STRONG_OBJECT_SUFFIX = ".strong.geojson"
#: Suffix marking the full run: every candidate alert for the date.
FULL_OBJECT_SUFFIX = ".geojson"


def classify_run_objects(paths: Iterable[str]) -> tuple[str, str]:
    """``(full, strong)`` logical paths for one date, or raise.

    Fails closed on anything but exactly one of each.  Two full objects for a
    date is not a situation with an obvious winner, and picking one would make
    the index depend on the order the release happens to list its paths.
    """

    strong = [path for path in paths if path.endswith(STRONG_OBJECT_SUFFIX)]
    full = [
        path
        for path in paths
        if path.endswith(FULL_OBJECT_SUFFIX) and not path.endswith(STRONG_OBJECT_SUFFIX)
    ]
    findings: list[Finding] = []
    if len(full) != 1:
        findings.append(
            Finding(
                "date_does_not_declare_one_full_run",
                f"expected exactly one object ending {FULL_OBJECT_SUFFIX!r} and not "
                f"{STRONG_OBJECT_SUFFIX!r}; found {sorted(full)}",
                "paths",
            )
        )
    if len(strong) != 1:
        findings.append(
            Finding(
                "date_does_not_declare_one_strong_subset",
                f"expected exactly one object ending {STRONG_OBJECT_SUFFIX!r}; "
                f"found {sorted(strong)}",
                "paths",
            )
        )
    if findings:
        raise SiteArtifactRejected(findings)
    return full[0], strong[0]


# ── the per-run pass: the only step that reads features ──────────────────────

def _natural_fraction(properties: Mapping[str, Any]) -> float:
    """The MapBiomas 10 m natural fraction, with the fallback the site uses.

    ``lc_natural_frac_10m`` is the v2 field; ``lc_natural_frac`` is what the
    pre-2A.6 annotation wrote.  Reading both is not defensive coding — the
    tracked alert files span both schemas, and treating an old file's fraction
    as absent would silently empty the strong subset for those dates.
    """

    raw = properties.get("lc_natural_frac_10m")
    if raw is None:
        raw = properties.get("lc_natural_frac")
    if raw is None:
        return 0.0
    return round(float(raw), 3)


def _sighting_count(properties: Mapping[str, Any]) -> int:
    """``persistence_count``, floored at 1.

    ``or 1`` rather than ``get(..., 1)``, deliberately: the producer writes
    ``null`` for a feature whose track has not been counted yet, and ``int(None)``
    would raise.  A missing streak means "seen once", which is what a first
    observation is.
    """

    return int(properties.get("persistence_count") or 1)


def is_strong(properties: Mapping[str, Any]) -> bool:
    """Whether a feature belongs to the subset the site loads by default.

    Three conjuncts, and none of them is redundant: high spectral confidence,
    a streak that survived at least one revisit, and a location MapBiomas maps
    as majority natural vegetation.  Dropping any one of them changes what the
    public sees first, which is why this is policy and not a filter.
    """

    return (
        properties.get("confidence_label") == STRONG_CONFIDENCE_LABEL
        and _sighting_count(properties) >= CANDIDATE_MIN_SIGHTINGS
        and _natural_fraction(properties) >= STRONG_MIN_NATURAL_FRACTION
    )


def run_statistics(features: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The statistics for one UTC date, from that date's alert features.

    Pure: no clock, no network, no object store.  ``features`` are GeoJSON
    features as the backend writes them — this reads ``geometry.type`` and the
    property names the annotation stage produces, never the site's rewritten
    short names (``conf``, ``nat10``), because the input is the published
    artifact and not the site's own output.

    ``area_ha`` is rounded once, here, to one decimal.  The rounding is part of
    the contract rather than a display concern: the index's total is the sum of
    these rounded values, so a consumer that rounded later would produce a
    different total from the same release.
    """

    stats = {key: 0 for key in RUN_STAT_KEYS}
    stats["area_ha"] = 0.0
    stats["pcount_max"] = MIN_PCOUNT_MAX

    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in COUNTED_GEOMETRY_TYPES:
            continue
        properties = feature.get("properties") or {}

        stats["count"] += 1
        label = properties.get("confidence_label", "low")
        stats[label if label in CONFIDENCE_LABELS else "low"] += 1
        stats["area_ha"] += float(properties.get("area_ha") or 0.0)

        sightings = _sighting_count(properties)
        stats["pcount_max"] = max(stats["pcount_max"], sightings)
        if sightings >= CONFIRMED_MIN_SIGHTINGS:
            stats["confirmed"] += 1
        elif sightings >= CANDIDATE_MIN_SIGHTINGS:
            stats["candidate"] += 1
        else:
            stats["first_obs"] += 1

        if is_strong(properties):
            stats["strong"] += 1

    stats["area_ha"] = round(stats["area_ha"], 1)
    return stats


# ── the composition: aggregation only, no features ───────────────────────────

def compose_alert_index(
    runs: Sequence[Mapping[str, Any]],
    *,
    source: str,
    strong_points_file: str,
) -> dict[str, Any]:
    """Compose the index from per-run rows, without reading a feature.

    ``runs`` must already be in chronological order and each row must carry
    ``date``, ``file``, ``file_strong`` and every key in :data:`RUN_STAT_KEYS`.
    Order is the caller's to establish because it is a property of the release
    (``dates[]`` is required to be chronological by
    ``GREEN_RELEASE_CONTRACT_V1.md`` §3), and re-sorting here would hide a
    release that violated it.

    ``last_run`` is the last row's date rather than the maximum, for the same
    reason: if the two differ, the release is not what it claims and the
    validator below says so instead of papering over it.
    """

    totals = {
        "count": sum(int(run["count"]) for run in runs),
        # The sum of values already rounded to one decimal, then rounded
        # again — matching what the site published before this policy existed.
        # Summing unrounded areas would drift from the per-run rows a reader
        # can add up by hand.
        "area_ha": round(sum((float(run["area_ha"]) for run in runs), 0.0), 1),
        "high": sum(int(run["high"]) for run in runs),
        "first_obs": sum(int(run["first_obs"]) for run in runs),
        "candidate": sum(int(run["candidate"]) for run in runs),
        "confirmed": sum(int(run["confirmed"]) for run in runs),
        "strong": sum(int(run["strong"]) for run in runs),
        "pcount_max": max(
            (int(run["pcount_max"]) for run in runs),
            default=MIN_PCOUNT_MAX,
        ),
    }
    return {
        "schema": INDEX_SCHEMA,
        "stats_policy_version": STATS_POLICY_VERSION,
        "runs": [
            {
                "date": run["date"],
                "file": run["file"],
                "file_strong": run["file_strong"],
                **{key: run[key] for key in RUN_STAT_KEYS},
            }
            for run in runs
        ],
        "strong_points_file": strong_points_file,
        "totals": totals,
        "last_run": runs[-1]["date"] if runs else None,
        "source": source,
    }


# ── the validator: what composition alone cannot guarantee ───────────────────

def check_alert_index(document: Mapping[str, Any]) -> None:
    """Raise :class:`SiteArtifactRejected` unless the index is self-consistent.

    Shape belongs to ``schemas/site-alert-index-v1.schema.json``; this checks
    only the relations JSON Schema cannot express — the division Package 2B.2A
    settled by deleting the code that restated the schema.

    Every check here is a relation *within* the document, so it holds for an
    index composed by this module and for one a consumer produced. It does not
    re-derive the statistics: that would require the features, and the whole
    point of the totals being aggregations is that a consumer can check them
    without them.

    One check is deliberately ABSENT. ``pcount_max`` below its floor is a
    per-field bound, which is shape, and the schema already refuses it with
    ``"minimum": 1``. A copy here was written first and deleted: it was an
    unreachable branch that read like protection, which is the failure Package
    2B.2A removed code to avoid. Both halves must therefore run — validate
    against the schema *and* call this — and the contract says so.
    """

    findings: list[Finding] = []
    runs = document.get("runs") or []

    dates = [run.get("date") for run in runs]
    if dates != sorted(dates):
        findings.append(
            Finding(
                "runs_out_of_order",
                "runs[] must be in chronological order; the release's dates[] "
                "is required to be, so an unordered index means the composer "
                "re-sorted or the release is malformed",
                "runs",
            )
        )
    if len(set(dates)) != len(dates):
        findings.append(
            Finding("run_date_repeated", "a UTC date appears in runs[] more than once", "runs")
        )

    expected_last = dates[-1] if dates else None
    if document.get("last_run") != expected_last:
        findings.append(
            Finding(
                "last_run_is_not_the_last_run",
                f"last_run is {document.get('last_run')!r} but the last row is {expected_last!r}",
                "last_run",
            )
        )

    for index, run in enumerate(runs):
        path = f"runs[{index}]"
        binned = sum(int(run.get(key, 0)) for key in ("first_obs", "candidate", "confirmed"))
        count = int(run.get("count", 0))
        if binned != count:
            findings.append(
                Finding(
                    "persistence_tiers_do_not_partition",
                    f"first_obs+candidate+confirmed is {binned} but count is {count}; "
                    "the three tiers are a partition of the counted features, "
                    "not overlapping views of them",
                    path,
                )
            )
        labelled = sum(int(run.get(key, 0)) for key in CONFIDENCE_LABELS)
        if labelled != count:
            findings.append(
                Finding(
                    "confidence_labels_do_not_partition",
                    f"high+medium+low is {labelled} but count is {count}",
                    path,
                )
            )
        if int(run.get("strong", 0)) > int(run.get("high", 0)):
            findings.append(
                Finding(
                    "strong_exceeds_high",
                    f"strong is {run.get('strong')} but only {run.get('high')} feature(s) "
                    f"carry the {STRONG_CONFIDENCE_LABEL!r} label that strong membership requires",
                    path,
                )
            )
        if run.get("file") == run.get("file_strong"):
            findings.append(
                Finding(
                    "full_and_strong_are_the_same_object",
                    f"file and file_strong are both {run.get('file')!r}; the strong subset is a "
                    "different object, and collapsing them would serve every candidate "
                    "under the default view",
                    path,
                )
            )

    totals = document.get("totals") or {}
    for key in TOTAL_KEYS:
        if key == "pcount_max":
            expected: Any = max(
                (int(run.get("pcount_max", MIN_PCOUNT_MAX)) for run in runs),
                default=MIN_PCOUNT_MAX,
            )
        elif key == "area_ha":
            expected = round(sum((float(run.get("area_ha", 0.0)) for run in runs), 0.0), 1)
        else:
            expected = sum(int(run.get(key, 0)) for run in runs)
        if totals.get(key) != expected:
            findings.append(
                Finding(
                    "total_does_not_aggregate_the_runs",
                    f"totals.{key} is {totals.get(key)!r} but aggregating runs[] gives {expected!r}",
                    f"totals.{key}",
                )
            )

    if findings:
        raise SiteArtifactRejected(findings)
