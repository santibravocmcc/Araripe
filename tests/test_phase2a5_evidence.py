"""Deterministic, local-only tests for Phase 2A.5 contextual evidence."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from jsonschema import Draft202012Validator, ValidationError
from rasterio.transform import from_origin
from rasterio.warp import transform_geom

import src.validation.phase2a5_evidence as evidence
from src.validation.phase2a5_context import load_context_registry
from src.validation.phase2a5_evidence import (
    BLANK_REVIEW,
    CASE_CLAIMS,
    COL10_KEY,
    COL3_KEY,
    MAPBIOMAS_CANDIDATES,
    SIGNATURE_CANDIDATES,
    Phase2A5EvidenceConfig,
    Phase2A5EvidenceError,
    _artifact,
    _canonical_sha256,
    _candidate_panels,
    _input_case_maps,
    _map_panel_bytes,
    _mapbiomas_context,
    _normalize_aggregation,
    _polygon_indices_on_context_grid,
    _read_polygon_values,
    _signature_panel_bytes,
    _source_binding,
    _spectral_stratum,
    _summary_from_context_api,
    _verify_checksum_inventory,
    _verify_record,
    _write_checksum_inventory,
    _write_npy,
    build_phase2a5_evidence,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPOSITORY_ROOT / "config/phase2a5_context_candidates_v1.json"
SCHEMA_ROOT = REPOSITORY_ROOT / "docs/contracts/phase2a/schemas"


def _registry():
    return load_context_registry(REGISTRY_PATH)


def _write_uint8_raster(path: Path, values: np.ndarray, transform) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        nodata=0,
    ) as dataset:
        dataset.write(np.asarray(values, dtype=np.uint8), 1)


def _full_raster_geometry() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [0.0, 0.0],
                [0.03, 0.0],
                [0.03, 0.03],
                [0.0, 0.03],
                [0.0, 0.0],
            ]
        ],
    }


def test_evidence_schemas_are_strict_and_external_bindings_are_satisfiable():
    manifest_schema = json.loads(
        (SCHEMA_ROOT / "phase2a5-context-evidence-manifest-v1.schema.json").read_text()
    )
    case_schema = json.loads(
        (SCHEMA_ROOT / "phase2a5-context-evidence-case-v1.schema.json").read_text()
    )
    Draft202012Validator.check_schema(manifest_schema)
    Draft202012Validator.check_schema(case_schema)

    external_schema = {
        "$ref": "#/$defs/external_artifact",
        "$defs": manifest_schema["$defs"],
    }
    binding = {
        "path": "data/input.json",
        "bytes": 1,
        "sha256": "a" * 64,
        "scope": "repository_relative_external_input",
    }
    Draft202012Validator(external_schema).validate(binding)
    with pytest.raises(ValidationError):
        Draft202012Validator(external_schema).validate(
            {**binding, "unbound_extra": True}
        )

    raw_properties = case_schema["properties"]["raw_detection"]["properties"]
    assert "source_binding_sha256" in raw_properties
    assert "source_feature_sha256" not in raw_properties


def _synthetic_resealable_evidence(root: Path, repository_root: Path) -> dict:
    """Create a checksum-complete minimal envelope for early binding checks."""
    source_paths = (
        "src/validation/phase2a5_context.py",
        "src/validation/phase2a5_evidence.py",
        "scripts/build_phase2a5_evidence.py",
        "scripts/validate_phase2a5_evidence.py",
        "config/phase2a5_context_candidates_v1.json",
        "docs/contracts/phase2a/schemas/phase2a5-context-evidence-manifest-v1.schema.json",
        "docs/contracts/phase2a/schemas/phase2a5-context-evidence-case-v1.schema.json",
    )
    for relative in source_paths:
        path = repository_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if path.suffix == ".json" else "synthetic\n")

    packaged_manifest_schema = (
        root / "schemas/phase2a5-context-evidence-manifest-v1.schema.json"
    )
    packaged_case_schema = root / "schemas/phase2a5-context-evidence-case-v1.schema.json"
    packaged_manifest_schema.parent.mkdir(parents=True, exist_ok=True)
    packaged_manifest_schema.write_bytes(
        (
            repository_root
            / "docs/contracts/phase2a/schemas/phase2a5-context-evidence-manifest-v1.schema.json"
        ).read_bytes()
    )
    packaged_case_schema.write_bytes(
        (
            repository_root
            / "docs/contracts/phase2a/schemas/phase2a5-context-evidence-case-v1.schema.json"
        ).read_bytes()
    )
    manifest = {
        "schema_bindings": {
            "manifest": evidence._artifact(packaged_manifest_schema, root),
            "case": evidence._artifact(packaged_case_schema, root),
        },
        "generator_source_inventory": evidence._generator_source_inventory(
            repository_root
        ),
        "runtime_versions": evidence._runtime_versions(),
        "artifact_inventory": evidence._actual_inventory(root),
    }
    evidence._write_json(root / "manifest.json", manifest)
    evidence._write_checksum_inventory(root)
    evidence._verify_checksum_inventory(root)
    return manifest


def _reseal_synthetic_evidence(root: Path, manifest: dict) -> None:
    manifest["artifact_inventory"] = evidence._actual_inventory(root)
    evidence._write_json(root / "manifest.json", manifest)
    evidence._write_checksum_inventory(root)
    evidence._verify_checksum_inventory(root)


@pytest.mark.parametrize(
    ("tamper", "message"),
    (
        ("schema_bytes", "packaged manifest schema differs"),
        ("schema_descriptor", "schema bindings differ"),
    ),
)
def test_resealed_evidence_schema_tamper_is_rejected(
    tmp_path: Path,
    tamper: str,
    message: str,
):
    repository_root = tmp_path / "repository"
    artifact = tmp_path / "evidence"
    manifest = _synthetic_resealable_evidence(artifact, repository_root)
    packaged_schema = (
        artifact / "schemas/phase2a5-context-evidence-manifest-v1.schema.json"
    )
    if tamper == "schema_bytes":
        packaged_schema.write_bytes(packaged_schema.read_bytes() + b"\n")
        manifest["schema_bindings"]["manifest"] = evidence._artifact(
            packaged_schema, artifact
        )
    elif tamper == "schema_descriptor":
        manifest["schema_bindings"]["manifest"]["sha256"] = "0" * 64
    else:  # pragma: no cover - parametrization is exhaustive.
        raise AssertionError(tamper)
    _reseal_synthetic_evidence(artifact, manifest)

    with pytest.raises(Phase2A5EvidenceError, match=message):
        evidence.validate_phase2a5_evidence_artifact(
            artifact,
            repository_root=repository_root,
        )


def test_resealed_evidence_parent_provenance_descriptor_is_rejected(
    tmp_path: Path,
    monkeypatch,
):
    repository_root = tmp_path / "repository"
    artifact = tmp_path / "evidence"
    manifest = _synthetic_resealable_evidence(artifact, repository_root)
    p2a3_root = repository_root / "data/validation/phase2a3"
    p2a4_root = repository_root / "data/validation/phase2a4"
    for parent in (p2a3_root, p2a4_root):
        parent.mkdir(parents=True)
        (parent / "manifest.json").write_text("{}\n", encoding="utf-8")
        (parent / "CHECKSUMS.sha256").write_text("synthetic\n", encoding="utf-8")
    p2a3_manifest = {"package_id": "synthetic-phase2a3"}
    p2a4_manifest = {"evidence_id": "synthetic-phase2a4"}
    manifest["parents"] = {
        "phase2a3": {
            "artifact_id": p2a3_manifest["package_id"],
            "manifest": evidence._external_artifact(
                p2a3_root / "manifest.json", repository_root
            ),
            "checksum_file": evidence._external_artifact(
                p2a3_root / "CHECKSUMS.sha256", repository_root
            ),
            "case_count": 60,
            "immutable_input": True,
        },
        "phase2a4": {
            "artifact_id": p2a4_manifest["evidence_id"],
            "manifest": evidence._external_artifact(
                p2a4_root / "manifest.json", repository_root
            ),
            "checksum_file": evidence._external_artifact(
                p2a4_root / "CHECKSUMS.sha256", repository_root
            ),
            "case_count": 60,
            "immutable_input": True,
        },
    }
    manifest["parents"]["phase2a3"]["manifest"]["sha256"] = "0" * 64
    _reseal_synthetic_evidence(artifact, manifest)
    monkeypatch.setattr(
        evidence,
        "_validate_frozen_inputs",
        lambda **_: (p2a3_manifest, p2a4_manifest, {}, {}),
    )

    with pytest.raises(
        Phase2A5EvidenceError, match="parent artifact provenance bindings changed"
    ):
        evidence.validate_phase2a5_evidence_artifact(
            artifact,
            parent_phase2a3_dir=p2a3_root,
            parent_phase2a4_dir=p2a4_root,
            candidate_registry_path=(
                repository_root / "config/phase2a5_context_candidates_v1.json"
            ),
            context_artifact_dir=repository_root / "data/validation/context",
            repository_root=repository_root,
        )


def test_case_schema_forces_blank_reviews_false_claims_and_panel_nullability():
    case_schema = json.loads(
        (SCHEMA_ROOT / "phase2a5-context-evidence-case-v1.schema.json").read_text()
    )
    Draft202012Validator(case_schema["properties"]["blank_review"]).validate(
        BLANK_REVIEW
    )
    populated = copy.deepcopy(BLANK_REVIEW)
    populated["qualified_label"] = "not permitted"
    with pytest.raises(ValidationError):
        Draft202012Validator(case_schema["properties"]["blank_review"]).validate(
            populated
        )

    Draft202012Validator(case_schema["properties"]["claims"]).validate(CASE_CLAIMS)
    selected = copy.deepcopy(CASE_CLAIMS)
    selected["selected_or_activated"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(case_schema["properties"]["claims"]).validate(selected)

    panel_schema = {
        "$ref": "#/$defs/panel",
        "$defs": case_schema["$defs"],
    }
    unreviewable = {
        "status": "unreviewable",
        "reason": "no assessable evidence",
        "path": None,
        "bytes": None,
        "sha256": None,
        "media_type": None,
    }
    Draft202012Validator(panel_schema).validate(unreviewable)
    with pytest.raises(ValidationError):
        Draft202012Validator(panel_schema).validate(
            {**unreviewable, "status": "available"}
        )


def test_polygon_summary_preserves_nodata_unmapped_and_ambiguous_categories():
    registry = _registry()
    values = np.asarray([[3, 4, 23, 15, 25, 0, 255]], dtype=np.uint8)
    selected = np.ones(values.shape, dtype=bool)

    summary = _summary_from_context_api(values, selected, COL3_KEY, registry)

    assert summary["pixel_count"] == 7
    assert summary["valid_pixel_count"] == 6
    assert summary["mapped_valid_pixel_count"] == 5
    assert summary["nodata_pixel_count"] == 1
    assert summary["unmapped_pixel_count"] == 1
    assert summary["class_histogram"] == {
        "0": 1,
        "3": 1,
        "4": 1,
        "15": 1,
        "23": 1,
        "25": 1,
        "255": 1,
    }
    assert summary["category_counts"] == {
        "natural_vegetation": 2,
        "other_natural_cover": 1,
        "anthropic_cover": 1,
        "uncertain_or_mixed": 1,
        "nodata": 1,
        "unmapped": 1,
    }
    assert summary["category_proportions"] == {
        "natural_vegetation": 0.4,
        "other_natural_cover": 0.2,
        "anthropic_cover": 0.2,
        "uncertain_or_mixed": 0.2,
    }


def test_mapbiomas_uses_all_touched_while_detector_grid_uses_pixel_centers(
    tmp_path: Path,
):
    raster_path = tmp_path / "categorical.tif"
    _write_uint8_raster(
        raster_path,
        np.asarray([[3, 4], [15, 25]], dtype=np.uint8),
        from_origin(0.0, 2.0, 1.0, 1.0),
    )
    sliver = {
        "type": "Polygon",
        "coordinates": [
            [
                [0.01, 1.90],
                [0.10, 1.90],
                [0.10, 1.99],
                [0.01, 1.99],
                [0.01, 1.90],
            ]
        ],
    }

    _, all_touched, _ = _read_polygon_values(
        raster_path, sliver, all_touched=True
    )
    _, pixel_centers, _ = _read_polygon_values(
        raster_path, sliver, all_touched=False
    )

    assert int(all_touched.sum()) == 1
    assert int(pixel_centers.sum()) == 0


def test_mapbiomas_native_summaries_nearest_agreement_and_both_thresholds(
    tmp_path: Path,
):
    primary_path = tmp_path / "primary.tif"
    secondary_path = tmp_path / "secondary.tif"
    primary = np.asarray(
        [[3, 3, 0], [4, 25, 15], [23, 255, 3]], dtype=np.uint8
    )
    _write_uint8_raster(primary_path, primary, from_origin(0.0, 0.03, 0.01, 0.01))
    _write_uint8_raster(
        secondary_path,
        np.asarray([[3]], dtype=np.uint8),
        from_origin(0.0, 0.03, 0.03, 0.03),
    )
    crop_paths = {COL3_KEY: primary_path, COL10_KEY: secondary_path}
    crop_bindings = {
        COL3_KEY: {"crop_id": "primary-test", "artifact": {"sha256": "a" * 64}},
        COL10_KEY: {"crop_id": "secondary-test", "artifact": {"sha256": "b" * 64}},
    }

    result = _mapbiomas_context(
        _full_raster_geometry(), _registry(), crop_paths, crop_bindings
    )

    primary_summary = result["collections"][COL3_KEY]
    secondary_summary = result["collections"][COL10_KEY]
    assert primary_summary["pixel_count"] == 9
    assert primary_summary["status"] == "partial"
    assert primary_summary["nodata_pixel_count"] == 1
    assert primary_summary["unmapped_pixel_count"] == 1
    assert primary_summary["category_proportions"]["natural_vegetation"] == (
        pytest.approx(4 / 7)
    )
    assert secondary_summary["class_histogram"] == {"3": 1}

    agreement = result["agreement"]
    assert agreement["resampling"] == "nearest_only"
    assert agreement["status"] == "partial"
    assert agreement["comparison_pixel_count"] == 9
    assert agreement["joint_valid_raw_count"] == 8
    assert agreement["exact_agreement_count"] == 3
    assert agreement["exact_disagreement_count"] == 5
    assert agreement["joint_mapped_count"] == 7
    assert agreement["category_agreement_count"] == 4
    assert agreement["category_disagreement_count"] == 3
    assert agreement["interpretation"] == "context_not_scientific_truth"

    alternatives = result["strong_subset_alternatives"]
    assert list(alternatives) == list(MAPBIOMAS_CANDIDATES)
    assert alternatives[MAPBIOMAS_CANDIDATES[0]]["membership"] == "included"
    assert alternatives[MAPBIOMAS_CANDIDATES[1]]["membership"] == "excluded"
    assert all(value["raw_detection_retained"] for value in alternatives.values())
    assert all(not value["selected_or_activated"] for value in alternatives.values())


def test_spectral_polygon_indices_are_center_within_on_the_accepted_20m_grid():
    context_window = {
        "transform": [20.0, 0.0, 500000.0, 0.0, -20.0, 9200000.0],
        "height": 2,
        "width": 2,
    }
    first_cell_utm = {
        "type": "Polygon",
        "coordinates": [
            [
                [500000.0, 9199980.0],
                [500020.0, 9199980.0],
                [500020.0, 9200000.0],
                [500000.0, 9200000.0],
                [500000.0, 9199980.0],
            ]
        ],
    }
    geometry = transform_geom("EPSG:32724", "EPSG:4326", first_cell_utm)

    indices = _polygon_indices_on_context_grid(geometry, context_window)

    assert indices.tolist() == [[0, 0]]


def _synthetic_phase2a4_stratum_input(root: Path) -> tuple[dict, np.ndarray]:
    values = np.asarray(
        [
            [[0.1, 0.1], [0.1, 0.1]],
            [[0.1, 0.2], [0.1, 0.1]],
            [[0.5, 0.2], [0.5, 0.5]],
            [[0.3, 0.4], [0.4, 0.4]],
            [[0.1, 0.8], [0.1, 0.1]],
            [[0.3, 0.2], [0.2, 0.2]],
        ],
        dtype=np.float32,
    )
    valid = np.asarray([[1, 1], [1, 0]], dtype=np.uint8)
    values_path = root / "inputs/values.npy"
    valid_path = root / "inputs/valid-mask.npy"
    _write_npy(values_path, values)
    _write_npy(valid_path, valid)
    case = {
        "processing_audit": {
            "compositions": {
                "cloud-a": {
                    "composition-a": {
                        "status": "available",
                        "reason": None,
                        "artifacts": {
                            "values": _artifact(values_path, root),
                            "valid_mask": _artifact(valid_path, root),
                        },
                    }
                }
            }
        },
        "factorial_cells": [
            {
                "cell_id": "cell-disabled",
                "availability": "available",
                "candidates": {
                    "cloud_mask": "cloud-a",
                    "daily_composition": "composition-a",
                    "drought_adjustment": "drought-disabled-v1",
                },
            },
            {
                "cell_id": "cell-chirps",
                "availability": "available",
                "candidates": {
                    "cloud_mask": "cloud-a",
                    "daily_composition": "composition-a",
                    "drought_adjustment": (
                        "chirps-v2-spi3-season-matched-1981-2025-v1"
                    ),
                },
            },
        ],
    }
    return case, np.full((2, 2), 0.5, dtype=np.float32)


def test_spectral_stratum_retains_measurements_arrays_and_not_assessed(
    tmp_path: Path,
):
    evidence_root = tmp_path / "p2a4"
    output_root = tmp_path / "p2a5"
    case, baseline = _synthetic_phase2a4_stratum_input(evidence_root)
    indices = np.asarray([[0, 0], [0, 1], [1, 0], [1, 1]], dtype=np.int32)

    result = _spectral_stratum(
        evidence_root=evidence_root,
        output_root=output_root,
        sample_id="synthetic-sample",
        polygon_indices=indices,
        baseline_nbr=baseline,
        p2a4_case=case,
        cloud_id="cloud-a",
        composition_id="composition-a",
    )

    assert result["status"] == "partial"
    assert "3 of 4 polygon pixels" in result["reason"]
    assert result["pixel_count"] == 4
    assert result["valid_pixel_count"] == 3
    assert result["not_assessed_pixel_count"] == 1
    assert [
        cell["drought_adjustment_candidate_id"]
        for cell in result["phase2a4_cells"]
    ] == [
        "chirps-v2-spi3-season-matched-1981-2025-v1",
        "drought-disabled-v1",
    ]
    assert result["class_counts"] == {
        "fire_like": 1,
        "exposed_soil_or_clearing_like": 1,
        "mixed_or_uncertain": 1,
        "not_assessed": 1,
    }
    assert result["proportions"] == {
        "fire_like": pytest.approx(1 / 3),
        "exposed_soil_or_clearing_like": pytest.approx(1 / 3),
        "mixed_or_uncertain": pytest.approx(1 / 3),
        "not_assessed": 0.25,
    }
    assert set(result["arrays"]) == {
        "dnbr",
        "post_nbr",
        "bsi",
        "valid",
        "not_assessed",
        "signature_codes",
    }
    for record in result["arrays"].values():
        _verify_record(output_root / record["path"], record)
    codes = np.load(
        output_root / result["arrays"]["signature_codes"]["path"],
        allow_pickle=False,
    )
    assert codes.tolist() == [1, 2, 3, 0]
    assert result["medians"]["dnbr"] == pytest.approx(1 / 6, rel=1e-5)


def test_signature_aggregation_evaluates_both_fixed_candidates_without_selection():
    strata = [
        {
            "stratum_id": f"stratum-{index}",
            "status": "available",
            "class_counts": {
                "fire_like": 55,
                "exposed_soil_or_clearing_like": 35,
                "mixed_or_uncertain": 10,
                "not_assessed": 0,
            },
            "proportions": {
                "fire_like": 0.55,
                "exposed_soil_or_clearing_like": 0.35,
                "mixed_or_uncertain": 0.10,
                "not_assessed": 0.0,
            },
        }
        for index in range(4)
    ]

    outcomes = _normalize_aggregation(strata, _registry())

    assert list(outcomes) == list(SIGNATURE_CANDIDATES)
    assert outcomes[SIGNATURE_CANDIDATES[0]]["label"] == "mixed_or_uncertain"
    assert outcomes[SIGNATURE_CANDIDATES[1]]["label"] == "fire_like"
    assert all(value["status"] == "available" for value in outcomes.values())
    assert all(not value["selected_or_activated"] for value in outcomes.values())
    assert all(not value["causal_inference"] for value in outcomes.values())


class _RecordingDraw:
    def __init__(self, captured: list[str]):
        self.captured = captured

    def text(self, _position, value, **_kwargs):
        self.captured.append(str(value))

    def rectangle(self, *_args, **_kwargs):
        return None


def test_panel_payload_text_is_blind_to_true_candidate_and_method_identities(
    monkeypatch,
):
    captured: list[str] = []

    def fake_canvas(subtitle: str):
        captured.append(subtitle)
        return object(), _RecordingDraw(captured)

    monkeypatch.setattr(
        "src.validation.phase2a5_evidence._panel_canvas", fake_canvas
    )
    monkeypatch.setattr(
        "src.validation.phase2a5_evidence._png_bytes", lambda _image: b"png"
    )
    mapbiomas = {
        "collections": {
            COL3_KEY: {
                "category_proportions": {
                    "natural_vegetation": 0.61,
                    "other_natural_cover": 0.12,
                    "anthropic_cover": 0.20,
                    "uncertain_or_mixed": 0.07,
                }
            }
        },
        "agreement": {"category_agreement_fraction": 0.73},
        "strong_subset_alternatives": {
            candidate_id: {"membership": "included"}
            for candidate_id in MAPBIOMAS_CANDIDATES
        },
    }
    spectral = {
        "aggregation_candidates": {
            SIGNATURE_CANDIDATES[0]: {
                "label": "fire_like",
                "available_stratum_count": 4,
                "median_assessed_proportions": {
                    "fire_like": 0.61,
                    "exposed_soil_or_clearing_like": 0.22,
                    "mixed_or_uncertain": 0.17,
                },
            },
            SIGNATURE_CANDIDATES[1]: {
                "label": "exposed_soil_or_clearing_like",
                "available_stratum_count": 4,
                "median_assessed_proportions": {
                    "fire_like": 0.61,
                    "exposed_soil_or_clearing_like": 0.22,
                    "mixed_or_uncertain": 0.17,
                },
            },
        }
    }

    for candidate_id in MAPBIOMAS_CANDIDATES:
        assert _map_panel_bytes(mapbiomas, candidate_id) == b"png"
    for candidate_id in SIGNATURE_CANDIDATES:
        assert _signature_panel_bytes(spectral, candidate_id) == b"png"

    rendered = "\n".join(captured).lower()
    for forbidden in (
        *MAPBIOMAS_CANDIDATES,
        *SIGNATURE_CANDIDATES,
        "0.50",
        "0.75",
        "0.60",
        "0.15",
        "scl-explicit-clear-shadow-v1",
        "coverage-ranked-first-valid-v1",
        "fire_like",
        "fire-like",
        "clearing-like",
    ):
        assert forbidden.lower() not in rendered
    assert "context only; no cause inferred" in rendered


def test_unreviewable_candidates_keep_exact_families_and_null_panel_artifacts(
    tmp_path: Path,
):
    mapbiomas = {
        "strong_subset_alternatives": {
            candidate_id: {
                "membership": "not_assessed",
                "reason": "no mapped valid Collection 3 pixels",
            }
            for candidate_id in MAPBIOMAS_CANDIDATES
        }
    }
    spectral = {
        "aggregation_candidates": {
            candidate_id: {
                "status": "unreviewable",
                "reason": "no assessed measurements",
            }
            for candidate_id in SIGNATURE_CANDIDATES
        }
    }

    panels = _candidate_panels(
        output_root=tmp_path,
        sample_id="synthetic-sample",
        mapbiomas=mapbiomas,
        spectral=spectral,
    )

    assert list(panels) == ["mapbiomas", "contextual_signature"]
    assert list(panels["mapbiomas"]) == list(MAPBIOMAS_CANDIDATES)
    assert list(panels["contextual_signature"]) == list(SIGNATURE_CANDIDATES)
    for family in panels.values():
        for record in family.values():
            assert record["status"] == "unreviewable"
            assert record["reason"]
            assert record["path"] is None
            assert record["bytes"] is None
            assert record["sha256"] is None
            assert record["media_type"] is None
    assert not list(tmp_path.rglob("*.png"))


def test_source_binding_is_exactly_the_canonical_available_phase2a3_fields():
    p2a3_root = REPOSITORY_ROOT / "data/validation/phase2a3-pilot-v1"
    sample = json.loads((p2a3_root / "sampling/sample.geojson").read_text())
    sample_id = sample["features"][0]["properties"]["sample_id"]
    coordinator_case = json.loads(
        (p2a3_root / "coordinator/cases" / f"{sample_id}.json").read_text()
    )

    source = coordinator_case["source"]
    binding = _source_binding(source)

    assert binding == {
        "source_artifact_sha256": source["source_artifact_sha256"],
        "source_feature_index": source["source_feature_index"],
        "geometry_sha256": source["geometry_sha256"],
        "source_record_id": source["source_record_id"],
    }
    assert _canonical_sha256(binding) == _canonical_sha256(
        {
            "geometry_sha256": source["geometry_sha256"],
            "source_artifact_sha256": source["source_artifact_sha256"],
            "source_feature_index": source["source_feature_index"],
            "source_record_id": source["source_record_id"],
        }
    )


def test_frozen_case_population_ids_geometries_and_source_order_are_unchanged():
    p2a3_root = REPOSITORY_ROOT / "data/validation/phase2a3-pilot-v1"
    p2a4_root = REPOSITORY_ROOT / "data/validation/phase2a4-candidate-evidence-v1"
    p2a4_manifest = json.loads((p2a4_root / "manifest.json").read_text())
    source_sample = json.loads((p2a3_root / "sampling/sample.geojson").read_text())

    features, crosswalk, p2a4_cases = _input_case_maps(p2a3_root, p2a4_manifest)

    expected_ids = [feature["properties"]["sample_id"] for feature in source_sample["features"]]
    actual_ids = [feature["properties"]["sample_id"] for feature in features]
    assert actual_ids == expected_ids
    assert [feature["geometry"] for feature in features] == [
        feature["geometry"] for feature in source_sample["features"]
    ]
    assert len(features) == len(crosswalk) == len(p2a4_cases) == 60


def test_deterministic_arrays_checksums_and_inventory_reject_tampering(
    tmp_path: Path,
):
    first = tmp_path / "first.npy"
    second = tmp_path / "second.npy"
    values = np.asarray([np.nan, -0.0, 0.125, 0.3], dtype=np.float32)
    _write_npy(first, values)
    _write_npy(second, values.copy())
    assert first.read_bytes() == second.read_bytes()

    record = _artifact(first, tmp_path)
    _verify_record(first, record)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    _write_checksum_inventory(tmp_path)
    _verify_checksum_inventory(tmp_path)

    first.write_bytes(first.read_bytes() + b"tamper")
    with pytest.raises(Phase2A5EvidenceError, match="checksum inventory mismatch"):
        _verify_checksum_inventory(tmp_path)
    with pytest.raises(Phase2A5EvidenceError, match="byte mismatch"):
        _verify_record(first, record)


def _dummy_build_config(output_dir: Path) -> Phase2A5EvidenceConfig:
    return Phase2A5EvidenceConfig(
        output_dir=output_dir,
        parent_phase2a3_dir=output_dir.parent / "phase2a3-unused",
        parent_phase2a4_dir=output_dir.parent / "phase2a4-unused",
        candidate_registry_path=output_dir.parent / "registry-unused.json",
        context_artifact_dir=output_dir.parent / "context-unused",
        generated_at="2026-08-09T12:00:00-03:00",
        repository_root=REPOSITORY_ROOT,
    )


def test_atomic_builder_refuses_to_replace_an_existing_audit_artifact(
    tmp_path: Path,
):
    target = tmp_path / "evidence"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(Phase2A5EvidenceError, match="refusing to replace"):
        build_phase2a5_evidence(_dummy_build_config(target))

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not list(tmp_path.glob(".evidence.staging-*"))
    assert not (tmp_path / ".evidence.lock").exists()


def test_atomic_builder_refuses_a_broken_output_symlink(tmp_path: Path):
    target = tmp_path / "evidence"
    missing_target = tmp_path / "missing-evidence"
    target.symlink_to(missing_target, target_is_directory=True)

    with pytest.raises(Phase2A5EvidenceError, match="refusing to replace"):
        build_phase2a5_evidence(_dummy_build_config(target))

    assert target.is_symlink()
    assert target.readlink() == missing_target
    assert not list(tmp_path.glob(".evidence.staging-*"))
    assert not (tmp_path / ".evidence.lock").exists()


def test_atomic_builder_cleans_staging_and_leaves_no_target_on_failure(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / "evidence"

    def fail_after_partial_write(config):
        partial = Path(config.output_dir)
        partial.mkdir(parents=True)
        (partial / "partial.json").write_text("{}\n", encoding="utf-8")
        raise Phase2A5EvidenceError("synthetic assembly failure")

    monkeypatch.setattr(
        "src.validation.phase2a5_evidence._build_phase2a5_evidence_in_place",
        fail_after_partial_write,
    )

    with pytest.raises(Phase2A5EvidenceError, match="synthetic assembly failure"):
        build_phase2a5_evidence(_dummy_build_config(target))

    assert not target.exists()
    assert not list(tmp_path.glob(".evidence.staging-*"))
    assert not (tmp_path / ".evidence.lock").exists()


def test_atomic_builder_renames_only_a_validated_staging_artifact(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / "evidence"
    expected = {"evidence_id": "synthetic-validated-evidence"}

    def succeed(config):
        staging = Path(config.output_dir)
        staging.mkdir(parents=True)
        (staging / "manifest.json").write_text("{}\n", encoding="utf-8")
        return expected

    monkeypatch.setattr(
        "src.validation.phase2a5_evidence._build_phase2a5_evidence_in_place",
        succeed,
    )

    assert build_phase2a5_evidence(_dummy_build_config(target)) == expected
    assert (target / "manifest.json").read_text(encoding="utf-8") == "{}\n"
    assert not list(tmp_path.glob(".evidence.staging-*"))
    assert not (tmp_path / ".evidence.lock").exists()


def test_evidence_build_lock_fails_closed_and_releases(tmp_path: Path):
    target = tmp_path / "evidence"
    lock = evidence._acquire_build_lock(target)
    try:
        with pytest.raises(Phase2A5EvidenceError, match="build lock already exists"):
            build_phase2a5_evidence(_dummy_build_config(target))
        assert lock.is_file()
        assert not target.exists()
        assert not list(tmp_path.glob(".evidence.staging-*"))
    finally:
        evidence._release_build_lock(lock)
    assert not lock.exists()


def test_atomic_builder_preserves_a_target_injected_during_assembly(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / "evidence"

    def inject_competing_target(config):
        staging = Path(config.output_dir)
        staging.mkdir(parents=True)
        (staging / "manifest.json").write_text("{}\n", encoding="utf-8")
        target.mkdir()
        (target / "keep.txt").write_text("preserve", encoding="utf-8")
        return {"evidence_id": "synthetic-validated-evidence"}

    monkeypatch.setattr(
        "src.validation.phase2a5_evidence._build_phase2a5_evidence_in_place",
        inject_competing_target,
    )

    with pytest.raises(Phase2A5EvidenceError, match="appeared during assembly"):
        build_phase2a5_evidence(_dummy_build_config(target))

    assert (target / "keep.txt").read_text(encoding="utf-8") == "preserve"
    assert not list(tmp_path.glob(".evidence.staging-*"))
    assert not (tmp_path / ".evidence.lock").exists()


def test_atomic_builder_preserves_a_broken_symlink_injected_during_assembly(
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / "evidence"
    missing_target = tmp_path / "missing-evidence"

    def inject_competing_target(config):
        staging = Path(config.output_dir)
        staging.mkdir(parents=True)
        (staging / "manifest.json").write_text("{}\n", encoding="utf-8")
        target.symlink_to(missing_target, target_is_directory=True)
        return {"evidence_id": "synthetic-validated-evidence"}

    monkeypatch.setattr(
        "src.validation.phase2a5_evidence._build_phase2a5_evidence_in_place",
        inject_competing_target,
    )

    with pytest.raises(Phase2A5EvidenceError, match="appeared during assembly"):
        build_phase2a5_evidence(_dummy_build_config(target))

    assert target.is_symlink()
    assert target.readlink() == missing_target
    assert not list(tmp_path.glob(".evidence.staging-*"))
    assert not (tmp_path / ".evidence.lock").exists()
