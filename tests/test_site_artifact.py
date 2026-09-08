"""The site alert index policy, and the vectors that carry it to the site repo.

Package 2B.4B, bullet 1.  Every test here is offline and deterministic: no
network, no clock, no object store.  The inputs are literal features and rows,
because the whole design property being tested is that the index needs nothing
else.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts import check_site_artifact as generator
from src.publication import site_artifact as sa

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads(
    (ROOT / "docs/contracts/phase2b/site_artifact_conformance_vectors.json").read_text(
        encoding="utf-8"
    )
)
SCHEMA = json.loads(
    (ROOT / "docs/contracts/phase2b/schemas/site-alert-index-v1.schema.json").read_text(
        encoding="utf-8"
    )
)


def _ids(cases):
    return [case["name"] for case in cases]


# ── the vectors are the reference, so first prove they still describe us ──────

def test_the_stored_vectors_are_what_the_generator_builds():
    """A hand-edited vectors file would let the two repositories agree on a
    policy neither implements.  The site's suite reads the same bytes."""

    assert VECTORS == generator.build_vectors()


def test_the_vectors_declare_the_policy_they_were_built_from():
    assert VECTORS["contract"] == sa.INDEX_SCHEMA
    assert VECTORS["stats_policy_version"] == sa.STATS_POLICY_VERSION
    assert VECTORS["policy"] == {
        "confirmed_min_sightings": sa.CONFIRMED_MIN_SIGHTINGS,
        "candidate_min_sightings": sa.CANDIDATE_MIN_SIGHTINGS,
        "strong_min_natural_fraction": sa.STRONG_MIN_NATURAL_FRACTION,
        "strong_confidence_label": sa.STRONG_CONFIDENCE_LABEL,
        "confidence_labels": list(sa.CONFIDENCE_LABELS),
        "counted_geometry_types": list(sa.COUNTED_GEOMETRY_TYPES),
        "min_pcount_max": sa.MIN_PCOUNT_MAX,
    }


def test_every_vector_group_is_populated():
    """An empty group passes every conformance loop in both repositories."""

    for group in ("run_cases", "index_cases", "rejection_cases"):
        assert VECTORS[group], group


# ── group 1: features in, statistics out ─────────────────────────────────────

@pytest.mark.parametrize("case", VECTORS["run_cases"], ids=_ids(VECTORS["run_cases"]))
def test_run_statistics_match_the_vector(case):
    assert sa.run_statistics(case["features"]) == case["expected"]


def test_count_is_not_the_length_of_the_feature_array():
    """The claim the 'non-areal geometry' vector exists to protect, stated once
    here so a reader does not have to infer it from a case name."""

    features = [
        {"type": "Feature", "geometry": {"type": "Polygon"}, "properties": {"area_ha": 1.0}},
        {"type": "Feature", "geometry": {"type": "Point"}, "properties": {"area_ha": 1.0}},
        {"type": "Feature", "geometry": {"type": "LineString"}, "properties": {"area_ha": 1.0}},
    ]
    assert len(features) == 3
    assert sa.run_statistics(features)["count"] == 1


def test_the_persistence_tiers_partition_every_counted_feature():
    """Property, not example: for any streak, exactly one tier increments."""

    for sightings in range(0, 40):
        stats = sa.run_statistics(
            [
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon"},
                    "properties": {"persistence_count": sightings, "area_ha": 1.0},
                }
            ]
        )
        assert stats["first_obs"] + stats["candidate"] + stats["confirmed"] == stats["count"] == 1


def test_strong_never_exceeds_high():
    """Enforced by the validator, and true by construction here — but only
    because ``is_strong`` requires the label.  Removing that conjunct passes
    every partition test and fails this one."""

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon"},
            "properties": {
                "confidence_label": label,
                "area_ha": 1.0,
                "persistence_count": 5,
                "lc_natural_frac_10m": 0.99,
            },
        }
        for label in ("high", "medium", "low", "high")
    ]
    stats = sa.run_statistics(features)
    assert stats["strong"] == 2
    assert stats["strong"] <= stats["high"]


def test_a_null_persistence_count_does_not_raise():
    """``int(None)`` raises, and the producer writes null.  The mutation that
    this catches is ``get("persistence_count", 1)``, which looks equivalent."""

    stats = sa.run_statistics(
        [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon"},
                "properties": {"persistence_count": None, "area_ha": 1.0},
            }
        ]
    )
    assert stats["first_obs"] == 1
    assert stats["pcount_max"] == sa.MIN_PCOUNT_MAX


# ── group 2: rows in, index out ──────────────────────────────────────────────

@pytest.mark.parametrize("case", VECTORS["index_cases"], ids=_ids(VECTORS["index_cases"]))
def test_composed_index_matches_the_vector(case):
    composed = sa.compose_alert_index(
        case["runs"],
        source=VECTORS["fixture"]["source"],
        strong_points_file=VECTORS["fixture"]["strong_points_file"],
    )
    assert composed == case["expected"]


@pytest.mark.parametrize("case", VECTORS["index_cases"], ids=_ids(VECTORS["index_cases"]))
def test_composed_index_satisfies_the_schema_and_the_validator(case):
    jsonschema.validate(case["expected"], SCHEMA)
    sa.check_alert_index(case["expected"])


def test_the_schema_is_a_valid_schema():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_totals_need_no_features():
    """The property the whole design rests on.

    Rows are supplied as bare numbers no feature ever produced — deliberately
    self-inconsistent ones — and every total still lands.  If any total needed
    a feature, this call could not be made at all.
    """

    rows = [
        {
            "date": "2026-03-01",
            "file": "a.geojson",
            "file_strong": "a.strong.geojson",
            "count": 7,
            "area_ha": 1.5,
            "high": 7,
            "medium": 0,
            "low": 0,
            "first_obs": 7,
            "candidate": 0,
            "confirmed": 0,
            "strong": 3,
            "pcount_max": 11,
        }
    ]
    index = sa.compose_alert_index(rows, source="s", strong_points_file="p.json")
    assert index["totals"] == {
        "count": 7,
        "area_ha": 1.5,
        "high": 7,
        "first_obs": 7,
        "candidate": 0,
        "confirmed": 0,
        "strong": 3,
        "pcount_max": 11,
    }


def test_the_total_area_is_a_float_even_with_no_runs():
    """``sum([])`` is the integer 0, and ``0`` and ``0.0`` are different bytes.
    The index must be byte-reproducible from an immutable release, so this is a
    contract detail rather than a style preference."""

    empty = sa.compose_alert_index([], source="s", strong_points_file="p.json")
    assert isinstance(empty["totals"]["area_ha"], float)
    assert empty["last_run"] is None


def test_the_per_run_maximum_aggregates_to_the_old_global_maximum():
    """``prepare_data.py`` tracked one global ``max_pcount`` across every run.
    Carrying it per run and taking the maximum is only a safe replacement if
    the two agree, including the floor — so that equality is asserted rather
    than assumed."""

    per_date = {
        "2026-01-01": [3, 9, 1],
        "2026-01-02": [],
        "2026-01-03": [42, 2],
    }
    rows = []
    global_max = sa.MIN_PCOUNT_MAX
    for date, streaks in per_date.items():
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon"},
                "properties": {"persistence_count": streak, "area_ha": 0.0},
            }
            for streak in streaks
        ]
        stats = sa.run_statistics(features)
        global_max = max(global_max, *streaks) if streaks else global_max
        rows.append(
            {"date": date, "file": f"{date}.geojson", "file_strong": f"{date}.s.geojson", **stats}
        )
    index = sa.compose_alert_index(rows, source="s", strong_points_file="p.json")
    assert index["totals"]["pcount_max"] == global_max == 42


# ── group 3: malformed indexes in, finding codes out ─────────────────────────

@pytest.mark.parametrize(
    "case", VECTORS["rejection_cases"], ids=_ids(VECTORS["rejection_cases"])
)
def test_rejection_cases_produce_the_recorded_codes(case):
    with pytest.raises(sa.SiteArtifactRejected) as raised:
        sa.check_alert_index(case["document"])
    assert sorted(set(raised.value.codes)) == case["expected_codes"]


@pytest.mark.parametrize(
    "case", VECTORS["rejection_cases"], ids=_ids(VECTORS["rejection_cases"])
)
def test_every_rejection_case_would_pass_the_schema(case):
    """The reason the validator exists.

    If a rejection case failed the schema, the code half of the split would be
    unreachable — protection that looks like protection.  Package 2B.2A reached
    this division by deleting exactly that kind of branch.
    """

    jsonschema.validate(case["document"], SCHEMA)


def test_the_validator_accepts_what_the_composer_builds():
    rows = [
        {
            "date": "2026-02-01",
            "file": "run-2026-02-01.geojson",
            "file_strong": "run-2026-02-01.strong.geojson",
            "count": 2,
            "area_ha": 3.0,
            "high": 1,
            "medium": 1,
            "low": 0,
            "first_obs": 1,
            "candidate": 1,
            "confirmed": 0,
            "strong": 1,
            "pcount_max": 4,
        }
    ]
    index = sa.compose_alert_index(rows, source="s", strong_points_file="p.json")
    sa.check_alert_index(index)
    jsonschema.validate(index, SCHEMA)


def test_the_validator_does_not_restate_a_schema_bound():
    """``pcount_max`` below its floor is refused by the schema, so no finding
    code exists for it.  The check was written, found unreachable by
    ``test_every_rejection_case_would_pass_the_schema``, and deleted — this
    asserts it stays deleted rather than being helpfully restored."""

    source = (ROOT / "src/publication/site_artifact.py").read_text(encoding="utf-8")
    assert "pcount_max_below_floor" not in source
    index = {"runs": [{"pcount_max": 0}]}
    jsonschema_error = None
    try:
        jsonschema.validate(index, SCHEMA)
    except jsonschema.ValidationError as error:
        jsonschema_error = error
    assert jsonschema_error is not None, "the schema must be the half that refuses this"


def test_a_rejection_reports_every_finding_at_once():
    """One malformed row must not hide the next.  Package 2B.1's validator died
    on the first bad feature and the log could not tell one odd row from a
    hundred thousand (``findings`` module docstring)."""

    index = sa.compose_alert_index(
        [
            {
                "date": "2026-02-01",
                "file": "a.geojson",
                "file_strong": "a.strong.geojson",
                "count": 1,
                "area_ha": 1.0,
                "high": 1,
                "medium": 0,
                "low": 0,
                "first_obs": 1,
                "candidate": 0,
                "confirmed": 0,
                "strong": 0,
                "pcount_max": 1,
            }
        ],
        source="s",
        strong_points_file="p.json",
    )
    index["runs"][0]["medium"] = 5
    index["runs"][0]["strong"] = 9
    index["last_run"] = "1999-01-01"
    with pytest.raises(sa.SiteArtifactRejected) as raised:
        sa.check_alert_index(index)
    assert {
        "confidence_labels_do_not_partition",
        "strong_exceeds_high",
        "last_run_is_not_the_last_run",
    } <= set(raised.value.codes)


def test_the_generator_refuses_a_rejection_case_that_is_accepted():
    """The generator asserts each rejection case actually rejects.  Without it,
    a case that stopped rejecting would silently record an empty code list and
    both repositories would agree that nothing is wrong."""

    source = (ROOT / "scripts/check_site_artifact.py").read_text(encoding="utf-8")
    assert "was accepted; it proves nothing" in source
