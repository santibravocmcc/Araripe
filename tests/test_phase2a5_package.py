"""Deterministic, blank-state, isolation, and tamper tests for Package 2A.5."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

import src.validation.phase2a5_package as package
from src.detection.baseline_manifest import sha256_file
from src.validation.phase2a5_package import (
    ACCEPTED_PHASE2A4_CHECKSUMS_SHA256,
    ACCEPTED_PHASE2A4_MANIFEST_SHA256,
    ACCEPTED_PHASE2A4_PACKAGE_ID,
    ALL_METHOD_FAMILIES,
    NEW_METHOD_FAMILIES,
    PACKAGED_GENERATOR_MATERIAL,
    Phase2A5PackageError,
    Phase2A5PackageIntegrityError,
    _assert_blank_review,
    _candidate_ids,
    _comparison_availability,
    _inventory,
    _primary_assessment_complete,
    _primary_snapshot,
    _reviewer_leakage_scan,
    _source_inventory,
    _validate_overlap,
    _validate_packaged_generator_material,
    _validate_parent_phase2a4_bytes,
    _validate_source_evidence_mapping,
    _verify_checksum_artifact,
    _write_checksums,
    deterministic_phase2a5_blind_mapping,
)


ROOT = Path(__file__).resolve().parents[1]


def _blind_ids() -> list[str]:
    return [f"p2a3-blind-v1-{index:024x}" for index in range(60)]


def _candidates() -> dict[str, tuple[str, str]]:
    return {
        family: (f"{family}-candidate-zero-v1", f"{family}-candidate-one-v1")
        for family in NEW_METHOD_FAMILIES
    }


def _blank_review() -> dict:
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
            family: copy.deepcopy(blank_method) for family in ALL_METHOD_FAMILIES
        },
        "usability": {
            "review_duration_seconds": None,
            "missing_or_confusing_evidence": [],
            "tool_issue": None,
        },
        "notes": None,
    }


def test_frozen_registry_exposes_exact_two_candidates_per_new_family():
    registry = json.loads(
        (ROOT / "config/phase2a5_context_candidates_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert _candidate_ids(registry) == {
        "mapbiomas": (
            "natural-vegetation-share-0.50-v1",
            "natural-vegetation-share-0.75-v1",
        ),
        "contextual_signature": (
            "dominant-assessed-share-0.60-v1",
            "plurality-assessed-margin-0.15-v1",
        ),
    }


def test_exact_phase2a4_derivative_identity_is_frozen_for_additive_parenting():
    parent = ROOT / "data/validation/phase2a4-method-comparison-v1"
    manifest = json.loads((parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["package_id"] == ACCEPTED_PHASE2A4_PACKAGE_ID
    assert sha256_file(parent / "manifest.json") == ACCEPTED_PHASE2A4_MANIFEST_SHA256
    assert (
        sha256_file(parent / "CHECKSUMS.sha256")
        == ACCEPTED_PHASE2A4_CHECKSUMS_SHA256
    )


def test_phase2a5_blinding_is_balanced_bijective_and_order_invariant():
    ids = _blind_ids()
    candidates = _candidates()
    first = deterministic_phase2a5_blind_mapping(
        ids, candidates, blinding_key="a" * 64
    )
    second = deterministic_phase2a5_blind_mapping(
        list(reversed(ids)), candidates, blinding_key="a" * 64
    )
    assert first == second
    for family in NEW_METHOD_FAMILIES:
        assert (
            sum(
                first[blind][family]["A"] == candidates[family][0]
                for blind in ids
            )
            == 30
        )
        for blind in ids:
            assert set(first[blind][family].values()) == set(candidates[family])


def test_phase2a5_blinding_rejects_population_change_and_unkeyed_input():
    with pytest.raises(Phase2A5PackageError, match="exactly 60"):
        deterministic_phase2a5_blind_mapping(
            _blind_ids()[:-1], _candidates(), blinding_key="a" * 64
        )
    with pytest.raises(Phase2A5PackageError, match="SHA-256"):
        deterministic_phase2a5_blind_mapping(
            _blind_ids(), _candidates(), blinding_key="not-a-digest"
        )


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("change_assessment", "change_label"), "real_change"),
        (("change_assessment", "artifact_flags"), ["cloud"]),
        (("temporal_assessment", "reason"), "assessment"),
        (("land_cover_assessment", "confidence"), "high"),
        (("contextual_signature", "label"), "fire_like"),
        (("usability", "review_duration_seconds"), 1),
        (("method_comparisons", "mapbiomas", "preference"), "A"),
        (("method_comparisons", "contextual_signature", "selected_or_activated"), True),
    ),
)
def test_blank_review_rejects_every_human_or_selection_field(path, value):
    review = _blank_review()
    _assert_blank_review(review)
    target = review
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    with pytest.raises(Phase2A5PackageIntegrityError):
        _assert_blank_review(review)


def test_primary_gate_requires_and_snapshots_contextual_signature():
    review = _blank_review()
    review["change_assessment"].update(
        {
            "change_label": "uncertain",
            "reason": "fixed primary reason",
            "evidence_sufficiency": "conflicting",
        }
    )
    review["temporal_assessment"] = {"confidence": "low", "reason": "reason"}
    review["land_cover_assessment"] = {
        "context": "mixed",
        "confidence": "low",
        "reason": "reason",
    }
    assert not _primary_assessment_complete(review)
    review["contextual_signature"] = {
        "label": "mixed_or_uncertain",
        "reason": "non-causal appearance only",
    }
    assert _primary_assessment_complete(review)
    assert _primary_snapshot(review)["contextual_signature"] == review[
        "contextual_signature"
    ]


def _small_checksum_package(root: Path) -> dict:
    payload = root / "payload.txt"
    payload.write_text("fixed\n", encoding="utf-8")
    item = {
        "path": "payload.txt",
        "bytes": payload.stat().st_size,
        "sha256": sha256_file(payload),
    }
    manifest = {"artifact_inventory": [item]}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "CHECKSUMS.sha256").write_text(
        f"{sha256_file(root / 'manifest.json')}  manifest.json\n"
        f"{item['sha256']}  payload.txt\n",
        encoding="utf-8",
    )
    return manifest


def test_deep_checksum_inventory_rejects_tamper_and_unlisted_file(tmp_path):
    manifest = _small_checksum_package(tmp_path)
    _verify_checksum_artifact(
        tmp_path, manifest, error_type=Phase2A5PackageIntegrityError
    )
    (tmp_path / "payload.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(Phase2A5PackageIntegrityError, match="checksum mismatch"):
        _verify_checksum_artifact(
            tmp_path, manifest, error_type=Phase2A5PackageIntegrityError
        )
    clean = tmp_path / "clean"
    clean.mkdir()
    clean_manifest = _small_checksum_package(clean)
    (clean / "unlisted.txt").write_text("x", encoding="utf-8")
    with pytest.raises(Phase2A5PackageIntegrityError, match="inventory mismatch"):
        _verify_checksum_artifact(
            clean, clean_manifest, error_type=Phase2A5PackageIntegrityError
        )


def test_phase2a4_opaque_bytes_are_preserved_except_declared_replacements(tmp_path):
    preserved = tmp_path / "coordinator/blinding-map.json"
    preserved.parent.mkdir(parents=True)
    preserved.write_text("fixed mapping\n", encoding="utf-8")
    replaced = tmp_path / "reviewer-a/index.html"
    replaced.parent.mkdir(parents=True)
    replaced.write_text("new interface\n", encoding="utf-8")
    parent_manifest = {
        "artifact_inventory": [
            {
                "path": "coordinator/blinding-map.json",
                "bytes": preserved.stat().st_size,
                "sha256": sha256_file(preserved),
            },
            {
                "path": "reviewer-a/index.html",
                "bytes": 1,
                "sha256": "0" * 64,
            },
        ]
    }
    _validate_parent_phase2a4_bytes(tmp_path, parent_manifest)
    preserved.write_text("changed mapping\n", encoding="utf-8")
    with pytest.raises(Phase2A5PackageIntegrityError, match="opaque artifact"):
        _validate_parent_phase2a4_bytes(tmp_path, parent_manifest)


def test_reviewer_leakage_scan_rejects_true_candidate_and_sample_ids(tmp_path):
    registry = {
        "strong_subset": {"candidate_ids": ["strong-zero", "strong-one"]},
        "contextual_signature": {
            "candidate_ids": ["signature-zero", "signature-one"]
        },
    }
    mapping = {"cases": [{"sample_id": "secret-sample"}]}
    for slot in ("reviewer-a", "reviewer-b"):
        root = tmp_path / slot
        root.mkdir()
        (root / "safe.json").write_text(
            json.dumps({"blind_option_id": "opaque"}), encoding="utf-8"
        )
    _reviewer_leakage_scan(tmp_path, registry=registry, mapping=mapping)
    (tmp_path / "reviewer-a/leak.txt").write_text(
        "strong-zero", encoding="utf-8"
    )
    with pytest.raises(Phase2A5PackageIntegrityError, match="identity leaked"):
        _reviewer_leakage_scan(tmp_path, registry=registry, mapping=mapping)


def test_overlap_requires_identical_sidecars_and_panel_bytes(tmp_path):
    blind = _blind_ids()[0]
    for slot in ("reviewer-a", "reviewer-b"):
        root = tmp_path / slot
        (root / "context-evidence" / blind / "mapbiomas").mkdir(parents=True)
        (root / "assignment.json").write_text(
            json.dumps({"blind_case_ids": [blind]}), encoding="utf-8"
        )
        (root / "context-evidence" / f"{blind}.json").write_text(
            '{"fixed":true}\n', encoding="utf-8"
        )
        (root / "context-evidence" / blind / "mapbiomas/A.png").write_bytes(
            b"same"
        )
    _validate_overlap(tmp_path)
    (
        tmp_path
        / "reviewer-b/context-evidence"
        / blind
        / "mapbiomas/A.png"
    ).write_bytes(b"different")
    with pytest.raises(Phase2A5PackageIntegrityError, match="overlap context panel"):
        _validate_overlap(tmp_path)


def test_missing_and_partial_panel_statuses_remain_explicit():
    assert _comparison_availability(
        [{"status": "available"}, {"status": "available"}]
    ) == ("available", None)
    assert _comparison_availability(
        [{"status": "partial"}, {"status": "unreviewable"}]
    )[0] == "partial"
    availability, reason = _comparison_availability(
        [{"status": "unreviewable"}, {"status": "unreviewable"}]
    )
    assert availability == "unreviewable"
    assert reason and "retained without replacement" in reason


def test_source_panels_bind_mapping_and_reviewer_artifacts_without_replacement():
    blind = _blind_ids()[0]
    panels = {}
    families = {}
    comparisons = {}
    review_method_metadata = {}
    for family in NEW_METHOD_FAMILIES:
        first = f"{family}-zero"
        second = f"{family}-one"
        panel_a = {
            "status": "available",
            "reason": None,
            "path": f"source/{family}/a.png",
            "bytes": 4,
            "sha256": "a" * 64,
            "media_type": "image/png",
        }
        panel_b = {
            "status": "unreviewable",
            "reason": "retained",
            "path": None,
            "bytes": None,
            "sha256": None,
            "media_type": None,
        }
        panels[family] = {first: panel_a, second: panel_b}
        families[family] = {
            "A": {
                "candidate_id": first,
                "blind_option_id": f"opaque-{family}-a",
                "source_panel": copy.deepcopy(panel_a),
            },
            "B": {
                "candidate_id": second,
                "blind_option_id": f"opaque-{family}-b",
                "source_panel": copy.deepcopy(panel_b),
            },
        }
        artifact = {
            "path": f"context-evidence/{blind}/{family}/A.png",
            "bytes": 4,
            "sha256": "a" * 64,
            "media_type": "image/png",
            "role": "blinded_context_comparison_panel",
        }
        comparisons[family] = {
            "availability": "partial",
            "reason": "Evidence is partial and retained without replacement.",
            "display_order": ["A", "B"],
            "option_a": {
                "blind_option_id": f"opaque-{family}-a",
                "artifacts": [artifact],
            },
            "option_b": {
                "blind_option_id": f"opaque-{family}-b",
                "artifacts": [],
            },
            "primary_assessment_required_first": True,
            "selected_or_activated": False,
        }
        review_method_metadata[family] = {
            "availability": "partial",
            "option_a": f"opaque-{family}-a",
            "option_b": f"opaque-{family}-b",
            "display_order": ["A", "B"],
            "preference": None,
            "reviewer_confidence": None,
            "evidence_reason": None,
            "selected_or_activated": False,
        }
    mapping = {
        "cases": [
            {
                "blind_case_id": blind,
                "sample_id": "sample-fixed",
                "families": families,
            }
        ]
    }
    records = {
        blind: {
            "blind_case_id": blind,
            "sample_id": "sample-fixed",
            "candidate_panels": panels,
        }
    }
    sidecars = {
        blind: {
            "comparisons": comparisons,
            "review_method_metadata": review_method_metadata,
        }
    }
    _validate_source_evidence_mapping(
        mapping, records=records, sidecars=sidecars
    )
    tampered = copy.deepcopy(mapping)
    tampered["cases"][0]["families"]["mapbiomas"]["A"]["source_panel"][
        "sha256"
    ] = "b" * 64
    with pytest.raises(Phase2A5PackageIntegrityError, match="source panel binding"):
        _validate_source_evidence_mapping(
            tampered, records=records, sidecars=sidecars
        )


def test_generator_source_inventory_binds_additive_reviewer_and_schemas():
    paths = {item["path"] for item in _source_inventory(ROOT)}
    assert "src/validation/phase2a4_package.py" in paths
    assert "src/validation/phase2a5_package.py" in paths
    assert "docs/contracts/phase2a/phase2a5-reviewer.js" in paths
    assert (
        "docs/contracts/phase2a/schemas/phase2a5-derivative-manifest-v1.schema.json"
        in paths
    )


def test_canonical_source_anchor_rejects_coherently_resealed_schema_tamper(
    tmp_path,
):
    for source, destinations in PACKAGED_GENERATOR_MATERIAL.items():
        for relative in destinations:
            destination = tmp_path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, destination)

    manifest = {"generator_source_inventory": _source_inventory(ROOT)}

    def reseal() -> None:
        manifest["artifact_inventory"] = _inventory(tmp_path)
        (tmp_path / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )
        _write_checksums(tmp_path, manifest["artifact_inventory"])

    reseal()
    _verify_checksum_artifact(
        tmp_path, manifest, error_type=Phase2A5PackageIntegrityError
    )
    _validate_packaged_generator_material(
        tmp_path, manifest, repository_root=ROOT
    )

    source = (
        "docs/contracts/phase2a/schemas/"
        "phase2a5-review-export-v1.schema.json"
    )
    packaged_schema = tmp_path / "schemas/phase2a5-review-export-v1.schema.json"
    packaged_schema.write_text(
        packaged_schema.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    self_declared = next(
        item
        for item in manifest["generator_source_inventory"]
        if item["path"] == source
    )
    self_declared["bytes"] = packaged_schema.stat().st_size
    self_declared["sha256"] = sha256_file(packaged_schema)
    reseal()
    _verify_checksum_artifact(
        tmp_path, manifest, error_type=Phase2A5PackageIntegrityError
    )
    with pytest.raises(
        Phase2A5PackageIntegrityError,
        match="canonical repository bytes",
    ):
        _validate_packaged_generator_material(
            tmp_path, manifest, repository_root=ROOT
        )


def test_derivative_build_lock_fails_closed_and_releases(tmp_path: Path):
    target = tmp_path / "derivative"
    lock = package._acquire_build_lock(target)
    try:
        assert lock == tmp_path / ".derivative.lock"
        with pytest.raises(Phase2A5PackageError, match="build lock already exists"):
            package._acquire_build_lock(target)
        assert lock.is_file()
    finally:
        package._release_build_lock(lock)
    assert not lock.exists()


def test_derivative_publication_refuses_an_appeared_target(tmp_path: Path):
    staging = tmp_path / ".derivative-staging"
    target = tmp_path / "derivative"
    staging.mkdir()
    (staging / "manifest.json").write_text("{}\n", encoding="utf-8")
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(Phase2A5PackageError, match="appeared during construction"):
        package._publish_directory_no_clobber(staging, target)

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert (staging / "manifest.json").is_file()


def test_derivative_publication_refuses_a_broken_symlink(tmp_path: Path):
    staging = tmp_path / ".derivative-staging"
    target = tmp_path / "derivative"
    missing_target = tmp_path / "missing-derivative"
    staging.mkdir()
    (staging / "manifest.json").write_text("{}\n", encoding="utf-8")
    target.symlink_to(missing_target, target_is_directory=True)

    with pytest.raises(Phase2A5PackageError, match="appeared during construction"):
        package._publish_directory_no_clobber(staging, target)

    assert target.is_symlink()
    assert target.readlink() == missing_target
    assert (staging / "manifest.json").is_file()


def test_derivative_builder_refuses_a_broken_output_symlink(tmp_path: Path):
    target = tmp_path / "derivative"
    missing_target = tmp_path / "missing-derivative"
    target.symlink_to(missing_target, target_is_directory=True)

    with pytest.raises(Phase2A5PackageError, match="already exists"):
        package.build_phase2a5_derivative_package(
            phase2a3_parent_root=tmp_path / "phase2a3-unused",
            phase2a4_derivative_root=tmp_path / "phase2a4-unused",
            registry_path=tmp_path / "registry-unused.json",
            context_manifest_path=tmp_path / "context-unused/manifest.json",
            evidence_root=tmp_path / "evidence-unused",
            output_root=target,
            repository_root=ROOT,
            generated_at="2026-08-09T12:00:00-03:00",
            generation_command=["synthetic-phase2a5-build"],
        )

    assert target.is_symlink()
    assert target.readlink() == missing_target
