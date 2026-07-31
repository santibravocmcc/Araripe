"""Offline regression tests for the provisional Phase 2A.3 validation pilot."""

from __future__ import annotations

import copy
import datetime as dt
import gzip
import json
import math
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.detection.baseline_manifest import sha256_file
from src.detection.identity import identity_sha256
from src.validation import evidence as evidence_module
from src.validation.evidence import (
    EvidenceConfig,
    _cache_key,
    _cache_read,
    _cache_write,
    _safe_error_message,
    _select_item,
)
from src.validation.package import (
    METHOD_FAMILIES,
    REQUIRED_EVIDENCE_ROLES,
    build_validation_package,
    write_canonical_jsonl_gzip,
)
from src.validation.sampling import (
    BALANCE_LEVELS,
    SAMPLING_DESIGN_VERSION,
    SamplingDesignError,
    build_sampling_frame,
    sanitize_origin_base_url,
)
from src.validation.validator import (
    ValidationPackageIntegrityError,
    _validate_json,
    _verify_cases,
    _verify_frame,
    validate_review_export,
    validate_validation_package,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXED_GENERATED_AT = "2026-07-31T13:15:00-03:00"
FIXED_RETRIEVED_AT = "2026-07-31T12:36:00-03:00"
FIXED_SEED = "20260731"


def _polygon(longitude: float, latitude: float) -> dict[str, Any]:
    half_size = 0.002
    ring = [
        [longitude - half_size, latitude - half_size],
        [longitude + half_size, latitude - half_size],
        [longitude + half_size, latitude + half_size],
        [longitude - half_size, latitude + half_size],
        [longitude - half_size, latitude - half_size],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def _feature(
    *,
    longitude: float,
    latitude: float,
    observed_on: str,
    confidence: str,
    area_ha: float,
    land_cover: str,
    persistence: str,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": _polygon(longitude, latitude),
        "properties": {
            "detection_date": observed_on,
            "confidence_label": confidence,
            "area_ha": area_ha,
            "lc_group_10m": land_cover,
            "persistence_status": persistence,
            "persistence_count": 1,
            "first_seen": observed_on,
            "last_seen": observed_on,
            "clearing_type": "provisional_fixture_value",
        },
    }


def _write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    payload = {
        "type": "FeatureCollection",
        "name": path.stem,
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "features": features,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_balanced_population(source_dir: Path) -> list[Path]:
    source_dir.mkdir(parents=True)
    # One cell in each 2x3 geographic zone, with exact six-case balance across
    # every other requested margin.  The first cell has two eligible locations
    # so conditional selection probability is exercised rather than assumed.
    longitudes = (-40.57, -39.92, -39.28, -40.57, -39.92, -39.28)
    latitudes = (-7.18, -7.18, -7.18, -7.66, -7.66, -7.66)
    dates = (
        "2026-03-01",
        "2026-06-01",
        "2026-04-01",
        "2026-07-01",
        "2026-02-01",
        "2026-05-01",
    )
    confidences = ("high", "medium", "low")
    areas = (1.5, 3.0, 6.0)
    land_covers = ("natural", "farming", "water")
    persistence = ("first", "candidate", "confirmed")

    paths: list[Path] = []
    for index, observed_on in enumerate(dates):
        feature = _feature(
            longitude=longitudes[index],
            latitude=latitudes[index],
            observed_on=observed_on,
            confidence=confidences[index % 3],
            area_ha=areas[index % 3],
            land_cover=land_covers[index % 3],
            persistence=persistence[index % 3],
        )
        features = [feature]
        if index == 0:
            second = _feature(
                longitude=longitudes[index] + 0.02,
                latitude=latitudes[index],
                observed_on=observed_on,
                confidence=confidences[index % 3],
                area_ha=areas[index % 3],
                land_cover=land_covers[index % 3],
                persistence=persistence[index % 3],
            )
            # The exact duplicate is excluded while the spatially distinct
            # second member remains eligible in the same joint cell.
            duplicate = json.loads(json.dumps(feature))
            features.extend((second, duplicate))
        if index == 5:
            features.append(
                _feature(
                    longitude=-50.0,
                    latitude=-10.0,
                    observed_on=observed_on,
                    confidence=confidences[index % 3],
                    area_ha=areas[index % 3],
                    land_cover=land_covers[index % 3],
                    persistence=persistence[index % 3],
                )
            )
        path = source_dir / f"alerts_{observed_on}_{index:02d}.geojson"
        _write_geojson(path, features)
        paths.append(path)
    return paths


def _write_overcomplete_population(source_dir: Path) -> list[Path]:
    """Write two disjoint, exactly balanced six-cell designs."""
    source_dir.mkdir(parents=True)
    longitudes = (-40.57, -39.92, -39.28, -40.57, -39.92, -39.28)
    latitudes = (-7.18, -7.18, -7.18, -7.66, -7.66, -7.66)
    dates = (
        "2026-03-01",
        "2026-06-01",
        "2026-04-01",
        "2026-07-01",
        "2026-02-01",
        "2026-05-01",
    )
    confidences = ("high", "medium", "low")
    areas = (1.5, 3.0, 6.0)
    land_covers = ("natural", "farming", "water")
    persistence = ("first", "candidate", "confirmed")

    paths: list[Path] = []
    for index, observed_on in enumerate(dates):
        first = _feature(
            longitude=longitudes[index],
            latitude=latitudes[index],
            observed_on=observed_on,
            confidence=confidences[index % 3],
            area_ha=areas[index % 3],
            land_cover=land_covers[index % 3],
            persistence=persistence[index % 3],
        )
        second = _feature(
            longitude=longitudes[index] + 0.02,
            latitude=latitudes[index],
            observed_on=observed_on,
            confidence=confidences[(index + 1) % 3],
            area_ha=areas[(index + 2) % 3],
            land_cover=land_covers[(index + 1) % 3],
            persistence=persistence[(index + 2) % 3],
        )
        path = source_dir / f"alerts_{observed_on}_{index:02d}.geojson"
        _write_geojson(path, [first, second])
        paths.append(path)
    return paths


@pytest.fixture(scope="module")
def pilot_frame(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("phase2a3-frame")
    source_dir = root / "sources"
    paths = _write_balanced_population(source_dir)
    frame = build_sampling_frame(
        paths,
        target_size=6,
        seed=FIXED_SEED,
        origin_base_url="https://example.invalid/provisional-alerts",
    )
    return {"source_dir": source_dir, "paths": paths, "frame": frame}


def _build_package(frame: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    return build_validation_package(
        frame,
        output_dir=output_dir,
        repository_root=REPOSITORY_ROOT,
        generated_at=FIXED_GENERATED_AT,
        source_retrieved_at=FIXED_RETRIEVED_AT,
        generation_command=["scripts/build_validation_pilot.py", "--synthetic-test"],
    )


@pytest.fixture(scope="module")
def pilot_package(
    tmp_path_factory: pytest.TempPathFactory,
    pilot_frame: dict[str, Any],
) -> dict[str, Any]:
    output_dir = tmp_path_factory.mktemp("phase2a3-package") / "package"
    manifest = _build_package(pilot_frame["frame"], output_dir)
    return {
        "root": output_dir,
        "manifest": manifest,
        "source_dir": pilot_frame["source_dir"],
    }


def _file_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_balanced_selection_is_deterministic_and_records_probabilities(
    pilot_frame: dict[str, Any],
) -> None:
    frame = pilot_frame["frame"]
    reversed_frame = build_sampling_frame(
        reversed(pilot_frame["paths"]),
        target_size=6,
        seed=FIXED_SEED,
        origin_base_url="https://example.invalid/provisional-alerts",
    )

    assert frame == reversed_frame
    assert frame["balance_status"] == "exact"
    assert frame["sample_margins"] == frame["margin_targets"]
    assert set(frame["sample_margins"]) == set(BALANCE_LEVELS)
    assert frame["source_feature_count"] == 9
    assert frame["eligible_count"] == 7
    assert frame["excluded_count"] == 2
    assert frame["exclusion_counts"] == {
        "duplicate_exact_location_date": 1,
        "wholly_outside_accepted_extent": 1,
    }

    selected = frame["selected_units"]
    assert len(selected) == 6
    assert len({unit["sample_id"] for unit in selected}) == 6
    assert all(unit["sample_id"].startswith("p2a3-sample-v1-") for unit in selected)
    assert all(unit["source_record_id"].startswith("p2a3-audit-location-v1-") for unit in selected)
    assert all(unit["canonical_observation_id"] is None for unit in selected)
    assert all(unit["canonical_event_id"] is None for unit in selected)

    two_member_cell = [
        unit
        for unit in frame["units"]
        if unit.get("eligible") and unit.get("joint_stratum_population") == 2
    ]
    assert len(two_member_cell) == 2
    assert sum(bool(unit["selected"]) for unit in two_member_cell) == 1
    assert all(math.isclose(unit["selection_probability"], 0.5) for unit in two_member_cell)
    singleton_cells = [
        unit
        for unit in frame["units"]
        if unit.get("eligible") and unit.get("joint_stratum_population") == 1
    ]
    assert len(singleton_cells) == 5
    assert all(unit["selected"] and unit["selection_probability"] == 1.0 for unit in singleton_cells)
    excluded = [unit for unit in frame["units"] if not unit["eligible"]]
    assert all(unit["selection_probability"] == 0.0 for unit in excluded)
    assert all(unit["sample_id"] is None for unit in excluded)


def test_package_bytes_are_deterministic_with_fixed_generation_inputs(
    tmp_path: Path,
    pilot_frame: dict[str, Any],
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_manifest = _build_package(pilot_frame["frame"], first)
    second_manifest = _build_package(pilot_frame["frame"], second)

    assert first_manifest == second_manifest
    assert _file_digests(first) == _file_digests(second)


def test_package_schema_checksums_and_blank_missing_evidence_are_valid(
    pilot_package: dict[str, Any],
) -> None:
    root = pilot_package["root"]
    result = validate_validation_package(
        root,
        source_dir=pilot_package["source_dir"],
    )
    assert result["status"] == "valid"
    assert result["source_feature_count"] == 9
    assert result["eligible_count"] == 7
    assert result["sample_size"] == 6
    assert result["double_review_size"] == 2

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review"]["human_labels_present"] is False
    assert manifest["claims"]["scientific_accuracy_claim"] is False
    assert manifest["claims"]["method_promoted_or_activated"] is False
    assert manifest["review"]["double_review_fraction"] == pytest.approx(2 / 6)

    assert not (root / "reviewer").exists()
    for slot, expected_count in (("reviewer-a", 6), ("reviewer-b", 2)):
        reviewer_root = root / slot
        assert (reviewer_root / "PROTOCOL.md").is_file()
        assert (reviewer_root / "reviewer.css").is_file()
        assert (reviewer_root / "reviewer.js").is_file()
        assert (reviewer_root / "index.html").is_file()
        assignment = json.loads(
            (reviewer_root / "assignment.json").read_text(encoding="utf-8")
        )
        assert assignment["reviewer_slot"] == slot
        assert len(assignment["blind_case_ids"]) == expected_count
        assert len(set(assignment["blind_case_ids"])) == expected_count

    cases = sorted((root / "reviewer-a" / "cases").glob("*.json"))
    assert len(cases) == 6
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        review = case["review_fields"]
        assert review["review_status"] == "unreviewed"
        assert review["change_assessment"]["change_label"] is None
        assert review["temporal_assessment"]["confidence"] is None
        assert review["land_cover_assessment"]["context"] is None
        assert set(case["evidence"]) == set(REQUIRED_EVIDENCE_ROLES)
        for role, evidence in case["evidence"].items():
            expected_status = "unavailable" if role == "provenance_valid_time_series" else "missing"
            assert evidence["status"] == expected_status
            assert evidence["local_path"] is None
            assert evidence["source"] is None
            assert evidence["reason"]
        for family in METHOD_FAMILIES:
            method = review["method_comparisons"][family]
            assert method["availability"] == "not_generated_in_2a3"
            assert method["preference"] is None
            assert method["selected_or_activated"] is False

    with gzip.open(root / "sampling" / "frame.jsonl.gz", "rt", encoding="utf-8") as handle:
        frame_rows = [json.loads(line) for line in handle]
    with gzip.open(
        root / "sampling" / "exclusions.jsonl.gz", "rt", encoding="utf-8"
    ) as handle:
        exclusion_rows = [json.loads(line) for line in handle]
    assert len(frame_rows) == 9
    assert len(exclusion_rows) == 2


def test_package_artifact_tampering_is_rejected(
    tmp_path: Path,
    pilot_package: dict[str, Any],
) -> None:
    tampered = tmp_path / "tampered-package"
    shutil.copytree(pilot_package["root"], tampered)
    case_path = next((tampered / "reviewer-a" / "cases").glob("*.json"))
    with case_path.open("ab") as handle:
        handle.write(b"\n")

    with pytest.raises(ValidationPackageIntegrityError, match="(byte|SHA-256) mismatch"):
        validate_validation_package(tampered)


def test_source_artifact_tampering_is_rejected_on_revalidation(
    tmp_path: Path,
    pilot_package: dict[str, Any],
) -> None:
    tampered_sources = tmp_path / "tampered-sources"
    shutil.copytree(pilot_package["source_dir"], tampered_sources)
    source_path = next(tampered_sources.glob("*.geojson"))
    with source_path.open("ab") as handle:
        handle.write(b"\n")

    with pytest.raises(ValidationPackageIntegrityError, match="source artifact changed"):
        validate_validation_package(
            pilot_package["root"],
            source_dir=tampered_sources,
        )


def test_evidence_cache_key_invalidation_and_asset_checksum_rejection(
    tmp_path: Path,
) -> None:
    sample_id = "p2a3-sample-v1-" + "a" * 64
    unit = {
        "sample_id": sample_id,
        "observed_on": "2026-03-01",
        "canonical_geometry": _polygon(-40.0, -7.4),
    }
    config = EvidenceConfig(
        cache_dir=tmp_path / "cache",
        catalog_accessed_at="2026-07-31T12:45:00-03:00",
        evidence_cutoff_date=dt.date(2026, 7, 31),
    )
    changed_config = replace(config, minimum_local_clear_fraction=0.75)
    original_key = _cache_key(unit, config)
    changed_key = _cache_key(unit, changed_config)
    assert original_key != changed_key

    case_dir = config.cache_dir / sample_id
    case_dir.mkdir(parents=True)
    asset = case_dir / "before.png"
    asset.write_bytes(b"abc")
    evidence = {
        "before_imagery": {
            "role": "before_imagery",
            "status": "available",
            "_source_path": str(asset),
        }
    }
    _cache_write(case_dir, sample_id, original_key, evidence)

    cached = _cache_read(case_dir, sample_id, original_key)
    assert cached is not None
    assert cached["before_imagery"]["_source_path"] == str(asset)
    assert _cache_read(case_dir, sample_id, changed_key) is None

    # Preserve byte length so rejection specifically exercises the stored hash.
    asset.write_bytes(b"xyz")
    assert _cache_read(case_dir, sample_id, original_key) is None


def test_signed_url_errors_are_redacted_before_recording() -> None:
    message = _safe_error_message(
        "failed https://alice:password@example.test/path/image.tif"
        "?token=super-secret&sig=also-secret"
    )
    assert "password" not in message
    assert "super-secret" not in message
    assert "also-secret" not in message
    assert "[userinfo-redacted]" in message
    assert "?[query-redacted]" in message


def test_item_selection_requires_both_local_clear_and_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = dt.datetime(2026, 3, 10, tzinfo=dt.timezone.utc)
    items = [
        SimpleNamespace(
            id="qa-read-error",
            datetime=target - dt.timedelta(days=1),
            properties={"eo:cloud_cover": 1.0},
        ),
        SimpleNamespace(
            id="low-coverage",
            datetime=target - dt.timedelta(days=2),
            properties={"eo:cloud_cover": 2.0},
        ),
        SimpleNamespace(
            id="low-clear",
            datetime=target - dt.timedelta(days=3),
            properties={"eo:cloud_cover": 3.0},
        ),
        SimpleNamespace(
            id="usable",
            datetime=target - dt.timedelta(days=4),
            properties={"eo:cloud_cover": 4.0},
        ),
    ]
    metrics = {
        "low-coverage": (0.99, 0.94),
        "low-clear": (0.69, 1.0),
        "usable": (0.80, 0.98),
    }

    def fake_local_qa(item: Any, **_: Any) -> tuple[float, float]:
        if item.id == "qa-read-error":
            raise OSError(
                "read failed: https://user:pass@example.test/qa.tif?sig=secret"
            )
        return metrics[item.id]

    monkeypatch.setattr(evidence_module, "_local_qa_metrics", fake_local_qa)
    config = EvidenceConfig(
        cache_dir=tmp_path / "cache",
        catalog_accessed_at="2026-07-31T12:45:00-03:00",
        evidence_cutoff_date=dt.date(2026, 7, 31),
        minimum_local_clear_fraction=0.70,
        minimum_local_coverage_fraction=0.95,
    )

    selected, clear_fraction, coverage_fraction, audit = _select_item(
        items,
        sensor="sentinel2",
        target=target,
        direction="before",
        longitude=-40.0,
        latitude=-7.4,
        config=config,
    )

    assert selected.id == "usable"
    assert (clear_fraction, coverage_fraction) == (0.80, 0.98)
    assert [record["local_qa_status"] for record in audit] == [
        "error",
        "below_threshold",
        "below_threshold",
        "usable",
    ]
    assert "pass" not in audit[0]["reason"]
    assert "secret" not in audit[0]["reason"]
    assert "[userinfo-redacted]" in audit[0]["reason"]
    assert "?[query-redacted]" in audit[0]["reason"]


def test_review_export_validation_and_completion_guards(
    tmp_path: Path,
    pilot_package: dict[str, Any],
) -> None:
    root = pilot_package["root"]
    template = json.loads(
        (root / "reviewer-a" / "review-template.json").read_text(
            encoding="utf-8"
        )
    )

    valid_export = copy.deepcopy(template)
    completed = valid_export["reviews"][0]
    completed["review_status"] = "complete"
    completed["reviewer"] = {
        "pseudonymous_id": "reviewer-fixture",
        "qualification_attested": True,
        "independence_attested": True,
    }
    completed["change_assessment"].update(
        {
            "change_label": "uncertain",
            "reason": "Available evidence remains ambiguous.",
            "evidence_sufficiency": "conflicting",
        }
    )
    completed["temporal_assessment"].update(
        {"confidence": "low", "reason": "The temporal bracket is broad."}
    )
    completed["land_cover_assessment"].update(
        {
            "context": "mixed",
            "confidence": "low",
            "reason": "The location crosses two visible cover types.",
        }
    )
    completed["contextual_signature"].update(
        {
            "label": "mixed_or_uncertain",
            "reason": "No single contextual signature is conclusive.",
        }
    )
    completed["usability"]["review_duration_seconds"] = 45
    valid_path = tmp_path / "valid-review.json"
    _write_json(valid_path, valid_export)
    result = validate_review_export(root, valid_path)
    assert result["status"] == "valid"
    assert result["status_counts"] == {"complete": 1, "unreviewed": 5}
    assert result["claim_scope"] == "review_process_validation_only_no_accuracy_metrics"

    all_null_complete = copy.deepcopy(template)
    all_null_complete["reviews"][0]["review_status"] = "complete"
    all_null_path = tmp_path / "all-null-complete.json"
    _write_json(all_null_path, all_null_complete)
    with pytest.raises(ValidationPackageIntegrityError, match="schema violation"):
        validate_review_export(root, all_null_path)

    immutable_tamper = copy.deepcopy(template)
    immutable_tamper["reviews"][0]["method_comparisons"]["cloud_mask"][
        "availability"
    ] = "unreviewable"
    immutable_path = tmp_path / "immutable-method-tamper.json"
    _write_json(immutable_path, immutable_tamper)
    with pytest.raises(
        ValidationPackageIntegrityError,
        match="changed immutable method metadata",
    ):
        validate_review_export(root, immutable_path)


def test_origin_url_is_sanitized_and_userinfo_is_rejected(
    pilot_frame: dict[str, Any],
) -> None:
    base = "https://example.invalid/provisional-alerts/?token=secret#private"
    assert sanitize_origin_base_url(base) == (
        "https://example.invalid/provisional-alerts"
    )
    frame = build_sampling_frame(
        pilot_frame["paths"],
        target_size=6,
        seed=FIXED_SEED,
        origin_base_url=base,
    )
    for artifact in frame["source_artifacts"]:
        assert artifact["origin_url"] == (
            "https://example.invalid/provisional-alerts/"
            + artifact["path_label"]
        )
        assert "secret" not in artifact["origin_url"]
        assert "?" not in artifact["origin_url"]
        assert "#" not in artifact["origin_url"]

    with pytest.raises(SamplingDesignError, match="must not contain credentials"):
        sanitize_origin_base_url(
            "https://reviewer:password@example.invalid/provisional-alerts"
        )


def test_verify_frame_rejects_a_coherent_alternate_balanced_selection(
    tmp_path: Path,
) -> None:
    source_paths = _write_overcomplete_population(tmp_path / "sources")
    frame = build_sampling_frame(
        source_paths,
        target_size=6,
        seed=FIXED_SEED,
        origin_base_url="https://example.invalid/provisional-alerts",
    )
    assert len(frame["fine_strata"]) == 12
    package_root = tmp_path / "package"
    manifest = _build_package(frame, package_root)
    selected_ids, _ = _verify_frame(package_root, manifest)
    assert len(selected_ids) == 6

    frame_path = package_root / "sampling" / "frame.jsonl.gz"
    with gzip.open(frame_path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    expected_cells = {
        row["joint_stratum_id"]
        for row in rows
        if row["selected_joint_stratum"]
    }
    design_a = {
        row["joint_stratum_id"]
        for row in rows
        if row["source_feature_index"] == 0
    }
    design_b = {
        row["joint_stratum_id"]
        for row in rows
        if row["source_feature_index"] == 1
    }
    alternate_cells = design_b if expected_cells == design_a else design_a
    assert len(alternate_cells) == 6
    assert alternate_cells != expected_cells

    alternate_rows = [
        row for row in rows if row["joint_stratum_id"] in alternate_cells
    ]
    for variable, expected_margin in manifest["sampling"][
        "sample_margins"
    ].items():
        actual_margin = dict(
            sorted(Counter(row["strata"][variable] for row in alternate_rows).items())
        )
        assert actual_margin == expected_margin

    for row in rows:
        selected = row["joint_stratum_id"] in alternate_cells
        row["selected_joint_stratum"] = selected
        row["joint_stratum_sample"] = int(selected)
        row["conditional_within_stratum_probability"] = float(selected)
        row["selection_probability"] = float(selected)
        row["selected"] = selected
        row["sample_id"] = (
            "p2a3-sample-v1-"
            + identity_sha256(
                "phase2a3-sample-v1",
                SAMPLING_DESIGN_VERSION,
                FIXED_SEED,
                row["source_record_id"],
            )
            if selected
            else None
        )
    write_canonical_jsonl_gzip(frame_path, rows)

    with pytest.raises(
        ValidationPackageIntegrityError,
        match="selected joint strata do not match deterministic balanced selection",
    ):
        _verify_frame(package_root, manifest)


def test_verify_cases_rejects_target_date_mismatch(
    tmp_path: Path,
    pilot_package: dict[str, Any],
) -> None:
    tampered = tmp_path / "target-date-mismatch"
    shutil.copytree(pilot_package["root"], tampered)
    manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
    selected_ids, selected_records = _verify_frame(tampered, manifest)
    case_path = next((tampered / "reviewer-a" / "cases").glob("*.json"))
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case["target_date"] = "2000-01-01"
    _write_json(case_path, case)

    with pytest.raises(
        ValidationPackageIntegrityError,
        match="reviewer target date does not match frame",
    ):
        _verify_cases(tampered, manifest, selected_ids, selected_records)


def test_verify_cases_rejects_double_review_evidence_mismatch(
    tmp_path: Path,
    pilot_package: dict[str, Any],
) -> None:
    tampered = tmp_path / "double-review-evidence-mismatch"
    shutil.copytree(pilot_package["root"], tampered)
    manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
    selected_ids, selected_records = _verify_frame(tampered, manifest)
    case_path = next((tampered / "reviewer-b" / "cases").glob("*.json"))
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case["evidence"]["before_imagery"]["reason"] = (
        "Reviewer-B fixture was changed independently."
    )
    _write_json(case_path, case)

    with pytest.raises(
        ValidationPackageIntegrityError,
        match="double-review evidence differs between reviewers",
    ):
        _verify_cases(tampered, manifest, selected_ids, selected_records)


@pytest.mark.parametrize("bad_reason", [None, ""])
def test_insufficient_evidence_requires_a_nonempty_reason(
    bad_reason: str | None,
    pilot_package: dict[str, Any],
) -> None:
    case_path = next(
        (pilot_package["root"] / "reviewer-a" / "cases").glob("*.json")
    )
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case["evidence"]["before_imagery"] = {
        "role": "before_imagery",
        "status": "insufficient",
        "reason": bad_reason,
        "independence_class": "operational_source_same_sensor",
        "local_path": "evidence/fixture/before.png",
        "local_bytes": 1,
        "local_sha256": "a" * 64,
        "source": {"fixture": True},
    }
    schema = json.loads(
        (
            REPOSITORY_ROOT
            / "docs/contracts/phase2a/schemas/validation-case-v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    with pytest.raises(ValidationPackageIntegrityError, match="reason"):
        _validate_json(case, schema, "insufficient-evidence-fixture")
