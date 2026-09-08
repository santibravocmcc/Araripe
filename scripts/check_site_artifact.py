#!/usr/bin/env python3
"""The site alert index policy, and the vectors that pin it across two languages.

    python scripts/check_site_artifact.py vectors --check
    python scripts/check_site_artifact.py vectors --write

Package 2B.4B, bullet 1.  ``src/publication/site_artifact.py`` is the authority
and it is Python; the thing that will actually build the file the public reads
is ``site/scripts/site_artifact.py`` and it runs in the site repository, from a
green release fetched over HTTP.  Two implementations of one policy drift, and
the drift is silent because both look right in isolation — the exact reasoning
``scripts/check_delivery_boundary.py`` recorded for the delivery boundary in
Package 2B.3, reused here rather than reinvented.

So the policy is pinned as **vectors**, in three groups because there are three
distinct claims to break:

``run_cases``
    Features in, per-run statistics out.  This is the only group whose inputs
    are alert features, and it is where a threshold change shows up.

``index_cases``
    Per-run rows in, composed index out.  Every totals field must be an
    aggregation of the rows and nothing else; a case with rows whose features
    were never supplied is what proves it.

``rejection_cases``
    A malformed index in, a set of finding codes out.  A validator that
    accepted everything would pass the first two groups perfectly.

Neither implementation is the reference — this file is.  A change to the policy
that forgets one of the cases fails the gate in both repositories.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.publication import site_artifact as sa  # noqa: E402

VECTORS_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/contracts/phase2b/site_artifact_conformance_vectors.json"
)

#: Caption the site shows beside the latest detection date.  Copied from
#: `site/public/data/alerts/manifest.json` at site `origin/main`
#: 32f90494dfb1af1f8c0b7d826548045115958f62 so the first index this policy
#: produces is indistinguishable from the one already published.
SOURCE_LINE = "SENTINEL-2 L2A · LANDSAT 8/9"
STRONG_POINTS_FILE = "all-strong-points.json"


def _polygon() -> dict:
    """A minimal square.  The vectors never test geometry maths — area comes
    from the ``area_ha`` property the backend already computed — so the
    coordinates only have to make the feature *countable*."""

    return {
        "type": "Polygon",
        "coordinates": [[[-39.5, -7.2], [-39.4, -7.2], [-39.4, -7.1], [-39.5, -7.1], [-39.5, -7.2]]],
    }


def _feature(**properties) -> dict:
    return {"type": "Feature", "geometry": _polygon(), "properties": properties}


def _run_cases() -> list[dict]:
    """One case per branch of the per-run pass, each named for what it breaks."""

    cases: list[dict] = [
        {
            "name": "empty run reports zeros and the pcount floor",
            "why": (
                "A date with no alerts is a valid observation of absence "
                "(GREEN_RELEASE_CONTRACT_V1 alert_state 'zero_alerts'), never to be "
                "collapsed into no-data. pcount_max must still be 1 or the UI slider "
                "range collapses."
            ),
            "features": [],
        },
        {
            "name": "the three persistence tiers partition the features",
            "why": (
                "Boundaries at exactly CANDIDATE_MIN_SIGHTINGS and "
                "CONFIRMED_MIN_SIGHTINGS, plus one either side of each. An "
                "off-by-one in either comparison moves a feature between tiers."
            ),
            "features": [
                _feature(confidence_label="low", area_ha=1.0, persistence_count=1),
                _feature(confidence_label="low", area_ha=1.0, persistence_count=2),
                _feature(confidence_label="low", area_ha=1.0, persistence_count=14),
                _feature(confidence_label="low", area_ha=1.0, persistence_count=15),
                _feature(confidence_label="low", area_ha=1.0, persistence_count=16),
            ],
        },
        {
            "name": "a missing streak counts as one sighting, not as a crash",
            "why": (
                "The producer writes null for a track it has not counted yet, and "
                "int(None) raises. 'Not counted' means seen once, which is what a "
                "first observation is."
            ),
            "features": [
                _feature(confidence_label="high", area_ha=2.0, persistence_count=None),
                _feature(confidence_label="high", area_ha=2.0),
            ],
        },
        {
            "name": "strong membership needs all three conjuncts",
            "why": (
                "One feature satisfies everything; the other three each fail exactly "
                "one conjunct. Dropping any conjunct from the policy makes one of "
                "them strong and this case fails."
            ),
            "features": [
                _feature(confidence_label="high", area_ha=5.0, persistence_count=3,
                         lc_natural_frac_10m=0.9),
                _feature(confidence_label="medium", area_ha=5.0, persistence_count=3,
                         lc_natural_frac_10m=0.9),
                _feature(confidence_label="high", area_ha=5.0, persistence_count=1,
                         lc_natural_frac_10m=0.9),
                _feature(confidence_label="high", area_ha=5.0, persistence_count=3,
                         lc_natural_frac_10m=0.49),
            ],
        },
        {
            "name": "the natural-fraction threshold is inclusive at the boundary",
            "why": (
                "STRONG_MIN_NATURAL_FRACTION is a floor, not a strict bound. The "
                "value is rounded to three decimals first, so 0.4999 is below and "
                "0.5 is in."
            ),
            "features": [
                _feature(confidence_label="high", area_ha=1.0, persistence_count=2,
                         lc_natural_frac_10m=0.5),
                _feature(confidence_label="high", area_ha=1.0, persistence_count=2,
                         lc_natural_frac_10m=0.4999),
            ],
        },
        {
            "name": "the pre-2A.6 natural-fraction field is read as a fallback",
            "why": (
                "Tracked alert files span two annotation schemas. Reading only "
                "lc_natural_frac_10m would silently empty the strong subset for "
                "every older date."
            ),
            "features": [
                _feature(confidence_label="high", area_ha=1.0, persistence_count=2,
                         lc_natural_frac=0.8),
            ],
        },
        {
            "name": "an unlabelled feature is counted low, never high",
            "why": (
                "A label the policy does not name — including a missing one — must "
                "land in the conservative bin. Counting it as high would advertise "
                "confidence the detector never claimed."
            ),
            "features": [
                _feature(area_ha=1.0, persistence_count=1),
                _feature(confidence_label="unknown", area_ha=1.0, persistence_count=1),
            ],
        },
        {
            "name": "a non-areal geometry is not a counted alert",
            "why": (
                "count is not len(features). A Point carries no area, and counting "
                "it would break the tier partition the validator checks."
            ),
            "features": [
                _feature(confidence_label="high", area_ha=3.0, persistence_count=2,
                         lc_natural_frac_10m=0.7),
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-39.45, -7.15]},
                    "properties": {"confidence_label": "high", "area_ha": 99.0,
                                   "persistence_count": 30},
                },
                {"type": "Feature", "geometry": None, "properties": {"area_ha": 99.0}},
            ],
        },
        {
            "name": "MultiPolygon counts and a null area contributes nothing",
            "why": (
                "The backend writes MultiPolygon for split clearings. A null area_ha "
                "must add 0.0 rather than raise, because the feature still exists "
                "and still belongs to a tier. This case also pins a cross-language "
                "trap: 7.25 rounds to 7.2 under Python's round() and to 7.3 under "
                "JavaScript's toFixed(1). The expected value is the Python one, "
                "because that is what the site has published since the first run "
                "and moving it would restate history."
            ),
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "MultiPolygon", "coordinates": [_polygon()["coordinates"]]},
                    "properties": {"confidence_label": "medium", "area_ha": 7.25,
                                   "persistence_count": 4},
                },
                _feature(confidence_label="medium", area_ha=None, persistence_count=4),
            ],
        },
        {
            "name": "area is rounded once, to one decimal",
            "why": (
                "Three areas that only sum to a stable value if the rounding happens "
                "after the summation. Rounding each feature first drifts from the "
                "total the page adds up."
            ),
            "features": [
                _feature(confidence_label="low", area_ha=0.04, persistence_count=1),
                _feature(confidence_label="low", area_ha=0.04, persistence_count=1),
                _feature(confidence_label="low", area_ha=0.04, persistence_count=1),
            ],
        },
    ]
    for case in cases:
        case["expected"] = sa.run_statistics(case["features"])
    return cases


def _row(date: str, **stats) -> dict:
    """A per-run row as the index consumes it: identity, object names, statistics."""

    row = {
        "date": date,
        "file": f"run-{date}.geojson",
        "file_strong": f"run-{date}.strong.geojson",
    }
    row.update({key: stats.get(key, 0) for key in sa.RUN_STAT_KEYS})
    row["area_ha"] = float(stats.get("area_ha", 0.0))
    row["pcount_max"] = int(stats.get("pcount_max", sa.MIN_PCOUNT_MAX))
    return row


def _index_cases() -> list[dict]:
    cases: list[dict] = [
        {
            "name": "no runs is a legitimate index",
            "why": (
                "The state before the first release. last_run is null and pcount_max "
                "falls back to the floor; refusing this state would make the site "
                "fail on a correct, empty green release."
            ),
            "runs": [],
        },
        {
            "name": "totals aggregate rows whose features were never supplied",
            "why": (
                "THE point of the design: every totals field is a function of the "
                "rows alone, so a consumer verifies the whole document without "
                "reading 429k features. If any total needed a feature, this case "
                "could not be built."
            ),
            "runs": [
                _row("2026-01-02", count=3, area_ha=73930.0, high=2, medium=1, low=0,
                     first_obs=3, candidate=0, confirmed=0, strong=0, pcount_max=1),
                _row("2026-04-04", count=5, area_ha=120.5, high=4, medium=0, low=1,
                     first_obs=1, candidate=3, confirmed=1, strong=2, pcount_max=17),
                _row("2026-08-30", count=2, area_ha=45883.5, high=1, medium=1, low=0,
                     first_obs=0, candidate=1, confirmed=1, strong=1, pcount_max=9),
            ],
        },
        {
            "name": "the total area sums values already rounded",
            "why": (
                "Three rows at .05 sum to a different number depending on whether the "
                "rounding happened per row or once at the end. The per-row value is "
                "what a reader can add up by hand, so it is the one that is summed."
            ),
            "runs": [
                _row("2026-05-01", count=1, area_ha=0.1, high=1, first_obs=1, pcount_max=1),
                _row("2026-05-02", count=1, area_ha=0.1, high=1, first_obs=1, pcount_max=1),
                _row("2026-05-03", count=1, area_ha=0.1, high=1, first_obs=1, pcount_max=1),
            ],
        },
        {
            "name": "pcount_max is the maximum of the rows, not of the last one",
            "why": (
                "The largest streak may belong to any date. Taking the last row's "
                "value would shrink the UI slider whenever the newest run happens to "
                "be quiet."
            ),
            "runs": [
                _row("2026-06-01", count=1, area_ha=1.0, low=1, confirmed=1, pcount_max=42),
                _row("2026-06-02", count=1, area_ha=1.0, low=1, first_obs=1, pcount_max=1),
            ],
        },
    ]
    for case in cases:
        case["expected"] = sa.compose_alert_index(
            case["runs"], source=SOURCE_LINE, strong_points_file=STRONG_POINTS_FILE
        )
    return cases


def _rejection_cases() -> list[dict]:
    """Indexes that are shape-valid and self-inconsistent.

    Every one of these would pass the JSON Schema: the schema owns shape and
    cannot express a relation between two numbers.  That division is the one
    Package 2B.2A settled, and these cases are what makes the code half of it
    load-bearing rather than decorative.
    """

    def valid() -> dict:
        return sa.compose_alert_index(
            [
                _row("2026-07-01", count=4, area_ha=10.0, high=3, medium=1, low=0,
                     first_obs=1, candidate=2, confirmed=1, strong=2, pcount_max=20),
                _row("2026-07-08", count=1, area_ha=2.5, high=0, medium=0, low=1,
                     first_obs=1, candidate=0, confirmed=0, strong=0, pcount_max=1),
            ],
            source=SOURCE_LINE,
            strong_points_file=STRONG_POINTS_FILE,
        )

    cases: list[dict] = []

    document = valid()
    document["runs"][0]["confirmed"] += 1
    cases.append({
        "name": "the persistence tiers no longer partition the count",
        "why": "A tier gained a feature the count never had; the page would show more "
               "confirmed alerts than alerts.",
        "document": document,
    })

    document = valid()
    document["runs"][0]["medium"] = 0
    cases.append({
        "name": "the confidence labels no longer partition the count",
        "why": "Dropping a label bin loses features silently — the totals still look "
               "plausible because high is unchanged.",
        "document": document,
    })

    document = valid()
    document["runs"][0]["strong"] = 4
    cases.append({
        "name": "strong exceeds the high-confidence features it is drawn from",
        "why": "Strong membership requires the high label, so strong > high is "
               "arithmetically impossible and means the subset was computed against a "
               "different rule than the one reported.",
        "document": document,
    })

    document = valid()
    document["runs"].reverse()
    cases.append({
        "name": "runs are not in chronological order",
        "why": "The release's dates[] is required to be chronological. The site reads "
               "runs[len-1] as the latest run, so a reversed index shows the OLDEST "
               "date as the newest detection.",
        "document": document,
    })

    document = valid()
    document["last_run"] = "2026-07-01"
    cases.append({
        "name": "last_run does not name the last row",
        "why": "Two places in the page disagree about which run is current: the caption "
               "reads last_run and the map reads runs[len-1].",
        "document": document,
    })

    document = valid()
    document["totals"]["count"] = 99
    cases.append({
        "name": "a total does not aggregate its rows",
        "why": "The all-runs headline number is the one figure a reader cannot check "
               "against anything else on the page.",
        "document": document,
    })

    document = valid()
    document["totals"]["area_ha"] = round(10.0 + 2.5 + 0.0001, 4)
    cases.append({
        "name": "the total area was recomputed at a different precision",
        "why": "Reproducibility, not tidiness: an index derived from the same immutable "
               "release must be byte-identical, and a stray decimal means two builds "
               "of one release disagree.",
        "document": document,
    })

    document = valid()
    document["runs"][1]["file"] = document["runs"][1]["file_strong"]
    cases.append({
        "name": "the full object and the strong subset are the same object",
        "why": "The default view would serve every candidate alert — 429k features "
               "instead of 125k, and a claim of high confidence the data does not carry.",
        "document": document,
    })

    document = valid()
    # The LAST row, so the dates stay sorted and this case fires on repetition
    # alone. Duplicating the first row would also break the ordering, and a case
    # that trips three checks at once proves none of them.
    document["runs"].append(dict(document["runs"][-1]))
    cases.append({
        "name": "a UTC date appears twice",
        "why": "The release declares each date exactly once, so a repeated row means "
               "the composer double-counted and every total is inflated.",
        "document": document,
    })

    for case in cases:
        try:
            sa.check_alert_index(case["document"])
        except sa.SiteArtifactRejected as rejected:
            case["expected_codes"] = sorted(set(rejected.codes))
        else:  # pragma: no cover - a case that is accepted is a broken case
            raise AssertionError(
                f"rejection case {case['name']!r} was accepted; it proves nothing"
            )
    return cases


def build_vectors() -> dict:
    return {
        "contract": sa.INDEX_SCHEMA,
        "stats_policy_version": sa.STATS_POLICY_VERSION,
        "generated_by": "scripts/check_site_artifact.py vectors --write",
        "authority": "src/publication/site_artifact.py",
        "note": (
            "Neither the Python authority nor the site's composer is the reference: "
            "this file is. Add a case to the generator and regenerate; never hand-edit."
        ),
        "policy": {
            "confirmed_min_sightings": sa.CONFIRMED_MIN_SIGHTINGS,
            "candidate_min_sightings": sa.CANDIDATE_MIN_SIGHTINGS,
            "strong_min_natural_fraction": sa.STRONG_MIN_NATURAL_FRACTION,
            "strong_confidence_label": sa.STRONG_CONFIDENCE_LABEL,
            "confidence_labels": list(sa.CONFIDENCE_LABELS),
            "counted_geometry_types": list(sa.COUNTED_GEOMETRY_TYPES),
            "min_pcount_max": sa.MIN_PCOUNT_MAX,
        },
        "fixture": {"source": SOURCE_LINE, "strong_points_file": STRONG_POINTS_FILE},
        "run_cases": _run_cases(),
        "index_cases": _index_cases(),
        "rejection_cases": _rejection_cases(),
    }


def _serialise(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def cmd_vectors(args) -> int:
    built = build_vectors()
    counts = {group: len(built[group]) for group in
              ("run_cases", "index_cases", "rejection_cases")}
    if args.write:
        VECTORS_PATH.write_text(_serialise(built), encoding="utf-8")
        print(f"wrote {counts} to {VECTORS_PATH}")
        return 0

    if not VECTORS_PATH.exists():
        print(f"erro: {VECTORS_PATH} is absent; run with --write", file=sys.stderr)
        return 1
    stored = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    if stored != built:
        print(
            "erro: the stored vectors do not match this policy.\n"
            "Regenerate with `vectors --write` and review the diff; a silent "
            "regeneration is how a threshold change reaches the public unnoticed.",
            file=sys.stderr,
        )
        return 1
    print(f"vectors match the policy: {counts}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    vectors = sub.add_parser("vectors", help="check or regenerate the conformance vectors")
    group = vectors.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", default=True)
    group.add_argument("--write", action="store_true")
    vectors.set_defaults(func=cmd_vectors)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
