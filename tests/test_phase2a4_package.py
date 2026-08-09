"""Offline deterministic and tamper tests for the Phase 2A.4 packager."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.detection.baseline_manifest import sha256_file
from src.detection.identity import canonical_geometry_sha256, canonical_sha256
from src.validation.phase2a4_package import (
    COVERAGE_CONTRACT,
    METHOD_FAMILIES,
    PACKAGE_ID_PREFIX,
    Phase2A4PackageError,
    Phase2A4PackageIntegrityError,
    _comparison_availability,
    _coverage_summary,
    _normalize_source_binding,
    _source_inventory,
    _assert_blank_review,
    _validate_packaged_evidence_mapping_binding,
    _validate_package_identity_binding,
    _verify_checksum_artifact,
    deterministic_blind_mapping,
)


def _blind_ids():
    return [f"p2a3-blind-v1-{index:024x}" for index in range(60)]


def _candidates():
    return {
        family: (f"{family}-candidate-zero-v1", f"{family}-candidate-one-v1")
        for family in METHOD_FAMILIES
    }


def _blank_review():
    blank_method = {
        "availability": "not_generated_in_2a3",
        "option_a": None,
        "option_b": None,
        "display_order": [],
        "preference": None,
        "reviewer_confidence": None,
        "evidence_reason": None,
        "selected_or_activated": False,
    }
    return {
        "schema_version": "1.0.0",
        "blind_case_id": _blind_ids()[0],
        "review_status": "unreviewed",
        "reviewer": {
            "pseudonymous_id": None,
            "qualification_attested": None,
            "independence_attested": None,
        },
        "change_assessment": {
            "change_label": None,
            "reason": None,
            "evidence_sufficiency": None,
            "artifact_flags": [],
        },
        "temporal_assessment": {"confidence": None, "reason": None},
        "land_cover_assessment": {
            "context": None,
            "confidence": None,
            "reason": None,
        },
        "contextual_signature": {"label": None, "reason": None},
        "method_comparisons": {
            family: copy.deepcopy(blank_method)
            for family in (*METHOD_FAMILIES, "mapbiomas", "contextual_signature")
        },
        "usability": {
            "review_duration_seconds": None,
            "missing_or_confusing_evidence": [],
            "tool_issue": None,
        },
        "notes": None,
    }


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("change_assessment", "evidence_sufficiency"), "sufficient"),
        (("change_assessment", "artifact_flags"), ["cloud"]),
        (("temporal_assessment", "reason"), "assessment"),
        (("land_cover_assessment", "confidence"), "high"),
        (("land_cover_assessment", "reason"), "assessment"),
        (("contextual_signature", "reason"), "assessment"),
        (("usability", "review_duration_seconds"), 1),
        (("usability", "missing_or_confusing_evidence"), ["missing"]),
        (("usability", "tool_issue"), "issue"),
        (("method_comparisons", "mapbiomas", "preference"), "A"),
        (("method_comparisons", "contextual_signature", "availability"), "available"),
    ),
)
def test_blank_review_rejects_every_human_and_phase2a5_field(path, value):
    review = _blank_review()
    _assert_blank_review(review)
    target = review
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(Phase2A4PackageIntegrityError):
        _assert_blank_review(review)


def test_blinding_is_exactly_balanced_bijective_and_order_invariant():
    ids = _blind_ids()
    candidates = _candidates()
    key = "a" * 64
    first = deterministic_blind_mapping(ids, candidates, blinding_key=key)
    second = deterministic_blind_mapping(list(reversed(ids)), candidates, blinding_key=key)
    assert first == second
    for family in METHOD_FAMILIES:
        pair = set(candidates[family])
        assert sum(first[blind][family]["A"] == candidates[family][0] for blind in ids) == 30
        for blind in ids:
            assert set(first[blind][family].values()) == pair


def test_blinding_rejects_case_replacement_or_non_digest_key():
    with pytest.raises(Phase2A4PackageError, match="exactly 60"):
        deterministic_blind_mapping(_blind_ids()[:-1], _candidates(), blinding_key="a" * 64)
    with pytest.raises(Phase2A4PackageError, match="SHA-256"):
        deterministic_blind_mapping(_blind_ids(), _candidates(), blinding_key="not-a-key")


def _small_checksum_package(root: Path):
    artifact = root / "payload.txt"
    artifact.write_text("fixed\n", encoding="utf-8")
    item = {"path": "payload.txt", "bytes": artifact.stat().st_size, "sha256": sha256_file(artifact)}
    manifest = {"artifact_inventory": [item]}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "CHECKSUMS.sha256").write_text(
        f"{sha256_file(root / 'manifest.json')}  manifest.json\n"
        f"{item['sha256']}  payload.txt\n",
        encoding="utf-8",
    )
    return manifest


def test_checksum_inventory_rejects_tamper_unlisted_and_traversal(tmp_path):
    manifest = _small_checksum_package(tmp_path)
    _verify_checksum_artifact(tmp_path, manifest, error_type=Phase2A4PackageIntegrityError)
    (tmp_path / "payload.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(Phase2A4PackageIntegrityError, match="checksum mismatch"):
        _verify_checksum_artifact(tmp_path, manifest, error_type=Phase2A4PackageIntegrityError)

    clean = tmp_path / "clean"
    clean.mkdir()
    clean_manifest = _small_checksum_package(clean)
    (clean / "unlisted.txt").write_text("x", encoding="utf-8")
    with pytest.raises(Phase2A4PackageIntegrityError, match="inventory mismatch"):
        _verify_checksum_artifact(clean, clean_manifest, error_type=Phase2A4PackageIntegrityError)

    traversal = copy.deepcopy(clean_manifest)
    traversal["artifact_inventory"][0]["path"] = "../payload.txt"
    with pytest.raises(Phase2A4PackageIntegrityError):
        _verify_checksum_artifact(clean, traversal, error_type=Phase2A4PackageIntegrityError)


def test_checksum_inventory_rejects_symlink(tmp_path):
    manifest = _small_checksum_package(tmp_path)
    (tmp_path / "alias.txt").symlink_to(tmp_path / "payload.txt")
    with pytest.raises(Phase2A4PackageIntegrityError, match="symlink"):
        _verify_checksum_artifact(tmp_path, manifest, error_type=Phase2A4PackageIntegrityError)


@pytest.mark.parametrize(
    "binding_path",
    (
        ("package_identity_inputs", "candidate_evidence_manifest_sha256"),
        ("package_identity_inputs", "candidate_evidence_checksums_sha256"),
        ("blinding_derivation", "coordinator_only_evidence_checksums_sha256"),
    ),
)
def test_packaged_evidence_hashes_bind_mapping_identity_and_blinding(
    tmp_path, binding_path
):
    evidence_root = tmp_path / "candidate-evidence"
    evidence_root.mkdir()
    (evidence_root / "manifest.json").write_text('{"fixed":true}\n', encoding="utf-8")
    (evidence_root / "CHECKSUMS.sha256").write_text(
        f"{'a' * 64}  fixed.bin\n", encoding="utf-8"
    )
    mapping = {
        "package_identity_inputs": {
            "candidate_evidence_manifest_sha256": sha256_file(
                evidence_root / "manifest.json"
            ),
            "candidate_evidence_checksums_sha256": sha256_file(
                evidence_root / "CHECKSUMS.sha256"
            ),
        },
        "blinding_derivation": {
            "coordinator_only_evidence_checksums_sha256": sha256_file(
                evidence_root / "CHECKSUMS.sha256"
            )
        },
    }
    _validate_packaged_evidence_mapping_binding(mapping, evidence_root)

    tampered = copy.deepcopy(mapping)
    tampered[binding_path[0]][binding_path[1]] = "0" * 64
    with pytest.raises(
        Phase2A4PackageIntegrityError,
        match="packaged candidate-evidence blinding or identity binding mismatch",
    ):
        _validate_packaged_evidence_mapping_binding(tampered, evidence_root)


def test_package_identity_binds_runtime_and_generator_inventory():
    identity = {
        "pipeline": "phase2a4-derivative-package-v1",
        "runtime_versions": {"python": "fixed"},
        "generator_source_inventory": [
            {"path": "generator.py", "bytes": 1, "sha256": "a" * 64}
        ],
    }
    manifest = {
        "package_id": PACKAGE_ID_PREFIX + canonical_sha256(identity),
        "runtime_versions": copy.deepcopy(identity["runtime_versions"]),
        "generator_source_inventory": copy.deepcopy(
            identity["generator_source_inventory"]
        ),
    }
    mapping = {"package_identity_inputs": copy.deepcopy(identity)}
    _validate_package_identity_binding(manifest, mapping)

    tampered = copy.deepcopy(manifest)
    tampered["runtime_versions"]["python"] = "different"
    with pytest.raises(
        Phase2A4PackageIntegrityError, match="runtime/source identity"
    ):
        _validate_package_identity_binding(tampered, mapping)


def test_package_source_inventory_binds_imported_provenance_validators():
    repository_root = Path(__file__).resolve().parents[1]
    paths = [item["path"] for item in _source_inventory(repository_root)]
    assert "src/detection/baseline_manifest.py" in paths
    assert "src/detection/identity.py" in paths
    assert "src/validation/phase2a4_evidence.py" in paths
    assert "src/validation/phase2a4_rainfall.py" in paths


def test_partial_comparisons_and_missing_cells_remain_explicit():
    panels = [
        {"status": "partial", "path": "panel.png"},
        {"status": "unreviewable", "path": None},
    ]
    cells = [
        {"availability": "available"},
        {"availability": "rejected_low_coverage"},
        {"availability": "unavailable"},
        {"availability": "error"},
    ]
    availability, reason = _comparison_availability(panels, cells)
    assert availability == "partial"
    assert reason and "retained without replacement" in reason
    assert _coverage_summary(cells) == {
        "available_cell_count": 1,
        "rejected_low_coverage_cell_count": 1,
        "unavailable_cell_count": 2,
    }


def test_source_binding_preserves_full_query_fingerprint_and_missing_scenes():
    case_window = {
        "column_offset": 10,
        "row_offset": 20,
        "width": 30,
        "height": 40,
        "transform": [20.0, 0.0, 290280.0, 0.0, -20.0, 9231380.0],
        "bounds": [290280.0, 9230580.0, 290880.0, 9231380.0],
        "pixel_size_m": 20,
        "aligned_to_reference_grid": True,
        "same_window_for_all_factorial_cells": True,
        "fixed_before_candidate_evaluation": True,
    }
    case_window["window_definition_sha256"] = canonical_sha256(case_window)
    intersects = {
        "type": "Polygon",
        "coordinates": [[[-40.0, -8.0], [-39.9, -8.0], [-39.9, -7.9], [-40.0, -7.9], [-40.0, -8.0]]],
    }
    interval = "2026-07-16T00:00:00Z/2026-07-17T00:00:00Z"
    request = {
        "stac_endpoint": "https://earth-search.aws.element84.com/v1",
        "collection": "sentinel-2-l2a",
        "intersects": intersects,
        "datetime": interval,
        "query": {"eo:cloud_cover": {"lt": 60}},
        "max_items": None,
        "pagination_policy": "all_pages_until_exhausted",
    }
    query = {
        "target_date": "2026-07-16",
        "spatial_filter": "intersects_fixed_grid_aligned_case_window",
        "temporal_filter": "target_date_inclusive_to_next_date_exclusive",
        "eo_cloud_cover_lt": 60,
        "intersects": intersects,
        "datetime": interval,
        "result_limit": None,
        "pagination_policy": "all_pages_until_exhausted",
        "intersects_geometry_sha256": canonical_geometry_sha256(intersects)[1],
        "canonical_payload_sha256": canonical_sha256(request),
    }
    record = {
        "target_date": "2026-07-16",
        "source_query": {
            "catalog_accessed_at": "2026-08-03T12:00:00-03:00",
            "query": query,
        },
        "source_scenes": [],
        "grid": {
            "case_window": case_window,
            "coverage_contract": copy.deepcopy(COVERAGE_CONTRACT),
        },
        "drought": {"rainfall_reference": {"status": "missing", "reason": "retained"}},
    }
    binding = _normalize_source_binding(record)
    assert binding["query"] == query
    assert binding["source_scenes"] == []
    assert binding["rainfall_reference"]["status"] == "missing"
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/contracts/phase2a/schemas/phase2a4-method-evidence-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    schema_contract = schema["$defs"]["source_binding"]["properties"][
        "coverage_contract"
    ]["const"]
    assert binding["coverage_contract"] == schema_contract == COVERAGE_CONTRACT
