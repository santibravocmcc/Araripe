"""Deterministic Package 2A.5 source, crop, context, and tamper tests."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import rasterio
from click.testing import CliRunner
from jsonschema import Draft202012Validator, FormatChecker
from rasterio.transform import from_origin
from rasterio.windows import Window, from_bounds

import src.validation.phase2a5_context as context
from scripts.build_phase2a5_context import main as build_context_cli
from src.validation.phase2a5_context import (
    COL10_KEY,
    COL3_KEY,
    Phase2A5ContextError,
    aggregate_contextual_signature_candidates,
    annotate_threshold_candidates_preserving_raw,
    calculate_agreement_disagreement,
    classify_contextual_signature_pixels,
    classify_mapbiomas_codes,
    contextual_signature_proportions,
    load_context_registry,
    strong_subset_membership,
    summarize_polygon_context,
)


ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "config/phase2a5_context_candidates_v1.json"
REGISTRY_SCHEMA_PATH = (
    ROOT
    / "docs/contracts/phase2a/schemas/phase2a5-context-candidate-registry-v1.schema.json"
)
MANIFEST_SCHEMA_PATH = (
    ROOT / "docs/contracts/phase2a/schemas/phase2a5-context-manifest-v1.schema.json"
)
@pytest.fixture(scope="module")
def registry() -> dict:
    return load_context_registry(REGISTRY_PATH, schema_path=REGISTRY_SCHEMA_PATH)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_schemas_meta_valid_and_registry_is_fixed(registry):
    for path in (REGISTRY_SCHEMA_PATH, MANIFEST_SCHEMA_PATH):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
    schema = json.loads(REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(registry)
    )
    assert errors == []
    assert registry["monitoring_extent"]["source_aoi_sha256"] == (
        "2bff31afa6cb74630a437b4fffb96ad88f7f873a3aa1461f337c66f61c209881"
    )
    assert registry["contextual_signature"]["polygon_pixel_rule"] == (
        "detector_grid_pixel_center_within_polygon-v1"
    )
    assert registry["contextual_signature"]["all_touched"] is False
    assert context._sha256_file(REGISTRY_PATH) == context.EXPECTED_REGISTRY_SHA256


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("sources", COL3_KEY, "sha256"), "0" * 64),
        (("monitoring_extent", "source_aoi_sha256"), "0" * 64),
        (("grid_reconciliation", "secondary_origin_offset_primary_pixels"), [7799, 24174]),
        (("strong_subset", "candidates", 0, "threshold"), 0.49),
    ],
)
def test_registry_tamper_is_rejected(tmp_path, registry, path, replacement):
    changed = copy.deepcopy(registry)
    cursor = changed
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = replacement
    candidate = tmp_path / "registry.json"
    _write_json(candidate, changed)
    with pytest.raises(Phase2A5ContextError):
        load_context_registry(candidate, schema_path=REGISTRY_SCHEMA_PATH)


def test_complete_class_mapping_and_explicit_unknown(registry):
    col3_codes = np.array([0, 3, 23, 9, 25, 33, 250], dtype=np.uint8)
    assert classify_mapbiomas_codes(col3_codes, COL3_KEY, registry).tolist() == [
        "nodata",
        "natural_vegetation",
        "other_natural_cover",
        "anthropic_cover",
        "uncertain_or_mixed",
        "uncertain_or_mixed",
        "unmapped",
    ]
    col10_codes = np.array([25, 33], dtype=np.uint8)
    assert classify_mapbiomas_codes(col10_codes, COL10_KEY, registry).tolist() == [
        "uncertain_or_mixed",
        "other_natural_cover",
    ]


def test_polygon_nodata_coverage_and_proportions(registry):
    summary = summarize_polygon_context(
        np.array([3, 23, 9, 25, 33, 0, 250], dtype=np.uint8),
        COL3_KEY,
        registry,
    )
    assert summary["class_histogram"] == {
        "0": 1,
        "3": 1,
        "9": 1,
        "23": 1,
        "25": 1,
        "33": 1,
        "250": 1,
    }
    assert summary["total_pixel_count"] == 7
    assert summary["valid_pixel_count"] == 6
    assert summary["mapped_valid_pixel_count"] == 5
    assert summary["nodata_pixel_count"] == 1
    assert summary["unmapped_pixel_count"] == 1
    assert summary["valid_coverage_fraction"] == pytest.approx(6 / 7)
    assert summary["category_proportions"] == {
        "natural_vegetation": pytest.approx(0.2),
        "other_natural_cover": pytest.approx(0.2),
        "anthropic_cover": pytest.approx(0.2),
        "uncertain_or_mixed": pytest.approx(0.4),
    }


def test_polygon_mask_shape_and_empty_denominator(registry):
    empty = summarize_polygon_context(
        np.array([0, 250], dtype=np.uint8), COL3_KEY, registry
    )
    assert empty["mapped_valid_pixel_count"] == 0
    assert all(value is None for value in empty["category_proportions"].values())
    with pytest.raises(Phase2A5ContextError, match="shapes differ"):
        summarize_polygon_context(
            np.ones((2, 2), dtype=np.uint8),
            COL3_KEY,
            registry,
            valid_mask=np.ones((2,), dtype=bool),
        )


@pytest.mark.parametrize(
    ("fraction", "current", "strict"),
    [
        (None, "not_assessed", "not_assessed"),
        (0.499999, "excluded", "excluded"),
        (0.5, "included", "excluded"),
        (0.749999, "included", "excluded"),
        (0.75, "included", "included"),
        (1.0, "included", "included"),
    ],
)
def test_strong_subset_fixed_greater_equal_boundaries(
    registry, fraction, current, strict
):
    result = strong_subset_membership(fraction, registry)
    assert result["natural-vegetation-share-0.50-v1"]["membership"] == current
    assert result["natural-vegetation-share-0.75-v1"]["membership"] == strict
    assert all(item["selected_or_activated"] is False for item in result.values())
    assert all(item["raw_detection_retained"] is True for item in result.values())


def test_raw_detection_sequence_identity_and_geometry_are_preserved(registry):
    original = [
        {"id": "raw-a", "geometry": {"type": "Point", "coordinates": [-39.5, -7.4]}},
        {"id": "raw-b", "geometry": {"type": "Point", "coordinates": [-39.4, -7.3]}},
        {"id": "raw-c", "geometry": None},
    ]
    snapshot = copy.deepcopy(original)
    annotated = annotate_threshold_candidates_preserving_raw(
        original, [0.5, None, 0.8], registry
    )
    assert original == snapshot
    assert [record["id"] for record in annotated] == ["raw-a", "raw-b", "raw-c"]
    assert [record["geometry"] for record in annotated] == [
        record["geometry"] for record in snapshot
    ]
    assert len(annotated) == len(original)


def test_agreement_uses_joint_valid_and_joint_mapped_denominators(registry):
    primary = np.array([3, 4, 25, 33, 0, 250], dtype=np.uint8)
    secondary = np.array([3, 15, 25, 33, 3, 3], dtype=np.uint8)
    result = calculate_agreement_disagreement(
        primary, secondary, registry, secondary_is_aligned=True
    )
    assert result["joint_valid_raw_count"] == 5
    assert result["exact_agreement_count"] == 3
    assert result["exact_disagreement_count"] == 2
    assert result["joint_mapped_count"] == 4
    assert result["category_agreement_count"] == 2
    assert result["category_disagreement_count"] == 2
    assert result["category_agreement_fraction"] == 0.5
    assert result["interpretation"] == "context_not_scientific_truth"
    with pytest.raises(Phase2A5ContextError, match="explicit nearest-aligned"):
        calculate_agreement_disagreement(primary, secondary, registry)


def test_contextual_signature_pixel_rule_and_measurement_boundaries():
    labels = classify_contextual_signature_pixels(
        np.array([0.270001, 0.27, 0.06, 0.11, 0.05, np.nan]),
        np.array([0.09, 0.09, 0.2, 0.2, 0.2, 0.0]),
        np.array([0.0, 0.0, 0.100001, 0.0, 0.2, 0.0]),
    )
    assert labels.tolist() == [
        "fire_like",
        "mixed_or_uncertain",
        "exposed_soil_or_clearing_like",
        "mixed_or_uncertain",
        "not_assessed",
        "not_assessed",
    ]
    summary = contextual_signature_proportions(labels)
    assert summary["assessed_pixel_count"] == 4
    assert summary["total_pixel_count"] == 6
    assert summary["counts"]["not_assessed"] == 2
    assert summary["proportions"]["fire_like"] == 0.25
    assert summary["proportions"]["exposed_soil_or_clearing_like"] == 0.25
    assert summary["proportions"]["mixed_or_uncertain"] == 0.5
    assert summary["proportions"]["not_assessed"] == pytest.approx(1 / 3)


def _stratum(fire: int, exposed: int, mixed: int, missing: int = 0, status="available"):
    labels = np.array(
        ["fire_like"] * fire
        + ["exposed_soil_or_clearing_like"] * exposed
        + ["mixed_or_uncertain"] * mixed
        + ["not_assessed"] * missing
    )
    return {"status": status, **contextual_signature_proportions(labels)}


def test_contextual_signature_candidates_are_fixed_unselected_and_noncausal(registry):
    strata = [_stratum(7, 2, 1), _stratum(8, 1, 1), _stratum(6, 2, 2), _stratum(7, 1, 2)]
    result = aggregate_contextual_signature_candidates(strata, registry)
    for candidate_id in (
        "dominant-assessed-share-0.60-v1",
        "plurality-assessed-margin-0.15-v1",
    ):
        assert result[candidate_id]["status"] == "available"
        assert result[candidate_id]["label"] == "fire_like"
        assert result[candidate_id]["available_stratum_count"] == 4
        assert result[candidate_id]["selected_or_activated"] is False
        assert result[candidate_id]["causal_inference"] is False
    tie = aggregate_contextual_signature_candidates(
        [_stratum(5, 5, 0)] * 4, registry
    )
    assert all(item["label"] == "mixed_or_uncertain" for item in tie.values())
    missing = aggregate_contextual_signature_candidates([], registry)
    assert all(item["label"] == "not_assessed" for item in missing.values())


def test_native_grid_crop_is_deterministic_categorical_and_non_mutating(tmp_path):
    source_path = tmp_path / "source.tif"
    values = (np.arange(16 * 16, dtype=np.uint16).reshape(16, 16) % 6).astype(np.uint8)
    transform = from_origin(-41.0, -6.0, 0.01, 0.01)
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        nodata=0,
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="LZW",
        predictor=2,
    ) as output:
        output.write(values, 1)
        output.update_tags(AREA_OR_POINT="Area")
    source_sha = context._sha256_file(source_path)
    window = Window(2, 3, 8, 6)
    expected = values[3:9, 2:10]
    with rasterio.open(source_path) as source:
        crop_transform = source.window_transform(window)
        crop_bounds = list(rasterio.transform.array_bounds(6, 8, crop_transform))
        config = {
            "transform": list(crop_transform)[:6],
            "bounds": crop_bounds,
            "block_shape": [16, 16],
            "output_nodata": 0,
        }
        first_values, first = context._write_crop(
            source, window, tmp_path / "first.tif", config
        )
        second_values, second = context._write_crop(
            source, window, tmp_path / "second.tif", config
        )
    assert np.array_equal(first_values, expected)
    assert np.array_equal(second_values, expected)
    assert first == second
    assert context._sha256_file(tmp_path / "first.tif") == context._sha256_file(
        tmp_path / "second.tif"
    )
    assert context._sha256_file(source_path) == source_sha
    assert first["tiled"] is True
    assert first["compression"] == "LZW"
    assert first["overviews"] == []


def test_outer_window_must_cover_the_exact_extent(tmp_path, registry):
    path = tmp_path / "source.tif"
    transform = from_origin(-41.0, -6.9, 0.1, 0.1)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=32,
        height=32,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
    ) as output:
        output.write(np.ones((32, 32), dtype=np.uint8), 1)
    changed = copy.deepcopy(registry)
    with rasterio.open(path) as source:
        fractional = from_bounds(
            *registry["monitoring_extent"]["bounds"], transform=source.transform
        )
        outer = [
            int(np.floor(fractional.col_off)),
            int(np.floor(fractional.row_off)),
            int(np.ceil(fractional.col_off + fractional.width))
            - int(np.floor(fractional.col_off)),
            int(np.ceil(fractional.row_off + fractional.height))
            - int(np.floor(fractional.row_off)),
        ]
        crop = changed["crop_policy"]["crops"][COL3_KEY]
        crop["fractional_source_window"] = [
            fractional.col_off,
            fractional.row_off,
            fractional.width,
            fractional.height,
        ]
        crop["integer_source_window"] = outer
        actual = context._window_from_registry(source, changed, COL3_KEY)
        assert [actual.col_off, actual.row_off, actual.width, actual.height] == outer
        crop["integer_source_window"][2] -= 1
        with pytest.raises(Phase2A5ContextError, match="exact outer window"):
            context._window_from_registry(source, changed, COL3_KEY)


def test_checksum_inventory_detects_content_and_population_tamper(tmp_path):
    (tmp_path / "payload.txt").write_text("fixed\n", encoding="utf-8")
    context._write_checksums(tmp_path)
    context._verify_checksum_file(tmp_path)
    (tmp_path / "payload.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(Phase2A5ContextError, match="checksum mismatch"):
        context._verify_checksum_file(tmp_path)
    (tmp_path / "payload.txt").write_text("fixed\n", encoding="utf-8")
    context._write_checksums(tmp_path)
    (tmp_path / "unlisted.txt").write_text("extra\n", encoding="utf-8")
    with pytest.raises(Phase2A5ContextError, match="population mismatch"):
        context._verify_checksum_file(tmp_path)


def test_context_build_lock_fails_closed_and_releases(tmp_path: Path):
    target = tmp_path / "context"
    lock = context._acquire_build_lock(target)
    try:
        assert lock == tmp_path / ".context.lock"
        assert lock.is_file()
        with pytest.raises(Phase2A5ContextError, match="build lock already exists"):
            context._acquire_build_lock(target)
        assert lock.is_file()
    finally:
        context._release_build_lock(lock)
    assert not lock.exists()


def test_context_crop_publication_never_clobbers_an_appeared_file(tmp_path: Path):
    staged = tmp_path / "crop-staging.tif"
    destination = tmp_path / "regional-crop.tif"
    staged.write_bytes(b"validated-crop")
    destination.write_bytes(b"noncooperating-writer")

    with pytest.raises(Phase2A5ContextError, match="crop appeared during build"):
        context._publish_file_no_clobber(staged, destination)

    assert staged.read_bytes() == b"validated-crop"
    assert destination.read_bytes() == b"noncooperating-writer"


def test_context_crop_publication_refuses_a_broken_symlink(tmp_path: Path):
    staged = tmp_path / "crop-staging.tif"
    destination = tmp_path / "regional-crop.tif"
    missing_target = tmp_path / "missing-regional-crop.tif"
    staged.write_bytes(b"validated-crop")
    destination.symlink_to(missing_target)

    with pytest.raises(Phase2A5ContextError, match="crop appeared during build"):
        context._publish_file_no_clobber(staged, destination)

    assert staged.read_bytes() == b"validated-crop"
    assert destination.is_symlink()
    assert destination.readlink() == missing_target


def test_context_directory_publication_refuses_an_appeared_target(tmp_path: Path):
    staging = tmp_path / ".context-staging"
    target = tmp_path / "context"
    staging.mkdir()
    (staging / "manifest.json").write_text("{}\n", encoding="utf-8")
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(Phase2A5ContextError, match="artifact appeared during build"):
        context._publish_directory_no_clobber(staging, target)

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert (staging / "manifest.json").is_file()


def test_context_directory_publication_refuses_a_broken_symlink(tmp_path: Path):
    staging = tmp_path / ".context-staging"
    target = tmp_path / "context"
    missing_target = tmp_path / "missing-context"
    staging.mkdir()
    (staging / "manifest.json").write_text("{}\n", encoding="utf-8")
    target.symlink_to(missing_target, target_is_directory=True)

    with pytest.raises(Phase2A5ContextError, match="artifact appeared during build"):
        context._publish_directory_no_clobber(staging, target)

    assert target.is_symlink()
    assert target.readlink() == missing_target
    assert (staging / "manifest.json").is_file()


def test_context_cli_preserves_and_refuses_a_broken_output_symlink(tmp_path: Path):
    target = tmp_path / "context"
    missing_target = tmp_path / "missing-context"
    target.symlink_to(missing_target, target_is_directory=True)

    result = CliRunner().invoke(
        build_context_cli,
        [
            "--output-dir",
            str(target),
            "--generated-at",
            "2026-08-09T12:00:00-03:00",
        ],
    )

    assert result.exit_code == 1
    assert "context artifact already exists; refusing overwrite" in result.output
    assert target.is_symlink()
    assert target.readlink() == missing_target
    assert not (tmp_path / ".context.lock").exists()


def _synthetic_binding_artifact(root: Path, registry: dict) -> dict:
    """Create just enough resealable structure to exercise binding semantics."""
    embedded_registry = root / "inputs/context-candidate-registry.json"
    embedded_registry.parent.mkdir(parents=True)
    shutil.copyfile(REGISTRY_PATH, embedded_registry)
    embedded_registry_schema = root / "schemas" / REGISTRY_SCHEMA_PATH.name
    embedded_manifest_schema = root / "schemas" / MANIFEST_SCHEMA_PATH.name
    embedded_registry_schema.parent.mkdir(parents=True)
    shutil.copyfile(REGISTRY_SCHEMA_PATH, embedded_registry_schema)
    shutil.copyfile(MANIFEST_SCHEMA_PATH, embedded_manifest_schema)
    manifest = {
        "schema_bindings": {
            "registry": context._artifact(embedded_registry_schema, root),
            "manifest": context._artifact(embedded_manifest_schema, root),
        },
        "candidate_registry": {
            "registry_id": registry["registry_id"],
            "path": REGISTRY_PATH.relative_to(ROOT).as_posix(),
            "bytes": REGISTRY_PATH.stat().st_size,
            "sha256": context._sha256_file(REGISTRY_PATH),
            "embedded": context._artifact(embedded_registry, root),
        },
    }
    context._write_json(root / "manifest.json", manifest)
    context._write_checksums(root)
    return manifest


def _assert_binding_artifact_rejected(root: Path, message: str) -> None:
    """Show that checksums are valid before a semantic binding check rejects."""
    context._verify_checksum_file(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    registry = load_context_registry(REGISTRY_PATH, schema_path=REGISTRY_SCHEMA_PATH)
    (
        manifest_schema_path,
        registry_schema_path,
        _,
        _,
    ) = context._verify_embedded_context_schemas(root, ROOT)
    with pytest.raises(Phase2A5ContextError, match=message):
        context._verify_context_binding_descriptors(
            root=root,
            manifest=manifest,
            registry=registry,
            registry_path=REGISTRY_PATH,
            repository_root=ROOT,
            manifest_schema_path=manifest_schema_path,
            registry_schema_embedded_path=registry_schema_path,
        )


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("registry_schema_bytes", "embedded context registry schema differs"),
        ("manifest_schema_bytes", "embedded context manifest schema differs"),
        ("schema_binding_descriptor", "context schema bindings do not reconcile"),
        ("registry_binding_descriptor", "context registry binding does not reconcile"),
    ],
)
def test_resealed_schema_and_registry_binding_tamper_is_rejected(
    tmp_path: Path, registry: dict, tamper: str, message: str
):
    artifact = tmp_path / "context"
    manifest = _synthetic_binding_artifact(artifact, registry)

    if tamper == "registry_schema_bytes":
        schema = artifact / "schemas/phase2a5-context-candidate-registry-v1.schema.json"
        schema.write_bytes(schema.read_bytes() + b"\n")
        manifest["schema_bindings"]["registry"] = context._artifact(schema, artifact)
    elif tamper == "manifest_schema_bytes":
        schema = artifact / "schemas/phase2a5-context-manifest-v1.schema.json"
        schema.write_bytes(schema.read_bytes() + b"\n")
        manifest["schema_bindings"]["manifest"] = context._artifact(schema, artifact)
    elif tamper == "schema_binding_descriptor":
        manifest["schema_bindings"]["registry"]["sha256"] = "0" * 64
    elif tamper == "registry_binding_descriptor":
        manifest["candidate_registry"]["embedded"]["sha256"] = "0" * 64
    else:  # pragma: no cover - parametrization is the complete tamper inventory.
        raise AssertionError(tamper)

    context._write_json(artifact / "manifest.json", manifest)
    context._write_checksums(artifact)
    context._verify_checksum_file(artifact)
    if tamper.endswith("schema_bytes"):
        with pytest.raises(Phase2A5ContextError, match=message):
            context._verify_embedded_context_schemas(artifact, ROOT)
    else:
        _assert_binding_artifact_rejected(artifact, message)
