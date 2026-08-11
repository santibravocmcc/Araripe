"""Deterministic Phase 2A.5 contextual evidence for the frozen 60-case pilot.

This module is deliberately additive.  It reads the immutable Phase 2A.3 case
population, Phase 2A.4 candidate evidence, and the local Phase 2A.5 MapBiomas
context artifact.  It never selects a scientific policy, changes a raw
detection, or constructs population-wide outcomes from units whose geometry is
not present in the frozen sample.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import rasterio
from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image, ImageDraw, ImageFont
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from rasterio.warp import Resampling, reproject, transform_geom
from shapely.geometry import shape

from .phase2a5_context import (
    aggregate_contextual_signature_candidates,
    calculate_agreement_disagreement,
    classify_contextual_signature_pixels,
    classify_mapbiomas_codes,
    contextual_signature_proportions,
    load_context_registry,
    strong_subset_membership,
    summarize_polygon_context,
    validate_phase2a5_context_artifact,
)


SCHEMA_VERSION = "1.0.0"
ARTIFACT_TYPE = "phase2a5_context_evidence"
PIPELINE_VERSION = "phase2a5-context-evidence-v1"
MANIFEST_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a5-context-evidence-manifest-v1.schema.json"
)
CASE_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a5-context-evidence-case-v1.schema.json"
)
PHASE2A3_MANIFEST_SHA256 = "4b78167930fcb7a928b40d50ae1d54675e4cca47a10857bcbf28db803c18946b"
PHASE2A4_MANIFEST_SHA256 = "7684a4a9beadc7125d7103fb7a995d8c026add59bb7da0280e71c81e580a9d3e"
REGISTRY_SHA256 = "848216d90cd95c4886aaade2f5125237517f2dfb3f151dcbc36f349b6d9e3d88"
COL3_KEY = "mapbiomas_col3_beta_10m_2024"
COL10_KEY = "mapbiomas_col10_1_30m_2024"
MAPBIOMAS_CANDIDATES = (
    "natural-vegetation-share-0.50-v1",
    "natural-vegetation-share-0.75-v1",
)
SIGNATURE_CANDIDATES = (
    "dominant-assessed-share-0.60-v1",
    "plurality-assessed-margin-0.15-v1",
)
SIGNATURE_LABELS = (
    "fire_like",
    "exposed_soil_or_clearing_like",
    "mixed_or_uncertain",
    "not_assessed",
)
SIGNATURE_CODES = {label: index + 1 for index, label in enumerate(SIGNATURE_LABELS[:-1])}
SIGNATURE_CODES["not_assessed"] = 0
REFLECTANCE_BANDS = ("blue", "red", "nir", "nir08", "swir16", "swir22")
FORMULAE = {
    "post_nbr": "(nir08-swir22)/(nir08+swir22)",
    "bsi": "((swir16+red)-(nir+blue))/(swir16+red+nir+blue)",
    "dnbr": "accepted_baseline_nbr_mean-post_nbr",
}
BLANK_REVIEW = {
    "review_status": "blank",
    "qualified_label": None,
    "accepted_observation_id": None,
    "accepted_event_id": None,
    "selected_strong_subset_candidate_id": None,
    "selected_contextual_signature_candidate_id": None,
    "public_wording_approval": None,
    "acceptance_record_id": None,
}
CASE_CLAIMS = {
    "raw_detection_modified": False,
    "raw_detection_filtered": False,
    "case_replaced": False,
    "selected_or_activated": False,
    "qualified_human_label_present": False,
    "accepted_identity_present": False,
    "scientific_accuracy_claim": False,
    "omission_or_recall_claim": False,
    "causal_cause_inferred": False,
    "desired_total_tuning_performed": False,
    "phase2a4_method_selected_or_modified": False,
    "population_changed_or_reconstructed": False,
}
MANIFEST_CLAIMS = {
    "local_only": True,
    "provisional_audit_inputs_only": True,
    "raw_detection_modified": False,
    "raw_detection_filtered": False,
    "case_replaced": False,
    "qualified_human_label_present": False,
    "accepted_observation_or_event_identity_present": False,
    "scientific_accuracy_claim": False,
    "omission_or_recall_claim": False,
    "threshold_selected_or_activated": False,
    "contextual_signature_policy_selected_or_activated": False,
    "phase2a4_method_selected_or_modified": False,
    "causal_cause_inferred": False,
    "public_wording_approved": False,
    "phase2a_exit_gate_closed": False,
}
SOURCE_LIMITATIONS = (
    (
        "Phase 2A.3 locations, imagery, series, provisional strata, and blank reviews "
        "remain provisional audit inputs."
    ),
    (
        "Phase 2A.4 cloud-mask, daily-composition, and drought evidence remains "
        "provisional; all four cloud-by-composition strata are retained without selection."
    ),
    (
        "Geometry is absent for nonselected Phase 2A.3 population units, so no "
        "population-wide Phase 2A.5 outcome total is sourced or reconstructed."
    ),
    (
        "MapBiomas collection agreement and disagreement are context, not scientific "
        "truth or an omission/recall reference."
    ),
    (
        "Contextual spectral signatures are non-causal and do not infer fire, "
        "clearing mechanism, or any other cause."
    ),
)


class Phase2A5EvidenceError(ValueError):
    """Raised when provenance, semantics, or deterministic replay diverges."""


def _acquire_build_lock(target: Path) -> Path:
    """Reserve one sibling lock without replacing a stale or active lock."""
    lock = target.parent / f".{target.name}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise Phase2A5EvidenceError(
            f"exclusive build lock already exists; refusing to continue: {lock}"
        ) from exc
    except OSError as exc:
        raise Phase2A5EvidenceError(f"cannot create exclusive build lock {lock}: {exc}") from exc
    try:
        os.write(descriptor, f"target={target.name}\n".encode("utf-8"))
    except OSError as exc:
        try:
            lock.unlink()
        except OSError:
            pass
        raise Phase2A5EvidenceError(f"cannot initialize exclusive build lock {lock}: {exc}") from exc
    finally:
        os.close(descriptor)
    return lock


def _release_build_lock(lock: Path) -> None:
    try:
        lock.unlink()
    except FileNotFoundError:
        pass


def _publish_directory_no_clobber(staging: Path, target: Path) -> None:
    """Publish a staged directory under the cooperative exclusive build lock."""
    if os.path.lexists(target):
        raise Phase2A5EvidenceError(
            f"output appeared during assembly; refusing replacement: {target}"
        )
    try:
        staging.rename(target)
    except FileExistsError as exc:
        raise Phase2A5EvidenceError(
            f"output appeared during assembly; refusing replacement: {target}"
        ) from exc
    except OSError as exc:
        raise Phase2A5EvidenceError(f"cannot publish evidence artifact {target}: {exc}") from exc


@dataclass(frozen=True)
class Phase2A5EvidenceConfig:
    """Explicit inputs for the local/private contextual evidence artifact."""

    output_dir: Path
    parent_phase2a3_dir: Path
    parent_phase2a4_dir: Path
    candidate_registry_path: Path
    context_artifact_dir: Path
    generated_at: str
    repository_root: Path | None = None


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Phase2A5EvidenceError(f"value is not canonical JSON: {exc}") from exc


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase2A5EvidenceError(f"cannot read JSON {path}: {exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _normalized_storage_array(value: np.ndarray) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.hasobject:
        raise Phase2A5EvidenceError("object arrays are forbidden")
    if array.dtype.kind == "f":
        dtype = np.dtype(f"<f{array.dtype.itemsize}")
        result = np.asarray(array, dtype=dtype).copy(order="C")
        result[np.isnan(result)] = np.array(np.nan, dtype=dtype)
        return result
    if array.dtype.kind in "iu":
        return np.asarray(array, dtype=array.dtype.newbyteorder("<")).copy(order="C")
    if array.dtype.kind == "b":
        return np.asarray(array, dtype=np.uint8).copy(order="C")
    raise Phase2A5EvidenceError(f"unsupported deterministic array dtype: {array.dtype}")


def _write_npy(path: Path, value: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        np.save(stream, _normalized_storage_array(value), allow_pickle=False)


def _safe_relative(root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise Phase2A5EvidenceError(f"artifact escapes root {root}: {path}") from exc
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise Phase2A5EvidenceError(f"unsafe artifact path: {relative!r}")
    return relative


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Phase2A5EvidenceError(f"artifact missing: {path}")
    return {
        "path": _safe_relative(root, path),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _array_artifact(path: Path, root: Path, value: np.ndarray) -> dict[str, Any]:
    record = _artifact(path, root)
    stored = _normalized_storage_array(value)
    record.update(
        {
            "media_type": "application/x-npy",
            "dtype": stored.dtype.str,
            "shape": list(stored.shape),
        }
    )
    return record


def _external_artifact(path: Path, repository_root: Path) -> dict[str, Any]:
    record = _artifact(path, repository_root)
    record["scope"] = "repository_relative_external_input"
    return record


def _verify_record(path: Path, record: Mapping[str, Any]) -> None:
    if not path.is_file():
        raise Phase2A5EvidenceError(f"bound artifact is missing: {path}")
    if path.stat().st_size != record.get("bytes"):
        raise Phase2A5EvidenceError(f"bound artifact byte mismatch: {path}")
    if _sha256_file(path) != record.get("sha256"):
        raise Phase2A5EvidenceError(f"bound artifact checksum mismatch: {path}")


def _safe_artifact_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise Phase2A5EvidenceError("artifact path must be a non-empty string")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise Phase2A5EvidenceError(f"artifact path escapes root: {relative}") from exc
    return path


def _validate_schema(value: Any, schema: Mapping[str, Any], label: str) -> None:
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        detail = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors[:12]
        )
        raise Phase2A5EvidenceError(f"{label} schema validation failed: {detail}")


def _parse_timestamp(value: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise Phase2A5EvidenceError("generated_at must be timezone-aware RFC3339") from exc
    if parsed.tzinfo is None:
        raise Phase2A5EvidenceError("generated_at must include a timezone")
    return value


def _distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unavailable"


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pillow": _distribution_version("Pillow"),
        "pyproj": _distribution_version("pyproj"),
        "rasterio": rasterio.__version__,
        "gdal": str(rasterio.__gdal_version__),
        "shapely": _distribution_version("shapely"),
        "jsonschema": _distribution_version("jsonschema"),
    }


def _generator_source_inventory(repository_root: Path) -> list[dict[str, Any]]:
    relative_paths = (
        "src/validation/phase2a5_context.py",
        "src/validation/phase2a5_evidence.py",
        "scripts/build_phase2a5_evidence.py",
        "scripts/validate_phase2a5_evidence.py",
        "config/phase2a5_context_candidates_v1.json",
        "docs/contracts/phase2a/schemas/phase2a5-context-evidence-manifest-v1.schema.json",
        "docs/contracts/phase2a/schemas/phase2a5-context-evidence-case-v1.schema.json",
    )
    records = []
    for relative in relative_paths:
        path = repository_root / relative
        if not path.is_file():
            raise Phase2A5EvidenceError(f"generator source is missing: {relative}")
        records.append(_artifact(path, repository_root))
    return records


def _verify_checksum_inventory(root: Path) -> None:
    checksum_path = root / "CHECKSUMS.sha256"
    if not checksum_path.is_file():
        raise Phase2A5EvidenceError(f"checksum inventory missing: {checksum_path}")
    lines = checksum_path.read_text(encoding="utf-8").splitlines()
    expected_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name not in {"CHECKSUMS.sha256"}
    )
    actual_paths: list[str] = []
    for line in lines:
        digest, separator, relative = line.partition("  ")
        if separator != "  " or len(digest) != 64:
            raise Phase2A5EvidenceError(f"invalid checksum line in {checksum_path}: {line!r}")
        path = _safe_artifact_path(root, relative)
        if _sha256_file(path) != digest:
            raise Phase2A5EvidenceError(f"checksum inventory mismatch: {relative}")
        actual_paths.append(relative)
    if actual_paths != expected_paths:
        raise Phase2A5EvidenceError(f"checksum inventory paths differ in {root}")


def _write_checksum_inventory(root: Path) -> None:
    paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    )
    lines = [f"{_sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in paths]
    (root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rounded_window(dataset: rasterio.io.DatasetReader, geometry: Mapping[str, Any]) -> Window:
    geometry_native = transform_geom("EPSG:4326", dataset.crs, geometry, precision=-1)
    bounds = shape(geometry_native).bounds
    raw = from_bounds(*bounds, transform=dataset.transform)
    column_start = max(0, int(np.floor(raw.col_off)))
    row_start = max(0, int(np.floor(raw.row_off)))
    column_stop = min(dataset.width, int(np.ceil(raw.col_off + raw.width)))
    row_stop = min(dataset.height, int(np.ceil(raw.row_off + raw.height)))
    if column_stop <= column_start or row_stop <= row_start:
        raise Phase2A5EvidenceError("case geometry does not intersect MapBiomas crop")
    return Window(column_start, row_start, column_stop - column_start, row_stop - row_start)


def _read_polygon_values(
    crop_path: Path,
    geometry: Mapping[str, Any],
    *,
    all_touched: bool,
) -> tuple[np.ndarray, np.ndarray, Any]:
    with rasterio.open(crop_path) as dataset:
        if dataset.count != 1 or dataset.dtypes[0] != "uint8":
            raise Phase2A5EvidenceError(f"categorical crop header changed: {crop_path}")
        window = _rounded_window(dataset, geometry)
        values = dataset.read(1, window=window)
        transform = dataset.window_transform(window)
        native_geometry = transform_geom("EPSG:4326", dataset.crs, geometry, precision=-1)
        selected = geometry_mask(
            [native_geometry],
            out_shape=values.shape,
            transform=transform,
            invert=True,
            all_touched=all_touched,
        )
        return values, selected, transform


def _summary_from_context_api(
    values: np.ndarray,
    selected: np.ndarray,
    collection_key: str,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    raw = summarize_polygon_context(values, collection_key, registry, valid_mask=selected)
    if not isinstance(raw, Mapping):
        raise Phase2A5EvidenceError("summarize_polygon_context returned a non-object")
    categories = classify_mapbiomas_codes(values[selected], collection_key, registry)
    categories = np.asarray(categories).astype(str)
    selected_values = np.asarray(values[selected], dtype=np.uint8)
    histogram = {
        str(int(code)): int(count)
        for code, count in zip(*np.unique(selected_values, return_counts=True), strict=True)
    }
    category_counts = {
        category: int(np.count_nonzero(categories == category))
        for category in (
            "natural_vegetation",
            "other_natural_cover",
            "anthropic_cover",
            "uncertain_or_mixed",
            "nodata",
            "unmapped",
        )
    }
    pixel_count = int(selected_values.size)
    nodata_count = category_counts["nodata"]
    unmapped_count = category_counts["unmapped"]
    valid_count = pixel_count - nodata_count
    mapped_valid_count = valid_count - unmapped_count
    denominator = mapped_valid_count
    proportions = {
        category: (category_counts[category] / denominator if denominator else None)
        for category in (
            "natural_vegetation",
            "other_natural_cover",
            "anthropic_cover",
            "uncertain_or_mixed",
        )
    }
    normalized = {
        "pixel_count": pixel_count,
        "valid_pixel_count": valid_count,
        "mapped_valid_pixel_count": mapped_valid_count,
        "nodata_pixel_count": nodata_count,
        "unmapped_pixel_count": unmapped_count,
        "valid_coverage_fraction": valid_count / pixel_count if pixel_count else None,
        "class_histogram": histogram,
        "category_counts": category_counts,
        "category_proportions": proportions,
    }
    # The public API is independently executed and must agree with the normalized
    # replay fields it exposes; extra fields remain allowed in its own contract.
    aliases = {
        "pixel_count": ("pixel_count", "total_pixel_count"),
        "valid_pixel_count": ("valid_pixel_count",),
        "nodata_pixel_count": ("nodata_pixel_count",),
        "unmapped_pixel_count": ("unmapped_pixel_count",),
        "class_histogram": ("class_histogram",),
        "category_counts": ("category_counts",),
    }
    for field, names in aliases.items():
        for name in names:
            if name in raw and raw[name] != normalized[field]:
                raise Phase2A5EvidenceError(
                    f"context API {collection_key} {name} disagrees with deterministic replay"
                )

    return normalized


def _crop_record(
    collection_key: str,
    registry: Mapping[str, Any],
    context_manifest: Mapping[str, Any],
    repository_root: Path,
) -> tuple[Path, dict[str, Any]]:
    crop_config = registry["crop_policy"]["crops"][collection_key]
    path = repository_root / crop_config["output_path"]
    if not path.is_file():
        raise Phase2A5EvidenceError(f"regional crop missing: {path}")
    digest = _sha256_file(path)
    encoded_manifest = _canonical_bytes(context_manifest)
    if crop_config["output_path"].encode("utf-8") not in encoded_manifest:
        raise Phase2A5EvidenceError(f"context manifest does not bind {collection_key} crop path")
    if digest.encode("ascii") not in encoded_manifest:
        raise Phase2A5EvidenceError(
            f"context manifest does not bind {collection_key} crop checksum"
        )
    binding = {
        "crop_id": crop_config["crop_id"],
        "artifact": _external_artifact(path, repository_root),
        "source_sha256": registry["sources"][collection_key]["sha256"],
        "extent_id": registry["monitoring_extent"]["extent_id"],
        "categorical_resampling": "nearest_only",
    }
    return path, binding


def _mapbiomas_context(
    geometry: Mapping[str, Any],
    registry: Mapping[str, Any],
    crop_paths: Mapping[str, Path],
    crop_bindings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    primary_values, primary_mask, primary_transform = _read_polygon_values(
        crop_paths[COL3_KEY], geometry, all_touched=True
    )
    secondary_values, secondary_mask, _ = _read_polygon_values(
        crop_paths[COL10_KEY], geometry, all_touched=True
    )
    primary_summary = _summary_from_context_api(primary_values, primary_mask, COL3_KEY, registry)
    secondary_summary = _summary_from_context_api(
        secondary_values, secondary_mask, COL10_KEY, registry
    )
    for key, summary in ((COL3_KEY, primary_summary), (COL10_KEY, secondary_summary)):
        if not summary["mapped_valid_pixel_count"]:
            status = "unreviewable"
            reason = "no mapped valid pixels"
        elif summary["mapped_valid_pixel_count"] < summary["pixel_count"]:
            status = "partial"
            reason = (
                f"{summary['mapped_valid_pixel_count']} of {summary['pixel_count']} "
                "polygon pixels are valid and mapped"
            )
        else:
            status = "available"
            reason = None
        summary.update(
            {
                "collection_id": key,
                "crop_id": crop_bindings[key]["crop_id"],
                "crop_sha256": crop_bindings[key]["artifact"]["sha256"],
                "status": status,
                "reason": reason,
            }
        )

    with rasterio.open(crop_paths[COL10_KEY]) as secondary_dataset:
        aligned_secondary = np.full(primary_values.shape, 0, dtype=np.uint8)
        reproject(
            source=rasterio.band(secondary_dataset, 1),
            destination=aligned_secondary,
            src_transform=secondary_dataset.transform,
            src_crs=secondary_dataset.crs,
            src_nodata=0,
            dst_transform=primary_transform,
            dst_crs=secondary_dataset.crs,
            dst_nodata=0,
            resampling=Resampling.nearest,
        )
    primary_selected = primary_values[primary_mask]
    secondary_selected = aligned_secondary[primary_mask]
    api_agreement = calculate_agreement_disagreement(
        primary_selected,
        secondary_selected,
        registry,
        secondary_is_aligned=True,
    )
    if not isinstance(api_agreement, Mapping):
        raise Phase2A5EvidenceError("calculate_agreement_disagreement returned a non-object")
    primary_categories = np.asarray(
        classify_mapbiomas_codes(primary_selected, COL3_KEY, registry)
    ).astype(str)
    secondary_categories = np.asarray(
        classify_mapbiomas_codes(secondary_selected, COL10_KEY, registry)
    ).astype(str)
    primary_raw_valid = primary_categories != "nodata"
    secondary_raw_valid = secondary_categories != "nodata"
    joint_raw = primary_raw_valid & secondary_raw_valid
    exact_equal = primary_selected == secondary_selected
    joint_raw_count = int(np.count_nonzero(joint_raw))
    exact_agree = int(np.count_nonzero(joint_raw & exact_equal))
    primary_mapped = ~np.isin(primary_categories, ("nodata", "unmapped"))
    secondary_mapped = ~np.isin(secondary_categories, ("nodata", "unmapped"))
    joint_mapped = primary_mapped & secondary_mapped
    category_equal = primary_categories == secondary_categories
    joint_mapped_count = int(np.count_nonzero(joint_mapped))
    category_agree = int(np.count_nonzero(joint_mapped & category_equal))
    comparison_pixel_count = int(primary_selected.size)
    exact_pairs: dict[str, int] = {}
    category_pairs: dict[str, int] = {}
    for left, right in zip(
        primary_selected[joint_raw], secondary_selected[joint_raw], strict=True
    ):
        key = f"{int(left)}|{int(right)}"
        exact_pairs[key] = exact_pairs.get(key, 0) + 1
    for left, right in zip(
        primary_categories[joint_mapped],
        secondary_categories[joint_mapped],
        strict=True,
    ):
        key = f"{left}|{right}"
        category_pairs[key] = category_pairs.get(key, 0) + 1
    if not joint_mapped_count:
        agreement_status = "unreviewable"
        agreement_reason = "no jointly mapped pixels"
    elif joint_mapped_count < comparison_pixel_count:
        agreement_status = "partial"
        agreement_reason = (
            f"{joint_mapped_count} of {comparison_pixel_count} comparison-grid pixels "
            "are jointly valid and mapped"
        )
    else:
        agreement_status = "available"
        agreement_reason = None
    agreement = {
        "status": agreement_status,
        "reason": agreement_reason,
        "comparison_grid": COL3_KEY,
        "resampling": "nearest_only",
        "interpretation": "context_not_scientific_truth",
        "comparison_pixel_count": comparison_pixel_count,
        "joint_valid_raw_count": joint_raw_count,
        "exact_agreement_count": exact_agree,
        "exact_disagreement_count": joint_raw_count - exact_agree,
        "exact_agreement_fraction": exact_agree / joint_raw_count if joint_raw_count else None,
        "joint_mapped_count": joint_mapped_count,
        "category_agreement_count": category_agree,
        "category_disagreement_count": joint_mapped_count - category_agree,
        "category_agreement_fraction": (
            category_agree / joint_mapped_count if joint_mapped_count else None
        ),
        "exact_pair_histogram": dict(sorted(exact_pairs.items())),
        "category_pair_histogram": dict(sorted(category_pairs.items())),
    }
    for field in (
        "joint_valid_raw_count",
        "exact_agreement_count",
        "exact_disagreement_count",
        "joint_mapped_count",
        "category_agreement_count",
        "category_disagreement_count",
    ):
        if field in api_agreement and api_agreement[field] != agreement[field]:
            raise Phase2A5EvidenceError(f"context agreement API disagrees for {field}")

    natural_fraction = primary_summary["category_proportions"]["natural_vegetation"]
    api_outcomes = strong_subset_membership(natural_fraction, registry)
    if not isinstance(api_outcomes, Mapping):
        raise Phase2A5EvidenceError("strong_subset_membership returned a non-object")
    candidates_by_id = {
        candidate["candidate_id"]: candidate
        for candidate in registry["strong_subset"]["candidates"]
    }
    outcomes: dict[str, dict[str, Any]] = {}
    for candidate_id in MAPBIOMAS_CANDIDATES:
        config = candidates_by_id[candidate_id]
        membership = (
            "not_assessed"
            if natural_fraction is None
            else "included"
            if natural_fraction >= config["threshold"]
            else "excluded"
        )
        reason = "no mapped valid Collection 3 pixels" if natural_fraction is None else None
        candidate_api = api_outcomes.get(candidate_id)
        if isinstance(candidate_api, Mapping):
            api_membership = candidate_api.get("membership", candidate_api.get("outcome"))
        else:
            api_membership = candidate_api
        if api_membership is not None and api_membership != membership:
            raise Phase2A5EvidenceError(f"strong-subset API disagrees for {candidate_id}")
        outcomes[candidate_id] = {
            "candidate_id": candidate_id,
            "threshold": config["threshold"],
            "natural_fraction": natural_fraction,
            "membership": membership,
            "reason": reason,
            "selected_or_activated": False,
            "raw_detection_retained": True,
        }
    return {
        "mapping_version": registry["class_mappings"]["mapping_version"],
        "polygon_pixel_rule": registry["strong_subset"]["polygon_pixel_rule"],
        "collections": {COL3_KEY: primary_summary, COL10_KEY: secondary_summary},
        "agreement": agreement,
        "strong_subset_alternatives": outcomes,
    }


def _load_npy(path: Path) -> np.ndarray:
    try:
        value = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise Phase2A5EvidenceError(f"cannot load array {path}: {exc}") from exc
    return np.asarray(value)


def _p2a4_artifact_path(
    root: Path,
    record: Mapping[str, Any],
) -> Path:
    path = _safe_artifact_path(root, str(record["path"]))
    _verify_record(path, record)
    return path


def _polygon_indices_on_context_grid(
    geometry: Mapping[str, Any],
    context_window: Mapping[str, Any],
    *,
    context_crs: str = "EPSG:32724",
) -> np.ndarray:
    native = transform_geom("EPSG:4326", context_crs, geometry, precision=-1)
    transform = rasterio.Affine(*context_window["transform"])
    mask = geometry_mask(
        [native],
        out_shape=(context_window["height"], context_window["width"]),
        transform=transform,
        invert=True,
        all_touched=False,
    )
    return np.argwhere(mask).astype(np.int32, copy=False)


def _find_composition(
    case: Mapping[str, Any],
    cloud_id: str,
    composition_id: str,
) -> Mapping[str, Any]:
    try:
        return case["processing_audit"]["compositions"][cloud_id][composition_id]
    except KeyError as exc:
        raise Phase2A5EvidenceError(
            f"Phase 2A.4 composition missing: {cloud_id} × {composition_id}"
        ) from exc


def _find_factorial_cells(
    case: Mapping[str, Any],
    cloud_id: str,
    composition_id: str,
) -> list[Mapping[str, Any]]:
    matches = [
        cell
        for cell in case["factorial_cells"]
        if cell["candidates"]["cloud_mask"] == cloud_id
        and cell["candidates"]["daily_composition"] == composition_id
    ]
    drought_ids = {
        cell["candidates"]["drought_adjustment"] for cell in matches
    }
    if len(matches) != 2 or drought_ids != {
        "drought-disabled-v1",
        "chirps-v2-spi3-season-matched-1981-2025-v1",
    }:
        raise Phase2A5EvidenceError(
            f"expected both unchanged Phase 2A.4 drought cells for {cloud_id} × "
            f"{composition_id}"
        )
    return sorted(
        matches, key=lambda cell: cell["candidates"]["drought_adjustment"]
    )


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    result = np.full(numerator.shape, np.nan, dtype=np.float32)
    valid = np.isfinite(numerator) & np.isfinite(denominator) & (denominator != 0)
    np.divide(numerator, denominator, out=result, where=valid)
    return result


def _normalize_signature_labels(value: Any, shape_: tuple[int, ...]) -> np.ndarray:
    if isinstance(value, Mapping):
        for key in ("labels", "classes", "signature_labels"):
            if key in value:
                value = value[key]
                break
    labels = np.asarray(value).astype(str)
    if labels.shape != shape_:
        raise Phase2A5EvidenceError("contextual signature API returned the wrong shape")
    if not set(np.unique(labels)).issubset(SIGNATURE_LABELS):
        raise Phase2A5EvidenceError("contextual signature API returned an unknown label")
    return labels


def _signature_summary(labels: np.ndarray) -> tuple[dict[str, int], dict[str, float | None]]:
    api = contextual_signature_proportions(labels)
    if not isinstance(api, Mapping):
        raise Phase2A5EvidenceError("contextual_signature_proportions returned a non-object")
    counts = {label: int(np.count_nonzero(labels == label)) for label in SIGNATURE_LABELS}
    assessed = sum(counts[label] for label in SIGNATURE_LABELS[:-1])
    total = int(labels.size)
    proportions: dict[str, float | None] = {
        label: counts[label] / assessed if assessed else None for label in SIGNATURE_LABELS[:-1]
    }
    proportions["not_assessed"] = counts["not_assessed"] / total if total else 1.0
    api_counts = api.get("counts", api.get("class_counts"))
    if api_counts is not None and dict(api_counts) != counts:
        raise Phase2A5EvidenceError("contextual signature API count mismatch")
    return counts, proportions


def _median_or_none(value: np.ndarray) -> float | None:
    finite = np.asarray(value)[np.isfinite(value)]
    return float(np.median(finite)) if finite.size else None


def _spectral_stratum(
    *,
    evidence_root: Path,
    output_root: Path,
    sample_id: str,
    polygon_indices: np.ndarray,
    baseline_nbr: np.ndarray,
    p2a4_case: Mapping[str, Any],
    cloud_id: str,
    composition_id: str,
) -> dict[str, Any]:
    composition = _find_composition(p2a4_case, cloud_id, composition_id)
    cells = _find_factorial_cells(p2a4_case, cloud_id, composition_id)
    stratum_id = "p2a5-stratum-v1-" + _canonical_sha256([cloud_id, composition_id])
    pixel_count = int(polygon_indices.shape[0])
    row_indices = polygon_indices[:, 0] if pixel_count else np.array([], dtype=np.int32)
    column_indices = polygon_indices[:, 1] if pixel_count else np.array([], dtype=np.int32)
    nan_values = np.full(pixel_count, np.nan, dtype=np.float32)
    valid = np.zeros(pixel_count, dtype=np.uint8)
    labels = np.full(pixel_count, "not_assessed", dtype="<U32")
    reason: str | None = None
    if composition.get("status") != "available":
        reason = composition.get("reason") or "Phase 2A.4 composition unavailable"
        post_nbr = nan_values.copy()
        bsi = nan_values.copy()
        dnbr = nan_values.copy()
        status = "unreviewable"
    else:
        artifacts = composition["artifacts"]
        values = _load_npy(_p2a4_artifact_path(evidence_root, artifacts["values"]))
        composite_valid = _load_npy(
            _p2a4_artifact_path(evidence_root, artifacts["valid_mask"])
        ).astype(bool)
        if values.shape[0] != len(REFLECTANCE_BANDS) or values.shape[1:] != baseline_nbr.shape:
            raise Phase2A5EvidenceError("Phase 2A.4 composition/baseline grid mismatch")
        band = {
            name: np.asarray(values[index], dtype=np.float32)
            for index, name in enumerate(REFLECTANCE_BANDS)
        }
        post_grid = _safe_ratio(band["nir08"] - band["swir22"], band["nir08"] + band["swir22"])
        bsi_grid = _safe_ratio(
            (band["swir16"] + band["red"]) - (band["nir"] + band["blue"]),
            band["swir16"] + band["red"] + band["nir"] + band["blue"],
        )
        dnbr_grid = np.asarray(baseline_nbr, dtype=np.float32) - post_grid
        post_nbr = post_grid[row_indices, column_indices].astype(np.float32, copy=True)
        bsi = bsi_grid[row_indices, column_indices].astype(np.float32, copy=True)
        dnbr = dnbr_grid[row_indices, column_indices].astype(np.float32, copy=True)
        valid_bool = (
            composite_valid[row_indices, column_indices]
            & np.isfinite(post_nbr)
            & np.isfinite(bsi)
            & np.isfinite(dnbr)
        )
        valid = valid_bool.astype(np.uint8)
        api_labels = classify_contextual_signature_pixels(dnbr, post_nbr, bsi)
        labels = _normalize_signature_labels(api_labels, dnbr.shape)
        labels[~valid_bool] = "not_assessed"
        valid_count = int(np.count_nonzero(valid_bool))
        if not valid_count:
            status = "unreviewable"
            reason = "no finite within-polygon measurements"
        else:
            partial_reasons = []
            if valid_count < pixel_count:
                partial_reasons.append(
                    f"{valid_count} of {pixel_count} polygon pixels have finite "
                    "candidate-composition measurements"
                )
            status = "partial" if partial_reasons else "available"
            reason = "; ".join(partial_reasons) if partial_reasons else None

    not_assessed = (labels == "not_assessed").astype(np.uint8)
    signature_codes = np.array([SIGNATURE_CODES[label] for label in labels], dtype=np.uint8)
    counts, proportions = _signature_summary(labels)
    stratum_dir = output_root / "cases" / sample_id / "spectral" / stratum_id
    array_values = {
        "dnbr": dnbr,
        "post_nbr": post_nbr,
        "bsi": bsi,
        "valid": valid,
        "not_assessed": not_assessed,
        "signature_codes": signature_codes,
    }
    array_records: dict[str, dict[str, Any]] = {}
    for name, value in array_values.items():
        path = stratum_dir / f"{name.replace('_', '-')}.npy"
        _write_npy(path, value)
        array_records[name] = _array_artifact(path, output_root, value)
    return {
        "stratum_id": stratum_id,
        "cloud_mask_candidate_id": cloud_id,
        "daily_composition_candidate_id": composition_id,
        "phase2a4_cells": [
            {
                "cell_id": cell["cell_id"],
                "drought_adjustment_candidate_id": cell["candidates"][
                    "drought_adjustment"
                ],
                "availability": cell["availability"],
            }
            for cell in cells
        ],
        "status": status,
        "reason": reason,
        "pixel_count": pixel_count,
        "valid_pixel_count": int(np.count_nonzero(valid)),
        "not_assessed_pixel_count": counts["not_assessed"],
        "class_counts": counts,
        "proportions": proportions,
        "medians": {
            "dnbr": _median_or_none(dnbr[valid.astype(bool)]),
            "post_nbr": _median_or_none(post_nbr[valid.astype(bool)]),
            "bsi": _median_or_none(bsi[valid.astype(bool)]),
        },
        "arrays": array_records,
    }


def _normalize_aggregation(
    strata: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    api_input = [
        {
            "stratum_id": stratum["stratum_id"],
            "status": stratum["status"],
            "class_counts": stratum["class_counts"],
            "proportions": stratum["proportions"],
        }
        for stratum in strata
    ]
    api = aggregate_contextual_signature_candidates(api_input, registry)
    if not isinstance(api, Mapping):
        raise Phase2A5EvidenceError(
            "aggregate_contextual_signature_candidates returned a non-object"
        )
    available = [
        stratum
        for stratum in strata
        if stratum["status"] in {"available", "partial"}
        and sum(stratum["class_counts"][label] for label in SIGNATURE_LABELS[:-1]) > 0
    ]
    medians: dict[str, float | None] = {}
    for label in SIGNATURE_LABELS[:-1]:
        values = [stratum["proportions"][label] for stratum in available]
        values = [float(value) for value in values if value is not None]
        medians[label] = float(np.median(values)) if values else None
    candidates_by_id = {
        candidate["candidate_id"]: candidate
        for candidate in registry["contextual_signature"]["candidates"]
    }
    outcomes: dict[str, dict[str, Any]] = {}
    for candidate_id in SIGNATURE_CANDIDATES:
        candidate = candidates_by_id[candidate_id]
        if not available or any(value is None for value in medians.values()):
            label = "not_assessed"
            status = "unreviewable"
            reason = "no assessed measurements in any cloud-by-composition stratum"
        else:
            ordered = sorted(
                ((float(value), name) for name, value in medians.items()),
                key=lambda item: (-item[0], item[1]),
            )
            top_value, top_label = ordered[0]
            runner_up = ordered[1][0]
            unique_top = top_value > runner_up
            if candidate["minimum_top_share"] is not None:
                emit = unique_top and top_value >= candidate["minimum_top_share"]
            else:
                emit = unique_top and (top_value - runner_up) >= candidate["minimum_margin"]
            label = top_label if emit else "mixed_or_uncertain"
            status = (
                "available"
                if len(available) == 4
                and all(stratum["status"] == "available" for stratum in available)
                else "partial"
            )
            reason = (
                None
                if status == "available"
                else f"{len(available)} of 4 strata contributed assessed evidence"
            )
        api_candidate = api.get(candidate_id)
        if isinstance(api_candidate, Mapping):
            api_label = api_candidate.get("label", api_candidate.get("outcome"))
        else:
            api_label = api_candidate
        if api_label is not None and api_label != label:
            raise Phase2A5EvidenceError(f"signature aggregation API disagrees for {candidate_id}")
        outcomes[candidate_id] = {
            "candidate_id": candidate_id,
            "status": status,
            "reason": reason,
            "label": label,
            "available_stratum_count": len(available),
            "median_assessed_proportions": medians,
            "selected_or_activated": False,
            "causal_inference": False,
        }
    return outcomes


def _spectral_context(
    *,
    geometry: Mapping[str, Any],
    sample_id: str,
    p2a4_case: Mapping[str, Any],
    p2a4_root: Path,
    output_root: Path,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    context_window = p2a4_case["grid"]["context_window"]
    reference_grid = p2a4_case["grid"]["reference_grid"]
    context_crs = reference_grid["crs"]
    if context_crs != "EPSG:32724" or reference_grid["pixel_size_m"] != 20:
        raise Phase2A5EvidenceError("Phase 2A.4 frozen detector grid changed")
    context_transform = list(context_window["transform"])
    if context_transform[:2] != [20, 0] or context_transform[3:5] != [0, -20]:
        raise Phase2A5EvidenceError("Phase 2A.4 context window is not on the 20 m grid")
    polygon_indices = _polygon_indices_on_context_grid(
        geometry, context_window, context_crs=context_crs
    )
    indices_path = output_root / "cases" / sample_id / "spectral" / "polygon-pixel-indices.npy"
    _write_npy(indices_path, polygon_indices)
    indices_record = _array_artifact(indices_path, output_root, polygon_indices)
    baseline_records = [
        record
        for record in p2a4_case["baseline"]["artifacts"]
        if record["path"].endswith("/nbr-mean.npy")
    ]
    if len(baseline_records) != 1:
        raise Phase2A5EvidenceError("Phase 2A.4 case does not bind one accepted NBR mean")
    baseline_nbr = _load_npy(_p2a4_artifact_path(p2a4_root, baseline_records[0]))
    compositions = p2a4_case["processing_audit"]["compositions"]
    cloud_ids = sorted(compositions)
    if len(cloud_ids) != 2:
        raise Phase2A5EvidenceError("expected exactly two Phase 2A.4 cloud-mask candidates")
    composition_id_sets = [set(compositions[cloud_id]) for cloud_id in cloud_ids]
    if len(composition_id_sets[0]) != 2 or any(
        values != composition_id_sets[0] for values in composition_id_sets
    ):
        raise Phase2A5EvidenceError(
            "expected the same two compositions under each cloud-mask candidate"
        )
    composition_ids = sorted(composition_id_sets[0])
    strata = [
        _spectral_stratum(
            evidence_root=p2a4_root,
            output_root=output_root,
            sample_id=sample_id,
            polygon_indices=polygon_indices,
            baseline_nbr=baseline_nbr,
            p2a4_case=p2a4_case,
            cloud_id=cloud_id,
            composition_id=composition_id,
        )
        for cloud_id in cloud_ids
        for composition_id in composition_ids
    ]
    return {
        "rule_version": registry["contextual_signature"]["rule_version"],
        "polygon_pixel_rule": registry["contextual_signature"]["polygon_pixel_rule"],
        "source_grid": {
            "crs": context_crs,
            "pixel_size_m": reference_grid["pixel_size_m"],
            "width": context_window["width"],
            "height": context_window["height"],
            "transform": context_transform,
            "bounds": list(context_window["bounds"]),
            "context_window_sha256": _canonical_sha256(context_window),
        },
        "formulae": FORMULAE,
        "polygon_pixel_count": int(polygon_indices.shape[0]),
        "polygon_pixel_indices": indices_record,
        "strata": strata,
        "aggregation_candidates": _normalize_aggregation(strata, registry),
    }


def _format_percent(value: float | None) -> str:
    return "not assessed" if value is None else f"{100.0 * value:.1f}%"


def _draw_bar(
    draw: ImageDraw.ImageDraw,
    *,
    y: int,
    label: str,
    value: float | None,
    color: tuple[int, int, int],
) -> None:
    draw.text((46, y), label, fill=(35, 42, 50))
    x0, x1 = 330, 760
    draw.rectangle((x0, y - 2, x1, y + 16), outline=(180, 185, 190), width=1)
    if value is not None:
        width = int(round((x1 - x0) * min(1.0, max(0.0, float(value)))))
        if width:
            draw.rectangle((x0 + 1, y - 1, x0 + width, y + 15), fill=color)
    draw.text((775, y), _format_percent(value), fill=(35, 42, 50))


def _panel_canvas(subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (920, 540), (250, 250, 248))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    # Explicitly pass the bundled default font so Pillow never discovers a
    # machine-local font.  The font object is retained by ImageDraw internally.
    draw.font = font
    draw.rectangle((20, 20, 900, 520), fill=(255, 255, 255), outline=(95, 105, 115), width=2)
    draw.text((46, 46), "Context candidate", fill=(20, 28, 36))
    draw.text((46, 72), subtitle, fill=(65, 73, 82))
    return image, draw


def _png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=False, compress_level=9)
    return stream.getvalue()


def _map_panel_bytes(mapbiomas: Mapping[str, Any], candidate_id: str) -> bytes:
    image, draw = _panel_canvas("Regional land-cover proportions; provisional context")
    primary = mapbiomas["collections"][COL3_KEY]
    values = primary["category_proportions"]
    rows = (
        ("Natural vegetation", values["natural_vegetation"], (65, 130, 85)),
        ("Other natural cover", values["other_natural_cover"], (85, 145, 175)),
        ("Anthropic cover", values["anthropic_cover"], (205, 145, 65)),
        ("Uncertain / mixed", values["uncertain_or_mixed"], (145, 125, 155)),
    )
    for index, (label, value, color) in enumerate(rows):
        _draw_bar(draw, y=128 + index * 54, label=label, value=value, color=color)
    outcome = mapbiomas["strong_subset_alternatives"][candidate_id]["membership"].replace("_", " ")
    draw.text((46, 365), f"Strong-subset contextual outcome: {outcome}", fill=(25, 35, 45))
    agreement = mapbiomas["agreement"]["category_agreement_fraction"]
    draw.text(
        (46, 397),
        f"Collection agreement context: {_format_percent(agreement)}",
        fill=(65, 73, 82),
    )
    draw.text(
        (46, 429),
        "Missing, NoData, and unmapped pixels remain explicit.",
        fill=(65, 73, 82),
    )
    draw.text((46, 480), "context only; no cause inferred", fill=(100, 50, 40))
    return _png_bytes(image)


def _signature_panel_bytes(spectral: Mapping[str, Any], candidate_id: str) -> bytes:
    image, draw = _panel_canvas("Non-causal spectral-signature proportions across all strata")
    outcome = spectral["aggregation_candidates"][candidate_id]
    values = outcome["median_assessed_proportions"]
    rows = (
        ("Signature class A", values["fire_like"], (185, 85, 55)),
        ("Signature class B", values["exposed_soil_or_clearing_like"], (205, 155, 65)),
        ("Signature class C", values["mixed_or_uncertain"], (125, 115, 150)),
    )
    for index, (label, value, color) in enumerate(rows):
        _draw_bar(draw, y=136 + index * 60, label=label, value=value, color=color)
    blind_labels = {
        "fire_like": "class A",
        "exposed_soil_or_clearing_like": "class B",
        "mixed_or_uncertain": "class C",
        "not_assessed": "not assessed",
    }
    draw.text(
        (46, 346),
        f"Contextual signature outcome: {blind_labels[outcome['label']]}",
        fill=(25, 35, 45),
    )
    draw.text(
        (46, 382),
        f"Assessed cloud-by-composition strata: {outcome['available_stratum_count']} of 4",
        fill=(65, 73, 82),
    )
    draw.text(
        (46, 418),
        "Every available stratum is retained; none is selected here.",
        fill=(65, 73, 82),
    )
    draw.text((46, 480), "context only; no cause inferred", fill=(100, 50, 40))
    return _png_bytes(image)


def _write_panel(
    path: Path,
    output_root: Path,
    content: bytes,
    *,
    status: str,
    reason: str | None,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    record = _artifact(path, output_root)
    record.update({"status": status, "reason": reason, "media_type": "image/png"})
    return {
        "status": record["status"],
        "reason": record["reason"],
        "path": record["path"],
        "bytes": record["bytes"],
        "sha256": record["sha256"],
        "media_type": record["media_type"],
    }


def _candidate_panels(
    *,
    output_root: Path,
    sample_id: str,
    mapbiomas: Mapping[str, Any],
    spectral: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {
        "mapbiomas": {},
        "contextual_signature": {},
    }
    for candidate_id in MAPBIOMAS_CANDIDATES:
        outcome = mapbiomas["strong_subset_alternatives"][candidate_id]
        if outcome["membership"] == "not_assessed":
            result["mapbiomas"][candidate_id] = {
                "status": "unreviewable",
                "reason": outcome["reason"] or "MapBiomas context is not assessable",
                "path": None,
                "bytes": None,
                "sha256": None,
                "media_type": None,
            }
        else:
            primary_status = mapbiomas["collections"][COL3_KEY]["status"]
            primary_reason = mapbiomas["collections"][COL3_KEY]["reason"]
            result["mapbiomas"][candidate_id] = _write_panel(
                output_root
                / "cases"
                / sample_id
                / "candidate-panels"
                / "mapbiomas"
                / f"{candidate_id}.png",
                output_root,
                _map_panel_bytes(mapbiomas, candidate_id),
                status=primary_status,
                reason=outcome["reason"] or primary_reason,
            )
    for candidate_id in SIGNATURE_CANDIDATES:
        outcome = spectral["aggregation_candidates"][candidate_id]
        if outcome["status"] == "unreviewable":
            result["contextual_signature"][candidate_id] = {
                "status": "unreviewable",
                "reason": outcome["reason"] or "spectral context is not assessable",
                "path": None,
                "bytes": None,
                "sha256": None,
                "media_type": None,
            }
        else:
            result["contextual_signature"][candidate_id] = _write_panel(
                output_root
                / "cases"
                / sample_id
                / "candidate-panels"
                / "contextual_signature"
                / f"{candidate_id}.png",
                output_root,
                _signature_panel_bytes(spectral, candidate_id),
                status=outcome["status"],
                reason=outcome["reason"],
            )
    return result


def _status_for_case(mapbiomas: Mapping[str, Any], spectral: Mapping[str, Any]) -> str:
    statuses = [summary["status"] for summary in mapbiomas["collections"].values()]
    statuses.append(mapbiomas["agreement"]["status"])
    statuses.extend(stratum["status"] for stratum in spectral["strata"])
    statuses.extend(outcome["status"] for outcome in spectral["aggregation_candidates"].values())
    if all(status == "available" for status in statuses):
        return "available"
    if all(status == "unreviewable" for status in statuses):
        return "unreviewable"
    return "partial"


def _source_binding(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_artifact_sha256": source["source_artifact_sha256"],
        "source_feature_index": source["source_feature_index"],
        "geometry_sha256": source["geometry_sha256"],
        "source_record_id": source["source_record_id"],
    }


def _build_case(
    *,
    output_root: Path,
    repository_root: Path,
    p2a3_root: Path,
    p2a4_root: Path,
    registry_path: Path,
    context_manifest_path: Path,
    registry: Mapping[str, Any],
    crop_paths: Mapping[str, Path],
    crop_bindings: Mapping[str, Mapping[str, Any]],
    feature: Mapping[str, Any],
    source_order_index: int,
    crosswalk: Mapping[str, Any],
    p2a4_descriptor: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    properties = feature["properties"]
    sample_id = properties["sample_id"]
    blind_case_id = crosswalk["blind_case_id"]
    if p2a4_descriptor["blind_case_id"] != blind_case_id:
        raise Phase2A5EvidenceError(f"Phase 2A.3/2A.4 blind ID mismatch for {sample_id}")
    p2a3_case_path = p2a3_root / "coordinator" / "cases" / f"{sample_id}.json"
    p2a3_case = _load_json(p2a3_case_path)
    p2a4_case_path = _safe_artifact_path(p2a4_root, p2a4_descriptor["record"]["path"])
    _verify_record(p2a4_case_path, p2a4_descriptor["record"])
    p2a4_case = _load_json(p2a4_case_path)
    geometry = feature["geometry"]
    geometry_sha256 = _canonical_sha256(geometry)
    if p2a3_case["source"]["geometry_sha256"] != geometry_sha256:
        raise Phase2A5EvidenceError(f"Phase 2A.3 geometry checksum mismatch for {sample_id}")
    if p2a4_case["target_geometry_sha256"] != geometry_sha256:
        raise Phase2A5EvidenceError(f"Phase 2A.4 geometry checksum mismatch for {sample_id}")
    if properties["observed_on"] != p2a4_case["target_date"]:
        raise Phase2A5EvidenceError(f"target-date mismatch for {sample_id}")
    mapbiomas = _mapbiomas_context(geometry, registry, crop_paths, crop_bindings)
    spectral = _spectral_context(
        geometry=geometry,
        sample_id=sample_id,
        p2a4_case=p2a4_case,
        p2a4_root=p2a4_root,
        output_root=output_root,
        registry=registry,
    )
    panels = _candidate_panels(
        output_root=output_root,
        sample_id=sample_id,
        mapbiomas=mapbiomas,
        spectral=spectral,
    )
    source = p2a3_case["source"]
    source_binding = _source_binding(source)
    record = {
        "$schema": CASE_SCHEMA_URL,
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample_id,
        "blind_case_id": blind_case_id,
        "source_order_index": source_order_index,
        "target_date": properties["observed_on"],
        "status": _status_for_case(mapbiomas, spectral),
        "case_replaced": False,
        "bindings": {
            "phase2a3_case": _external_artifact(p2a3_case_path, repository_root),
            "phase2a4_case": _external_artifact(p2a4_case_path, repository_root),
            "candidate_registry": _external_artifact(registry_path, repository_root),
            "context_manifest": _external_artifact(context_manifest_path, repository_root),
        },
        "raw_detection": {
            "source_record_id": source["source_record_id"],
            "source_feature_index": source["source_feature_index"],
            "source_binding_sha256": _canonical_sha256(source_binding),
            "geometry": geometry,
            "geometry_sha256": geometry_sha256,
            "canonical_observation_id": None,
            "canonical_event_id": None,
            "geometry_preserved": True,
            "identity_preserved": True,
            "order_preserved": True,
            "filtered_or_relabelled": False,
        },
        "mapbiomas": mapbiomas,
        "spectral_context": spectral,
        "candidate_panels": panels,
        "blank_review": BLANK_REVIEW,
        "claims": CASE_CLAIMS,
    }
    path = output_root / "cases" / sample_id / "case-evidence.json"
    _write_json(path, record)
    descriptor = {
        "sample_id": sample_id,
        "blind_case_id": blind_case_id,
        "status": record["status"],
        "record": _artifact(path, output_root),
    }
    return record, descriptor


def _copy_schema(source: Path, output_root: Path) -> dict[str, Any]:
    destination = output_root / "schemas" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    return _artifact(destination, output_root)


def _context_artifact_id(manifest: Mapping[str, Any]) -> str:
    for key in ("artifact_id", "context_id", "manifest_id", "package_id"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return value
    raise Phase2A5EvidenceError("Phase 2A.5 context manifest has no artifact identity")


def _validate_frozen_inputs(
    *,
    repository_root: Path,
    p2a3_root: Path,
    p2a4_root: Path,
    registry_path: Path,
    context_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if _sha256_file(p2a3_root / "manifest.json") != PHASE2A3_MANIFEST_SHA256:
        raise Phase2A5EvidenceError("frozen Phase 2A.3 manifest checksum changed")
    if _sha256_file(p2a4_root / "manifest.json") != PHASE2A4_MANIFEST_SHA256:
        raise Phase2A5EvidenceError("frozen Phase 2A.4 manifest checksum changed")
    if _sha256_file(registry_path) != REGISTRY_SHA256:
        raise Phase2A5EvidenceError("fixed Phase 2A.5 candidate registry checksum changed")
    from .phase2a4_evidence import validate_phase2a4_evidence_artifact
    from .validator import validate_validation_package

    validate_validation_package(p2a3_root)
    validate_phase2a4_evidence_artifact(
        p2a4_root,
        parent_package_dir=p2a3_root,
        candidate_registry_path=repository_root / "config/phase2a4_candidates_v1.json",
        rainfall_artifact_dir=repository_root / "data/validation/phase2a4-rainfall-reference-v1",
        baseline_manifest_path=repository_root / "config/baseline_manifest_v1.json",
        repository_root=repository_root,
    )
    registry = load_context_registry(registry_path)
    if registry["monitoring_extent"]["source_aoi_sha256"] != (
        "2bff31afa6cb74630a437b4fffb96ad88f7f873a3aa1461f337c66f61c209881"
    ):
        raise Phase2A5EvidenceError(
            "candidate registry does not bind the accepted Phase 1 AOI source"
        )
    if registry["strong_subset"]["polygon_pixel_rule"] != "all_touched_true":
        raise Phase2A5EvidenceError("MapBiomas polygon extraction rule changed")
    signature = registry["contextual_signature"]
    if signature.get("polygon_pixel_rule") != "detector_grid_pixel_center_within_polygon-v1":
        raise Phase2A5EvidenceError("spectral polygon extraction rule changed")
    if signature.get("all_touched") is not False:
        raise Phase2A5EvidenceError("spectral extraction must remain center-in-polygon")
    context_result = validate_phase2a5_context_artifact(
        context_root,
        registry_path=registry_path,
        repository_root=repository_root,
    )
    if isinstance(context_result, Mapping) and "manifest" in context_result:
        context_manifest = context_result["manifest"]
    elif isinstance(context_result, Mapping):
        context_manifest = dict(context_result)
    else:
        context_manifest = _load_json(context_root / "manifest.json")
    p2a3_manifest = _load_json(p2a3_root / "manifest.json")
    p2a4_manifest = _load_json(p2a4_root / "manifest.json")
    return p2a3_manifest, p2a4_manifest, dict(registry), dict(context_manifest)


def _input_case_maps(
    p2a3_root: Path,
    p2a4_manifest: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    sample = _load_json(p2a3_root / "sampling/sample.geojson")
    features = sample.get("features")
    if not isinstance(features, list) or len(features) != 60:
        raise Phase2A5EvidenceError("Phase 2A.3 sample is not the exact 60-case population")
    sample_ids = [feature["properties"]["sample_id"] for feature in features]
    if len(set(sample_ids)) != 60:
        raise Phase2A5EvidenceError("Phase 2A.3 sample IDs are not unique")
    crosswalk_value = _load_json(p2a3_root / "coordinator/crosswalk.json")
    mappings = crosswalk_value.get("mappings")
    if not isinstance(mappings, list) or len(mappings) != 60:
        raise Phase2A5EvidenceError("Phase 2A.3 crosswalk is not the exact 60-case mapping")
    crosswalk = {value["sample_id"]: value for value in mappings}
    p2a4_cases = {value["sample_id"]: value for value in p2a4_manifest["cases"]}
    if set(sample_ids) != set(crosswalk) or set(sample_ids) != set(p2a4_cases):
        raise Phase2A5EvidenceError("Phase 2A.3/2A.4 case populations differ")
    return features, crosswalk, p2a4_cases


def _manifest_identity_input(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pipeline_version": manifest["pipeline_version"],
        "generated_at": manifest["generated_at"],
        "runtime_versions": manifest["runtime_versions"],
        "generator_source_inventory": manifest["generator_source_inventory"],
        "schema_bindings": manifest["schema_bindings"],
        "parents": manifest["parents"],
        "candidate_registry_sha256": manifest["candidate_registry"]["artifact"][
            "sha256"
        ],
        "mapbiomas_context": manifest["mapbiomas_context"],
        "case_population": manifest["case_population"],
        "candidate_families": manifest["candidate_families"],
        "cases": manifest["cases"],
        "counts": manifest["counts"],
        "source_limitations": manifest["source_limitations"],
        "claims": manifest["claims"],
    }


def _actual_inventory(root: Path) -> list[dict[str, Any]]:
    return [
        _artifact(path, root)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in {"manifest.json", "CHECKSUMS.sha256"}
    ]


def _build_phase2a5_evidence_in_place(
    config: Phase2A5EvidenceConfig,
) -> dict[str, Any]:
    """Assemble and deeply validate one new artifact at a non-existing path."""
    # Keep the destination lexical so a broken symlink is treated as an
    # occupied path rather than resolved away by Path.resolve().
    output_root = Path(config.output_dir).absolute()
    if os.path.lexists(output_root):
        raise Phase2A5EvidenceError(
            f"output already exists; refusing to replace audit evidence: {output_root}"
        )
    repository_root = (
        Path(config.repository_root).resolve()
        if config.repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    p2a3_root = Path(config.parent_phase2a3_dir).resolve()
    p2a4_root = Path(config.parent_phase2a4_dir).resolve()
    registry_path = Path(config.candidate_registry_path).resolve()
    context_root = Path(config.context_artifact_dir).resolve()
    generated_at = _parse_timestamp(config.generated_at)
    p2a3_manifest, p2a4_manifest, registry, context_manifest = _validate_frozen_inputs(
        repository_root=repository_root,
        p2a3_root=p2a3_root,
        p2a4_root=p2a4_root,
        registry_path=registry_path,
        context_root=context_root,
    )
    output_root.mkdir(parents=True, exist_ok=False)
    schema_root = repository_root / "docs/contracts/phase2a/schemas"
    manifest_schema_path = schema_root / "phase2a5-context-evidence-manifest-v1.schema.json"
    case_schema_path = schema_root / "phase2a5-context-evidence-case-v1.schema.json"
    manifest_schema_record = _copy_schema(manifest_schema_path, output_root)
    case_schema_record = _copy_schema(case_schema_path, output_root)
    case_schema = _load_json(case_schema_path)
    features, crosswalk, p2a4_cases = _input_case_maps(p2a3_root, p2a4_manifest)
    context_manifest_path = context_root / "manifest.json"
    crop_paths: dict[str, Path] = {}
    crop_bindings: dict[str, dict[str, Any]] = {}
    for collection_key in (COL3_KEY, COL10_KEY):
        crop_path, binding = _crop_record(
            collection_key, registry, context_manifest, repository_root
        )
        crop_paths[collection_key] = crop_path
        crop_bindings[collection_key] = binding
    descriptors: list[dict[str, Any]] = []
    for source_order_index, feature in enumerate(features):
        sample_id = feature["properties"]["sample_id"]
        record, descriptor = _build_case(
            output_root=output_root,
            repository_root=repository_root,
            p2a3_root=p2a3_root,
            p2a4_root=p2a4_root,
            registry_path=registry_path,
            context_manifest_path=context_manifest_path,
            registry=registry,
            crop_paths=crop_paths,
            crop_bindings=crop_bindings,
            feature=feature,
            source_order_index=source_order_index,
            crosswalk=crosswalk[sample_id],
            p2a4_descriptor=p2a4_cases[sample_id],
        )
        _validate_schema(record, case_schema, f"Phase 2A.5 case {sample_id}")
        descriptors.append(descriptor)
    descriptors.sort(key=lambda value: value["blind_case_id"])
    original_sample_ids = [feature["properties"]["sample_id"] for feature in features]
    geometry_hashes = [_canonical_sha256(feature["geometry"]) for feature in features]
    status_counts = {
        status: sum(descriptor["status"] == status for descriptor in descriptors)
        for status in ("available", "partial", "unreviewable")
    }
    manifest: dict[str, Any] = {
        "$schema": MANIFEST_SCHEMA_URL,
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "evidence_id": "",
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": generated_at,
        "runtime_versions": _runtime_versions(),
        "generator_source_inventory": _generator_source_inventory(repository_root),
        "schema_bindings": {
            "manifest": manifest_schema_record,
            "case": case_schema_record,
        },
        "parents": {
            "phase2a3": {
                "artifact_id": p2a3_manifest["package_id"],
                "manifest": _external_artifact(p2a3_root / "manifest.json", repository_root),
                "checksum_file": _external_artifact(
                    p2a3_root / "CHECKSUMS.sha256", repository_root
                ),
                "case_count": 60,
                "immutable_input": True,
            },
            "phase2a4": {
                "artifact_id": p2a4_manifest["evidence_id"],
                "manifest": _external_artifact(p2a4_root / "manifest.json", repository_root),
                "checksum_file": _external_artifact(
                    p2a4_root / "CHECKSUMS.sha256", repository_root
                ),
                "case_count": 60,
                "immutable_input": True,
            },
        },
        "candidate_registry": {
            "registry_id": registry["registry_id"],
            "registry_version": registry["registry_version"],
            "artifact": _external_artifact(registry_path, repository_root),
            "fixed_before_case_outcomes": True,
        },
        "mapbiomas_context": {
            "artifact_id": _context_artifact_id(context_manifest),
            "manifest": _external_artifact(context_manifest_path, repository_root),
            "crops": crop_bindings,
        },
        "case_population": {
            "case_count": 60,
            "source_sample": _external_artifact(
                p2a3_root / "sampling/sample.geojson", repository_root
            ),
            "population_snapshot_id": p2a3_manifest["population_snapshot_id"],
            "original_case_order_sha256": _canonical_sha256(original_sample_ids),
            "original_geometry_order_sha256": _canonical_sha256(geometry_hashes),
            "preserved_without_replacement": True,
            "population_wide_geometry_available": False,
            "population_wide_outcomes_computed": False,
            "gap": (
                "Geometry is retained for the exact 60 selected cases only; nonselected "
                "population units cannot be reconstructed and no population-wide Phase 2A.5 "
                "outcome totals are computed."
            ),
        },
        "candidate_families": {
            "mapbiomas": list(MAPBIOMAS_CANDIDATES),
            "contextual_signature": list(SIGNATURE_CANDIDATES),
        },
        "cases": descriptors,
        "counts": {
            "case_count": 60,
            **status_counts,
            "raw_detection_count": 60,
        },
        "source_limitations": list(SOURCE_LIMITATIONS),
        "claims": MANIFEST_CLAIMS,
        "artifact_inventory_rule": "all files except manifest.json and CHECKSUMS.sha256",
        "artifact_inventory": [],
        "checksum_file": "CHECKSUMS.sha256",
    }
    manifest["artifact_inventory"] = _actual_inventory(output_root)
    manifest["evidence_id"] = "p2a5-context-evidence-v1-" + _canonical_sha256(
        _manifest_identity_input(manifest)
    )
    manifest_schema = _load_json(manifest_schema_path)
    _validate_schema(manifest, manifest_schema, "Phase 2A.5 evidence manifest")
    _write_json(output_root / "manifest.json", manifest)
    _write_checksum_inventory(output_root)
    return validate_phase2a5_evidence_artifact(
        output_root,
        parent_phase2a3_dir=p2a3_root,
        parent_phase2a4_dir=p2a4_root,
        candidate_registry_path=registry_path,
        context_artifact_dir=context_root,
        repository_root=repository_root,
    )


def build_phase2a5_evidence(config: Phase2A5EvidenceConfig) -> dict[str, Any]:
    """Build in sibling staging and atomically expose only validated evidence."""
    # Keep the destination lexical for the same reason as the in-place guard.
    target = Path(config.output_dir).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _acquire_build_lock(target)
    staging_container: Path | None = None
    try:
        if os.path.lexists(target):
            raise Phase2A5EvidenceError(
                f"output already exists; refusing to replace audit evidence: {target}"
            )
        staging_container = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)
        )
        staging = staging_container / "artifact"
        staging_config = Phase2A5EvidenceConfig(
            output_dir=staging,
            parent_phase2a3_dir=config.parent_phase2a3_dir,
            parent_phase2a4_dir=config.parent_phase2a4_dir,
            candidate_registry_path=config.candidate_registry_path,
            context_artifact_dir=config.context_artifact_dir,
            generated_at=config.generated_at,
            repository_root=config.repository_root,
        )
        validated = _build_phase2a5_evidence_in_place(staging_config)
        _publish_directory_no_clobber(staging, target)
        return validated
    finally:
        if staging_container is not None:
            shutil.rmtree(staging_container, ignore_errors=True)
        _release_build_lock(lock_path)


def _verify_inventory(root: Path, manifest: Mapping[str, Any]) -> None:
    expected = manifest["artifact_inventory"]
    actual = _actual_inventory(root)
    if actual != expected:
        raise Phase2A5EvidenceError("artifact inventory does not match exact files/checksums")
    _verify_checksum_inventory(root)


def _compare_expected_tree(expected_root: Path, actual_root: Path, prefix: str) -> None:
    expected_files = sorted(
        path.relative_to(expected_root).as_posix()
        for path in expected_root.rglob("*")
        if path.is_file()
    )
    actual_base = actual_root / prefix
    actual_files = sorted(
        f"{prefix}/{path.relative_to(actual_base).as_posix()}"
        for path in actual_base.rglob("*")
        if path.is_file()
    )
    expected_prefixed = [f"{prefix}/{value}" for value in expected_files]
    if actual_files != expected_prefixed:
        raise Phase2A5EvidenceError(f"case artifact file set differs for {prefix}")
    for relative in expected_files:
        expected_path = expected_root / relative
        actual_path = actual_base / relative
        if _sha256_file(expected_path) != _sha256_file(actual_path):
            raise Phase2A5EvidenceError(f"case artifact replay mismatch: {prefix}/{relative}")


def validate_phase2a5_evidence_artifact(
    evidence_dir: Path,
    *,
    parent_phase2a3_dir: Path | None = None,
    parent_phase2a4_dir: Path | None = None,
    candidate_registry_path: Path | None = None,
    context_artifact_dir: Path | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Deeply replay all cases, arrays, panels, provenance, and checksums."""
    root = Path(evidence_dir).resolve()
    if not root.is_dir():
        raise Phase2A5EvidenceError(f"evidence directory does not exist: {root}")
    repo = (
        Path(repository_root).resolve()
        if repository_root
        else Path(__file__).resolve().parents[2]
    )
    p2a3_root = (
        Path(parent_phase2a3_dir).resolve()
        if parent_phase2a3_dir
        else repo / "data/validation/phase2a3-pilot-v1"
    )
    p2a4_root = (
        Path(parent_phase2a4_dir).resolve()
        if parent_phase2a4_dir
        else repo / "data/validation/phase2a4-candidate-evidence-v1"
    )
    registry_path = (
        Path(candidate_registry_path).resolve()
        if candidate_registry_path
        else repo / "config/phase2a5_context_candidates_v1.json"
    )
    context_root = (
        Path(context_artifact_dir).resolve()
        if context_artifact_dir
        else repo / "data/validation/phase2a5-context-v1"
    )
    manifest = _load_json(root / "manifest.json")
    manifest_schema_path = root / "schemas/phase2a5-context-evidence-manifest-v1.schema.json"
    case_schema_path = root / "schemas/phase2a5-context-evidence-case-v1.schema.json"
    manifest_schema = _load_json(manifest_schema_path)
    case_schema = _load_json(case_schema_path)
    _validate_schema(manifest, manifest_schema, "Phase 2A.5 evidence manifest")
    _verify_inventory(root, manifest)
    canonical_schema_root = repo / "docs/contracts/phase2a/schemas"
    canonical_schema_paths = {
        "manifest": canonical_schema_root
        / "phase2a5-context-evidence-manifest-v1.schema.json",
        "case": canonical_schema_root / "phase2a5-context-evidence-case-v1.schema.json",
    }
    packaged_schema_paths = {"manifest": manifest_schema_path, "case": case_schema_path}
    for label, canonical_path in canonical_schema_paths.items():
        if not canonical_path.is_file() or (
            canonical_path.read_bytes() != packaged_schema_paths[label].read_bytes()
        ):
            raise Phase2A5EvidenceError(
                f"packaged {label} schema differs from the canonical repository schema"
            )
    expected_schema_bindings = {
        "manifest": _artifact(manifest_schema_path, root),
        "case": _artifact(case_schema_path, root),
    }
    if manifest["schema_bindings"] != expected_schema_bindings:
        raise Phase2A5EvidenceError("schema bindings differ from packaged schemas")
    if manifest["generator_source_inventory"] != _generator_source_inventory(repo):
        raise Phase2A5EvidenceError("generator source inventory changed")
    if manifest["runtime_versions"] != _runtime_versions():
        raise Phase2A5EvidenceError("runtime version binding changed")
    p2a3_manifest, p2a4_manifest, registry, context_manifest = _validate_frozen_inputs(
        repository_root=repo,
        p2a3_root=p2a3_root,
        p2a4_root=p2a4_root,
        registry_path=registry_path,
        context_root=context_root,
    )
    expected_parents = {
        "phase2a3": {
            "artifact_id": p2a3_manifest["package_id"],
            "manifest": _external_artifact(p2a3_root / "manifest.json", repo),
            "checksum_file": _external_artifact(p2a3_root / "CHECKSUMS.sha256", repo),
            "case_count": 60,
            "immutable_input": True,
        },
        "phase2a4": {
            "artifact_id": p2a4_manifest["evidence_id"],
            "manifest": _external_artifact(p2a4_root / "manifest.json", repo),
            "checksum_file": _external_artifact(p2a4_root / "CHECKSUMS.sha256", repo),
            "case_count": 60,
            "immutable_input": True,
        },
    }
    if manifest["parents"] != expected_parents:
        raise Phase2A5EvidenceError("parent artifact provenance bindings changed")
    if manifest["candidate_registry"]["artifact"] != _external_artifact(registry_path, repo):
        raise Phase2A5EvidenceError("candidate registry binding changed")
    context_manifest_path = context_root / "manifest.json"
    if manifest["mapbiomas_context"]["manifest"] != _external_artifact(
        context_manifest_path, repo
    ):
        raise Phase2A5EvidenceError("MapBiomas context manifest binding changed")
    if manifest["mapbiomas_context"]["artifact_id"] != _context_artifact_id(
        context_manifest
    ):
        raise Phase2A5EvidenceError("MapBiomas context artifact identity changed")
    crop_paths: dict[str, Path] = {}
    crop_bindings: dict[str, dict[str, Any]] = {}
    for collection_key in (COL3_KEY, COL10_KEY):
        path, binding = _crop_record(collection_key, registry, context_manifest, repo)
        crop_paths[collection_key] = path
        crop_bindings[collection_key] = binding
    if manifest["mapbiomas_context"]["crops"] != crop_bindings:
        raise Phase2A5EvidenceError("regional crop provenance binding changed")
    features, crosswalk, p2a4_cases = _input_case_maps(p2a3_root, p2a4_manifest)
    descriptors = manifest["cases"]
    if descriptors != sorted(descriptors, key=lambda value: value["blind_case_id"]):
        raise Phase2A5EvidenceError("manifest cases are not sorted by blind_case_id")
    if len({value["sample_id"] for value in descriptors}) != 60 or len(
        {value["blind_case_id"] for value in descriptors}
    ) != 60:
        raise Phase2A5EvidenceError("manifest case IDs are not exactly unique")
    descriptors_by_sample = {value["sample_id"]: value for value in descriptors}
    expected_descriptors: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="phase2a5-evidence-replay-") as temporary:
        replay_root = Path(temporary)
        for source_order_index, feature in enumerate(features):
            sample_id = feature["properties"]["sample_id"]
            actual_descriptor = descriptors_by_sample.get(sample_id)
            if actual_descriptor is None:
                raise Phase2A5EvidenceError(f"manifest omits frozen case {sample_id}")
            actual_case_path = _safe_artifact_path(root, actual_descriptor["record"]["path"])
            _verify_record(actual_case_path, actual_descriptor["record"])
            actual_case = _load_json(actual_case_path)
            _validate_schema(actual_case, case_schema, f"Phase 2A.5 case {sample_id}")
            expected_case, expected_descriptor = _build_case(
                output_root=replay_root,
                repository_root=repo,
                p2a3_root=p2a3_root,
                p2a4_root=p2a4_root,
                registry_path=registry_path,
                context_manifest_path=context_manifest_path,
                registry=registry,
                crop_paths=crop_paths,
                crop_bindings=crop_bindings,
                feature=feature,
                source_order_index=source_order_index,
                crosswalk=crosswalk[sample_id],
                p2a4_descriptor=p2a4_cases[sample_id],
            )
            if actual_case != expected_case:
                raise Phase2A5EvidenceError(f"case semantic replay differs: {sample_id}")
            if actual_descriptor != expected_descriptor:
                raise Phase2A5EvidenceError(f"case record checksum/summary differs: {sample_id}")
            _compare_expected_tree(
                replay_root / "cases" / sample_id,
                root,
                f"cases/{sample_id}",
            )
            expected_descriptors.append(expected_descriptor)
    expected_descriptors.sort(key=lambda value: value["blind_case_id"])
    if descriptors != expected_descriptors:
        raise Phase2A5EvidenceError("manifest case descriptor order/content changed")
    original_ids = [feature["properties"]["sample_id"] for feature in features]
    geometry_hashes = [_canonical_sha256(feature["geometry"]) for feature in features]
    population = manifest["case_population"]
    if population["population_snapshot_id"] != p2a3_manifest["population_snapshot_id"]:
        raise Phase2A5EvidenceError("Phase 2A.3 population snapshot binding changed")
    if population["original_case_order_sha256"] != _canonical_sha256(original_ids):
        raise Phase2A5EvidenceError("original Phase 2A.3 case order binding changed")
    if population["original_geometry_order_sha256"] != _canonical_sha256(geometry_hashes):
        raise Phase2A5EvidenceError("original geometry/order binding changed")
    if population["source_sample"] != _external_artifact(
        p2a3_root / "sampling/sample.geojson", repo
    ):
        raise Phase2A5EvidenceError("source sample binding changed")
    if manifest["source_limitations"] != list(SOURCE_LIMITATIONS):
        raise Phase2A5EvidenceError("source limitations changed")
    counts = {
        status: sum(value["status"] == status for value in descriptors)
        for status in ("available", "partial", "unreviewable")
    }
    if manifest["counts"] != {
        "case_count": 60,
        **counts,
        "raw_detection_count": 60,
    }:
        raise Phase2A5EvidenceError("case counts do not reconcile")
    expected_evidence_id = "p2a5-context-evidence-v1-" + _canonical_sha256(
        _manifest_identity_input(manifest)
    )
    if manifest["evidence_id"] != expected_evidence_id:
        raise Phase2A5EvidenceError("evidence identity does not replay")
    if manifest["claims"] != MANIFEST_CLAIMS:
        raise Phase2A5EvidenceError("manifest claims changed")
    return manifest
