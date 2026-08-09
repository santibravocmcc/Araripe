"""Build and deeply validate the local Phase 2A.4 review derivative.

The accepted Phase 2A.3 package is immutable.  This module derives reviewer
packages from it, adds only the three Phase 2A.4 method families, and keeps all
true candidate/cell mappings and raw inputs below ``coordinator/``.  It does
not select or activate a method, infer canonical scientific identities, replay
detections, or write outside the requested local output directory.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import mimetypes
import os
import platform
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from src.detection.baseline_manifest import sha256_file
from src.detection.identity import (
    canonical_geometry_sha256,
    canonical_json_bytes,
    canonical_sha256,
    identity_sha256,
)
from src.validation.package import _html_document, _runtime_versions, write_canonical_json
from src.validation.phase2a4_rainfall import (
    RainfallArtifactError,
    validate_rainfall_reference_artifact,
)
from src.validation.phase2a4_evidence import (
    _ASSET_HREF_RESOLUTION_POLICY,
    _resolve_provider_asset_hrefs,
    validate_phase2a4_evidence_artifact,
)
from src.validation.validator import validate_validation_package


SCHEMA_VERSION = "1.0.0"
PACKAGE_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a4-derivative-manifest-v1.schema.json"
)
EVIDENCE_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a4-method-evidence-v1.schema.json"
)
REVIEW_EXPORT_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a4-review-export-v1.schema.json"
)
PACKAGE_ID_PREFIX = "p2a4-derivative-package-v1-"
EVIDENCE_ID_PREFIX = "p2a4-method-evidence-v1-"
BLIND_OPTION_PREFIX = "p2a4-blind-option-v1-"
BLIND_CELL_PREFIX = "p2a4-blind-cell-v1-"

ACCEPTED_PARENT_PACKAGE_ID = (
    "p2a3-pilot-package-v1-"
    "050d2b944679385e1a3e3bf209fbe2f3a6a3892a4016ef2a24c1f96e281bf5c8"
)
ACCEPTED_POPULATION_ID = (
    "p2a3-population-v1-"
    "100c4e3e2f293235211d519392323c6ee0e6f2b88928d9fc8a74a71b52d80c6c"
)
ACCEPTED_PARENT_MANIFEST_SHA256 = (
    "4b78167930fcb7a928b40d50ae1d54675e4cca47a10857bcbf28db803c18946b"
)
ACCEPTED_BASELINE_MANIFEST_SHA256 = (
    "15a1ed3cea7c804d18d2c82c86a7b9a030687fedb01b315d543965b1f26f0a82"
)
ACCEPTED_EXTENT_GEOMETRY_SHA256 = (
    "b4986ef80d8a0d6e65bbb41b575dbd952c010415bf3aee93a88412b3b657e8c7"
)
REGISTRY_ID = "araripe-phase2a4-candidates-v1"
REGISTRY_RELATIVE_PATH = "config/phase2a4_candidates_v1.json"
METHOD_FAMILIES = ("cloud_mask", "daily_composition", "drought_adjustment")
PRESERVED_METHOD_FAMILIES = ("mapbiomas", "contextual_signature")
ASSET_KEYS = ("blue", "red", "nir", "nir08", "swir16", "swir22", "scl", "cloud")
REVIEWER_SLOTS = ("reviewer-a", "reviewer-b")
CHECKSUM_LINE = re.compile(r"^(?P<sha>[0-9a-f]{64})  (?P<path>[^\n]+)$")
FORBIDDEN_REVIEWER_PREFIXES = ("p2a3-sample-v1-", "p2a4-cell-v1-")

REFERENCE_GRID = {
    "crs": "EPSG:32724",
    "width": 10773,
    "height": 4999,
    "transform": [20.0, 0.0, 290080.0, 0.0, -20.0, 9231780.0],
    "bounds": [290080.0, 9131800.0, 505540.0, 9231780.0],
    "pixel_size_m": 20,
}
COVERAGE_CONTRACT = {
    "denominator_pixel_rule": "all_pixels_in_fixed_grid_aligned_case_window",
    "valid_pixel_rule": (
        "finite_required_reflectance_after_candidate_mask_and_composition_"
        "and_at_least_one_configured_index_with_finite_current_baseline_"
        "mean_and_std"
    ),
    "valid_coverage_formula": "valid_pixel_count/case_window_pixel_count",
    "minimum_valid_coverage_fraction": 0.2,
}


class Phase2A4PackageError(ValueError):
    """Raised when construction would violate a Phase 2A.4 boundary."""


class Phase2A4PackageIntegrityError(ValueError):
    """Raised when a derivative package fails deep reconciliation."""


def _load_json(path: Path, *, error_type: type[ValueError] = Phase2A4PackageError) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise error_type(f"cannot parse {path}: {exc}") from exc


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _method_artifact(path: Path, root: Path, *, role: str) -> dict[str, Any]:
    record = _artifact(path, root)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {**record, "media_type": media_type, "role": role}


def _safe_path(root: Path, relative: str, *, error_type: type[ValueError]) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise error_type(f"unsafe artifact path: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise error_type(f"artifact path escapes root: {relative}") from exc
    return resolved


def _validate_schema(value: Any, schema: Mapping[str, Any], label: str) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise Phase2A4PackageIntegrityError(
            f"{label} schema violation at {location}: {first.message}"
        )


def _parse_timestamp(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Phase2A4PackageError(f"{label} must be an RFC 3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise Phase2A4PackageError(f"{label} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise Phase2A4PackageError(f"{label} must include an offset")
    return value


def _verify_checksum_artifact(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    error_type: type[ValueError],
) -> None:
    inventory = manifest.get("artifact_inventory")
    if not isinstance(inventory, list) or not inventory:
        raise error_type("artifact inventory is missing")
    paths = [item.get("path") for item in inventory]
    if any(not isinstance(path, str) for path in paths) or len(paths) != len(set(paths)):
        raise error_type("artifact inventory paths are invalid or duplicated")
    actual: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise error_type(f"symlink is forbidden: {path}")
        if path.is_file():
            actual[path.relative_to(root).as_posix()] = path
    expected = set(paths) | {"manifest.json", "CHECKSUMS.sha256"}
    if set(actual) != expected:
        raise error_type(
            "artifact inventory mismatch; "
            f"missing={sorted(expected - set(actual))}, "
            f"unlisted={sorted(set(actual) - expected)}"
        )
    for item in inventory:
        path = _safe_path(root, item["path"], error_type=error_type)
        if (
            not path.is_file()
            or path.stat().st_size != item.get("bytes")
            or sha256_file(path) != item.get("sha256")
        ):
            raise error_type(f"artifact checksum mismatch: {item['path']}")
    recorded: dict[str, str] = {}
    try:
        lines = (root / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise error_type(f"cannot read CHECKSUMS.sha256: {exc}") from exc
    for number, line in enumerate(lines, start=1):
        match = CHECKSUM_LINE.fullmatch(line)
        if match is None or match.group("path") in recorded:
            raise error_type(f"invalid or duplicate checksum line {number}")
        recorded[match.group("path")] = match.group("sha")
    checksum_paths = expected - {"CHECKSUMS.sha256"}
    if set(recorded) != checksum_paths:
        raise error_type("checksum-file inventory does not reconcile")
    for relative, digest in recorded.items():
        if sha256_file(_safe_path(root, relative, error_type=error_type)) != digest:
            raise error_type(f"checksum-file mismatch: {relative}")


def _write_checksums(root: Path, inventory: Sequence[Mapping[str, Any]]) -> None:
    entries = [
        {"path": "manifest.json", "sha256": sha256_file(root / "manifest.json")},
        *({"path": item["path"], "sha256": item["sha256"]} for item in inventory),
    ]
    payload = "".join(
        f"{item['sha256']}  {item['path']}\n"
        for item in sorted(entries, key=lambda item: item["path"])
    )
    (root / "CHECKSUMS.sha256").write_text(payload, encoding="utf-8", newline="\n")


def _inventory(root: Path) -> list[dict[str, Any]]:
    excluded = {"manifest.json", "CHECKSUMS.sha256"}
    return [
        _artifact(path, root)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.relative_to(root).as_posix() not in excluded
    ]


def _inventory_digest(items: Iterable[Mapping[str, Any]]) -> str:
    normalized = [
        {"path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
        for item in sorted(items, key=lambda item: item["path"])
    ]
    return canonical_sha256(normalized)


def _parent_index(parent_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = _load_json(parent_root / "manifest.json")
    if (
        manifest.get("package_id") != ACCEPTED_PARENT_PACKAGE_ID
        or manifest.get("population_snapshot_id") != ACCEPTED_POPULATION_ID
        or sha256_file(parent_root / "manifest.json") != ACCEPTED_PARENT_MANIFEST_SHA256
    ):
        raise Phase2A4PackageError("Phase 2A.3 parent is not the accepted frozen package")
    crosswalk = _load_json(parent_root / "coordinator" / "crosswalk.json")
    mappings = crosswalk.get("mappings")
    if not isinstance(mappings, list) or len(mappings) != 60:
        raise Phase2A4PackageError("Phase 2A.3 crosswalk must contain exactly 60 cases")
    by_blind: dict[str, dict[str, Any]] = {}
    for mapping in mappings:
        blind_id = mapping.get("blind_case_id")
        sample_id = mapping.get("sample_id")
        if not isinstance(blind_id, str) or not isinstance(sample_id, str):
            raise Phase2A4PackageError("invalid Phase 2A.3 crosswalk mapping")
        case = _load_json(parent_root / "coordinator" / "cases" / f"{sample_id}.json")
        reviewer_case = case.get("reviewer_case")
        if not isinstance(reviewer_case, dict) or reviewer_case.get("blind_case_id") != blind_id:
            raise Phase2A4PackageError(f"parent case does not reconcile: {blind_id}")
        _, geometry_sha256 = canonical_geometry_sha256(reviewer_case["target_geometry"])
        by_blind[blind_id] = {
            **mapping,
            "target_date": reviewer_case["target_date"],
            "target_geometry_sha256": geometry_sha256,
            "reviewer_case": reviewer_case,
        }
    if len(by_blind) != 60:
        raise Phase2A4PackageError("duplicate Phase 2A.3 blind case ID")
    reviewer_a = _load_json(parent_root / "reviewer-a" / "assignment.json")
    reviewer_b = _load_json(parent_root / "reviewer-b" / "assignment.json")
    if set(reviewer_a.get("blind_case_ids", [])) != set(by_blind):
        raise Phase2A4PackageError("reviewer-a assignment does not cover frozen cases")
    if len(reviewer_b.get("blind_case_ids", [])) != 12:
        raise Phase2A4PackageError("reviewer-b assignment is not the frozen 12-case overlap")
    return manifest, by_blind


def _registry_index(registry: Mapping[str, Any]) -> tuple[dict[str, tuple[str, str]], dict[str, dict[str, str]]]:
    if registry.get("registry_id") != REGISTRY_ID or registry.get("registry_version") != SCHEMA_VERSION:
        raise Phase2A4PackageError("candidate registry identity mismatch")
    families = registry.get("families")
    if not isinstance(families, dict) or set(families) != set(METHOD_FAMILIES):
        raise Phase2A4PackageError("candidate registry method families mismatch")
    candidates: dict[str, tuple[str, str]] = {}
    for family in METHOD_FAMILIES:
        ids = families[family].get("candidate_ids")
        if not isinstance(ids, list) or len(ids) != 2 or len(set(ids)) != 2:
            raise Phase2A4PackageError(f"{family} must define exactly two candidates")
        candidates[family] = (ids[0], ids[1])
    cells = registry.get("factorial_design", {}).get("treatment_cells")
    if not isinstance(cells, list) or len(cells) != 8:
        raise Phase2A4PackageError("registry must contain eight factorial cells")
    cell_index: dict[str, dict[str, str]] = {}
    observed: set[tuple[str, str, str]] = set()
    for cell in cells:
        cell_id = cell.get("cell_id")
        factors = {family: cell.get(family) for family in METHOD_FAMILIES}
        if not isinstance(cell_id, str) or cell_id in cell_index:
            raise Phase2A4PackageError("duplicate or invalid registry cell ID")
        if any(factors[family] not in candidates[family] for family in METHOD_FAMILIES):
            raise Phase2A4PackageError(f"registry cell references unknown candidate: {cell_id}")
        signature = tuple(factors[family] for family in METHOD_FAMILIES)
        if signature in observed:
            raise Phase2A4PackageError("registry factorial signatures are not unique")
        observed.add(signature)
        cell_index[cell_id] = factors
    if len(observed) != 8:
        raise Phase2A4PackageError("registry is not a complete 2x2x2 design")
    return candidates, cell_index


def deterministic_blind_mapping(
    blind_case_ids: Sequence[str],
    candidate_ids: Mapping[str, Sequence[str]],
    *,
    blinding_key: str,
) -> dict[str, dict[str, dict[str, str]]]:
    """Return an exact 30/30 deterministic A/B map for every family.

    The evidence checksum is the coordinator-only key.  Reviewer packages do
    not contain it, so deterministic identifiers are not an unkeyed lookup of
    the public registry candidate IDs.
    """
    ids = sorted(blind_case_ids)
    if len(ids) != 60 or len(set(ids)) != 60:
        raise Phase2A4PackageError("balanced blinding requires exactly 60 unique cases")
    if not re.fullmatch(r"[0-9a-f]{64}", blinding_key):
        raise Phase2A4PackageError("blinding key must be a SHA-256 digest")
    result: dict[str, dict[str, dict[str, str]]] = {blind: {} for blind in ids}
    for family in METHOD_FAMILIES:
        pair = tuple(candidate_ids[family])
        if len(pair) != 2 or len(set(pair)) != 2:
            raise Phase2A4PackageError(f"{family} does not have two candidates")
        ranked = sorted(
            ids,
            key=lambda blind: identity_sha256(
                "phase2a4-balanced-option-order-v1", blinding_key, family, blind
            ),
        )
        first_is_a = set(ranked[:30])
        for blind in ids:
            a, b = pair if blind in first_is_a else (pair[1], pair[0])
            result[blind][family] = {"A": a, "B": b}
    return result


def _blind_option_id(blinding_key: str, blind_id: str, family: str, candidate_id: str) -> str:
    return BLIND_OPTION_PREFIX + identity_sha256(
        "phase2a4-blind-option-v1", blinding_key, blind_id, family, candidate_id
    )[:24]


def _blind_cell_id(blinding_key: str, blind_id: str, cell_id: str) -> str:
    return BLIND_CELL_PREFIX + identity_sha256(
        "phase2a4-blind-cell-v1", blinding_key, blind_id, cell_id
    )[:24]


def _paired_mapping_key(
    blind_id: str,
    family: str,
    factors: Mapping[str, str],
) -> str:
    other_factors = {
        name: factors[name]
        for name in METHOD_FAMILIES
        if name != family
    }
    return identity_sha256(
        "phase2a4-paired-stratum-v1",
        blind_id,
        family,
        canonical_sha256(other_factors),
    )


def _load_evidence(
    evidence_root: Path,
    *,
    parent_by_blind: Mapping[str, Mapping[str, Any]],
    registry_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    manifest = _load_json(evidence_root / "manifest.json")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("artifact_type") != "phase2a4_candidate_evidence":
        raise Phase2A4PackageError("candidate evidence manifest identity mismatch")
    _verify_checksum_artifact(evidence_root, manifest, error_type=Phase2A4PackageError)
    parent = manifest.get("phase2a3", {})
    if (
        parent.get("package_id") != ACCEPTED_PARENT_PACKAGE_ID
        or parent.get("population_snapshot_id") != ACCEPTED_POPULATION_ID
        or parent.get("manifest_sha256") != ACCEPTED_PARENT_MANIFEST_SHA256
        or not re.fullmatch(r"[0-9a-f]{64}", str(parent.get("checksums_sha256", "")))
    ):
        raise Phase2A4PackageError("candidate evidence parent binding mismatch")
    registry_binding = manifest.get("candidate_registry", {})
    if (
        registry_binding.get("registry_id") != REGISTRY_ID
        or registry_binding.get("sha256") != sha256_file(registry_path)
    ):
        raise Phase2A4PackageError("candidate evidence registry binding mismatch")
    descriptors = manifest.get("cases")
    if not isinstance(descriptors, list) or len(descriptors) != 60:
        raise Phase2A4PackageError("candidate evidence must retain exactly 60 cases")
    records: dict[str, dict[str, Any]] = {}
    for descriptor in descriptors:
        blind = descriptor.get("blind_case_id")
        sample = descriptor.get("sample_id")
        if blind not in parent_by_blind or parent_by_blind[blind]["sample_id"] != sample:
            raise Phase2A4PackageError("candidate evidence case mapping mismatch")
        expected = parent_by_blind[blind]
        if descriptor.get("target_date") != expected["target_date"]:
            raise Phase2A4PackageError(f"candidate evidence date mismatch: {blind}")
        record_artifact = descriptor.get("record")
        if not isinstance(record_artifact, dict):
            raise Phase2A4PackageError(f"candidate evidence record missing: {blind}")
        record_path = _safe_path(evidence_root, record_artifact["path"], error_type=Phase2A4PackageError)
        if (
            not record_path.is_file()
            or record_path.stat().st_size != record_artifact.get("bytes")
            or sha256_file(record_path) != record_artifact.get("sha256")
        ):
            raise Phase2A4PackageError(f"candidate evidence record checksum mismatch: {blind}")
        record = _load_json(record_path)
        if (
            record.get("sample_id") != sample
            or record.get("blind_case_id") != blind
            or record.get("target_date") != expected["target_date"]
        ):
            raise Phase2A4PackageError(f"candidate evidence record identity mismatch: {blind}")
        if blind in records:
            raise Phase2A4PackageError(f"duplicate candidate evidence blind ID: {blind}")
        records[blind] = record
    if set(records) != set(parent_by_blind):
        raise Phase2A4PackageError("candidate evidence silently replaced or omitted a frozen case")
    return manifest, records, sha256_file(evidence_root / "CHECKSUMS.sha256")


def _copy_verified_artifact(
    source_root: Path,
    record: Mapping[str, Any],
    destination: Path,
) -> None:
    source = _safe_path(source_root, str(record.get("path")), error_type=Phase2A4PackageError)
    if (
        not source.is_file()
        or source.stat().st_size != record.get("bytes")
        or sha256_file(source) != record.get("sha256")
    ):
        raise Phase2A4PackageError(f"source artifact does not reconcile: {record.get('path')}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _panel_role(family: str) -> str:
    return {
        "cloud_mask": "cloud_mask_panel",
        "daily_composition": "daily_composition_panel",
        "drought_adjustment": "drought_adjustment_panel",
    }[family]


def _normalize_source_binding(record: Mapping[str, Any]) -> dict[str, Any]:
    source_query = record.get("source_query")
    source_scenes = record.get("source_scenes")
    grid = record.get("grid")
    drought = record.get("drought")
    if not all(isinstance(value, dict) for value in (source_query, grid, drought)) or not isinstance(source_scenes, list):
        raise Phase2A4PackageError("candidate case lacks source query/grid/drought provenance")
    query_input = source_query.get("query", source_query)
    query_fields = (
        "target_date",
        "spatial_filter",
        "temporal_filter",
        "eo_cloud_cover_lt",
        "intersects",
        "datetime",
        "result_limit",
        "pagination_policy",
        "intersects_geometry_sha256",
        "canonical_payload_sha256",
    )
    if not isinstance(query_input, Mapping) or any(field not in query_input for field in query_fields):
        raise Phase2A4PackageError("candidate case lacks the complete STAC query fingerprint")
    query = {field: copy.deepcopy(query_input[field]) for field in query_fields}
    scene_ids = [scene.get("item_id") for scene in source_scenes]
    if any(not isinstance(item, str) or not item for item in scene_ids) or len(scene_ids) != len(set(scene_ids)):
        raise Phase2A4PackageError("candidate case source scene IDs are invalid")
    reference_grid = grid.get("reference_grid", REFERENCE_GRID)
    case_window = copy.deepcopy(grid.get("case_window", grid))
    case_window.pop("reference_grid", None)
    case_window.pop("coverage_contract", None)
    supplied_window_hash = case_window.pop("window_definition_sha256", None)
    expected_window_hash = canonical_sha256(case_window)
    if supplied_window_hash not in (None, expected_window_hash):
        raise Phase2A4PackageError("case-window definition hash mismatch")
    case_window["window_definition_sha256"] = expected_window_hash
    rainfall = copy.deepcopy(drought.get("rainfall_reference", drought))
    return {
        "monitoring_extent_id": "araripe-implementation-rectangle-v1",
        "monitoring_extent_geometry_sha256": ACCEPTED_EXTENT_GEOMETRY_SHA256,
        "baseline_version": "1.0.0",
        "baseline_manifest_sha256": ACCEPTED_BASELINE_MANIFEST_SHA256,
        "catalog": "Element84 Earth Search",
        "stac_endpoint": "https://earth-search.aws.element84.com/v1",
        "collection_id": "sentinel-2-l2a",
        "catalog_accessed_at": source_query.get("catalog_accessed_at"),
        "query": query,
        "source_scene_ids_sha256": canonical_sha256(scene_ids),
        "source_scenes": copy.deepcopy(source_scenes),
        "reference_grid": copy.deepcopy(reference_grid),
        "case_window": case_window,
        "coverage_contract": copy.deepcopy(grid.get("coverage_contract", COVERAGE_CONTRACT)),
        "rainfall_reference": rainfall,
    }


def _cell_records(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    cells = record.get("factorial_cells")
    if not isinstance(cells, list):
        raise Phase2A4PackageError("candidate case factorial_cells must be an array")
    result: dict[str, dict[str, Any]] = {}
    for cell in cells:
        if not isinstance(cell, dict) or not isinstance(cell.get("cell_id"), str):
            raise Phase2A4PackageError("candidate case contains an invalid factorial cell")
        if cell["cell_id"] in result:
            raise Phase2A4PackageError("candidate case contains a duplicate factorial cell")
        result[cell["cell_id"]] = cell
    return result


def _panel_records(record: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    panels = record.get("candidate_panels")
    if not isinstance(panels, dict):
        raise Phase2A4PackageError("candidate case lacks candidate_panels")
    return panels  # validated against the registry while constructing each case


def _reviewer_protocol() -> str:
    return (
        "# Phase 2A.4 blinded method comparison\n\n"
        "Complete and save the primary change assessment before revealing method "
        "panels. The primary fields are then locked. Compare A and B only; neither "
        "label identifies an accepted method. Missing evidence remains missing and "
        "must not be interpreted as no change. No option is selected or activated "
        "by this package. Return only the exported review JSON to the coordinator.\n"
    )


def _comparison_availability(
    option_panels: Sequence[Mapping[str, Any]],
    candidate_cells: Sequence[Mapping[str, Any]],
) -> tuple[str, str | None]:
    panel_available = [
        panel.get("status") in {"available", "partial"} and panel.get("path")
        for panel in option_panels
    ]
    cell_available = [cell.get("availability") == "available" for cell in candidate_cells]
    if all(panel_available) and all(cell_available):
        return "available", None
    if any(panel_available) or any(cell_available):
        return "partial", "One or more paired strata or panel artifacts are unavailable; retained without replacement."
    return "unreviewable", "Both blinded options lack reviewable evidence; case retained without replacement."


def _coverage_summary(cells: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(cell.get("availability") for cell in cells)
    return {
        "available_cell_count": counts["available"],
        "rejected_low_coverage_cell_count": counts["rejected_low_coverage"],
        "unavailable_cell_count": counts["unavailable"] + counts["error"],
    }


def _sidecar_payload_hash(sidecar: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(sidecar)
    payload["integrity"].pop("canonical_payload_sha256", None)
    return canonical_sha256(payload)


def _all_sidecar_artifacts(sidecar: Mapping[str, Any]) -> list[dict[str, Any]]:
    records: dict[tuple[str, str, int, str, str], dict[str, Any]] = {}
    rainfall = sidecar["source_binding"]["rainfall_reference"].get("artifact")
    candidates: list[Mapping[str, Any]] = []
    if rainfall is not None:
        candidates.append(rainfall)
    for cell in sidecar["factorial_results"]:
        candidates.extend(cell["artifacts"])
    for comparison in sidecar["comparisons"].values():
        candidates.extend(comparison["option_a"]["artifacts"])
        candidates.extend(comparison["option_b"]["artifacts"])
    for item in candidates:
        key = (item["path"], item["sha256"], item["bytes"], item["media_type"], item["role"])
        records[key] = dict(item)
    return [records[key] for key in sorted(records)]


def _build_case_material(
    *,
    package_root: Path,
    evidence_root: Path,
    record: Mapping[str, Any],
    parent_case: Mapping[str, Any],
    package_id: str,
    registry_artifact: Mapping[str, Any],
    candidate_ids: Mapping[str, tuple[str, str]],
    registry_cells: Mapping[str, Mapping[str, str]],
    labels: Mapping[str, Mapping[str, str]],
    blinding_key: str,
    overlap: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    blind = parent_case["blind_case_id"]
    cells = _cell_records(record)
    if set(cells) != set(registry_cells):
        raise Phase2A4PackageError(f"case {blind} does not retain all eight registry cells")
    for cell_id, factors in registry_cells.items():
        if cells[cell_id].get("candidates") != dict(factors):
            raise Phase2A4PackageError(
                f"case {blind} cell factors do not match the registry: {cell_id}"
            )
    panels = _panel_records(record)
    for family in METHOD_FAMILIES:
        if set(panels.get(family, {})) != set(candidate_ids[family]):
            raise Phase2A4PackageError(f"case {blind} panel candidates mismatch for {family}")

    reviewer_roots = [package_root / "reviewer-a"]
    if overlap:
        reviewer_roots.append(package_root / "reviewer-b")
    panel_artifacts: dict[str, dict[str, dict[str, Any] | None]] = {
        family: {} for family in METHOD_FAMILIES
    }
    mapping_families: dict[str, Any] = {}
    for family in METHOD_FAMILIES:
        mapping_families[family] = {}
        for label in ("A", "B"):
            candidate_id = labels[family][label]
            panel = panels[family][candidate_id]
            if not isinstance(panel, dict):
                raise Phase2A4PackageError(f"case {blind} has invalid {family}/{candidate_id} panel")
            status = panel.get("status")
            path_value = panel.get("path")
            artifact: dict[str, Any] | None = None
            if status in {"available", "partial"} and path_value is not None:
                if not isinstance(path_value, str):
                    raise Phase2A4PackageError(f"reviewable panel has no path: {blind}/{family}/{candidate_id}")
                suffix = Path(path_value).suffix.lower() or ".bin"
                relative = Path("method-evidence") / blind / family / f"{label}{suffix}"
                for reviewer_root in reviewer_roots:
                    _copy_verified_artifact(evidence_root, panel, reviewer_root / relative)
                artifact = _method_artifact(
                    package_root / "reviewer-a" / relative,
                    package_root / "reviewer-a",
                    role=_panel_role(family),
                )
            elif path_value is not None:
                raise Phase2A4PackageError(f"unreviewable panel must not name a path: {blind}/{family}/{candidate_id}")
            panel_artifacts[family][candidate_id] = artifact
            owned_cells = [
                cell_id for cell_id, factors in registry_cells.items() if factors[family] == candidate_id
            ]
            if panel.get("paired_cell_ids") != sorted(
                owned_cells,
                key=lambda cell_id: _paired_mapping_key(
                    blind, family, registry_cells[cell_id]
                ),
            ):
                raise Phase2A4PackageError(
                    f"case {blind} panel strata do not match the registry: {family}/{candidate_id}"
                )
            mapping_families[family][label] = {
                "candidate_id": candidate_id,
                "blind_option_id": _blind_option_id(blinding_key, blind, family, candidate_id),
                "blind_cell_ids": [
                    _blind_cell_id(blinding_key, blind, cell_id) for cell_id in owned_cells
                ],
                "source_panel": {
                    "status": status,
                    "reason": panel.get("reason"),
                    "path": path_value,
                    "sha256": panel.get("sha256"),
                },
            }

    source_binding = _normalize_source_binding(record)
    rainfall = source_binding["rainfall_reference"]
    if rainfall.get("status") == "available":
        rainfall_relative = Path("method-evidence") / blind / "rainfall-reference.json"
        rainfall_public = {
            key: rainfall.get(key)
            for key in (
                "status", "reason", "dataset_id", "source_kind", "official_cog_base_url",
                "official_cog_pattern", "aggregation_version", "coverage_denominator",
                "reference_start_month", "reference_end_month", "target_ending_month",
                "complete_reference_window_count", "artifact_id", "manifest_sha256", "plan_sha256",
                "full_upstream_cog_checksum_available", "checksum_scope_limitation",
            )
        }
        for reviewer_root in reviewer_roots:
            write_canonical_json(reviewer_root / rainfall_relative, rainfall_public)
        rainfall["artifact"] = _method_artifact(
            package_root / "reviewer-a" / rainfall_relative,
            package_root / "reviewer-a",
            role="rainfall_reference",
        )
    else:
        rainfall["artifact"] = None

    factorial_results: list[dict[str, Any]] = []
    factorial_mapping: list[dict[str, Any]] = []
    for cell_id, factors in registry_cells.items():
        raw = cells[cell_id]
        availability = raw.get("availability")
        reason = raw.get("unavailable_reason")
        if availability not in {
            "available",
            "rejected_low_coverage",
            "unavailable",
            "error",
        }:
            raise Phase2A4PackageError(f"invalid cell availability: {blind}/{cell_id}")
        artifacts = []
        for family in METHOD_FAMILIES:
            artifact = panel_artifacts[family][factors[family]]
            if artifact is not None and artifact not in artifacts:
                artifacts.append(artifact)
        if availability == "available" and not artifacts:
            raise Phase2A4PackageError(f"available cell has no reviewer evidence: {blind}/{cell_id}")
        drought_status = copy.deepcopy(raw.get("drought_status"))
        if not isinstance(drought_status, dict):
            raise Phase2A4PackageError(f"cell lacks drought status: {blind}/{cell_id}")
        expected_adjustment = {
            "disabled": 0.0,
            "drought": 0.5,
            "not_drought": 0.0,
            "unavailable": None,
        }.get(drought_status.get("status"), object())
        if drought_status.get("z_threshold_adjustment") != expected_adjustment:
            raise Phase2A4PackageError(f"cell drought adjustment is not the applied value: {blind}/{cell_id}")
        blind_cell = _blind_cell_id(blinding_key, blind, cell_id)
        factorial_results.append(
            {
                "blind_cell_id": blind_cell,
                "availability": availability,
                "unavailable_reason": reason,
                "ordered_source_scene_ids": copy.deepcopy(raw.get("ordered_source_scene_ids", [])),
                "contributing_scenes": copy.deepcopy(raw.get("contributing_scenes", [])),
                "coverage": copy.deepcopy(raw.get("coverage")),
                "artifacts": artifacts,
            }
        )
        factorial_mapping.append({"cell_id": cell_id, "blind_cell_id": blind_cell, **factors})

    comparisons: dict[str, Any] = {}
    review_methods: dict[str, Any] = {}
    ui_families: dict[str, Any] = {}
    for family in METHOD_FAMILIES:
        options: dict[str, Any] = {}
        option_ui: dict[str, Any] = {}
        option_panels: list[Mapping[str, Any]] = []
        family_cells: list[Mapping[str, Any]] = []
        for label in ("A", "B"):
            candidate_id = labels[family][label]
            panel = panels[family][candidate_id]
            option_panels.append(panel)
            owned_ids = [cell_id for cell_id, factors in registry_cells.items() if factors[family] == candidate_id]
            owned = [cells[cell_id] for cell_id in owned_ids]
            family_cells.extend(owned)
            artifact = panel_artifacts[family][candidate_id]
            blind_option = mapping_families[family][label]
            options[label] = {
                "blind_option_id": blind_option["blind_option_id"],
                "blind_cell_ids": blind_option["blind_cell_ids"],
                "artifacts": [] if artifact is None else [artifact],
                "coverage_summary": _coverage_summary(owned),
            }
            option_status = (
                "available"
                if artifact is not None and all(cell.get("availability") == "available" for cell in owned)
                else "partial"
                if artifact is not None
                or any(
                    cell.get("availability")
                    in {"available", "rejected_low_coverage"}
                    for cell in owned
                )
                else "unreviewable"
            )
            option_ui[label] = {
                "status": option_status,
                "reason": None if option_status == "available" else panel.get("reason") or "Evidence is incomplete and retained without replacement.",
                "local_path": None if artifact is None else artifact["path"],
                "valid_coverage_fraction": panel.get("valid_coverage_fraction"),
                "contributing_scene_count": panel.get("contributing_scene_count"),
            }
        availability, reason = _comparison_availability(option_panels, family_cells)
        comparisons[family] = {
            "availability": availability,
            "reason": reason,
            "display_order": ["A", "B"],
            "option_a": options["A"],
            "option_b": options["B"],
            "paired_other_factors": True,
            "primary_assessment_required_first": True,
            "selected_or_activated": False,
        }
        review_methods[family] = {
            "availability": availability,
            "option_a": options["A"]["blind_option_id"],
            "option_b": options["B"]["blind_option_id"],
            "display_order": ["A", "B"],
            "preference": None,
            "reviewer_confidence": None,
            "evidence_reason": None,
            "selected_or_activated": False,
        }
        ui_families[family] = {"options": option_ui}

    evidence_id = EVIDENCE_ID_PREFIX + identity_sha256(
        "phase2a4-method-evidence-v1", package_id, blind
    )
    sidecar: dict[str, Any] = {
        "$schema": EVIDENCE_SCHEMA_URL,
        "schema_version": SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "derivative_package_id": package_id,
        "scientific_status": "provisional_blinded_method_comparison_evidence",
        "registry_binding": {
            "registry_id": REGISTRY_ID,
            "registry_version": SCHEMA_VERSION,
            "path": REGISTRY_RELATIVE_PATH,
            "bytes": registry_artifact["bytes"],
            "sha256": registry_artifact["sha256"],
        },
        "parent_case": {
            "phase2a3_package_id": ACCEPTED_PARENT_PACKAGE_ID,
            "phase2a3_population_snapshot_id": ACCEPTED_POPULATION_ID,
            "phase2a3_manifest_sha256": ACCEPTED_PARENT_MANIFEST_SHA256,
            "blind_case_id": blind,
            "target_date": parent_case["target_date"],
            "target_geometry_sha256": parent_case["target_geometry_sha256"],
            "canonical_observation_id": None,
            "canonical_event_id": None,
        },
        "source_binding": source_binding,
        "factorial_results": factorial_results,
        "comparisons": comparisons,
        "review_method_metadata": review_methods,
        "missing_evidence_policy": {
            "case_replaced": False,
            "unavailable_cells_retained": True,
            "unavailable_comparison_label": "unreviewable",
            "missing_interpreted_as_zero": False,
        },
        "claims": {
            "qualified_human_label_present": False,
            "scientific_accuracy_claim": False,
            "method_selected_or_activated": False,
            "raw_detection_modified": False,
            "canonical_identity_inferred": False,
            "phase2a5_policy_modified": False,
        },
        "integrity": {
            "canonical_payload_sha256": "0" * 64,
            "canonical_payload_hash_rule": "RFC8785_SHA256_with_integrity.canonical_payload_sha256_omitted",
            "artifact_inventory_sha256": "0" * 64,
            "schema_validated": True,
            "parent_case_reconciled": True,
            "factorial_cells_reconciled": True,
            "coverage_reconciled": True,
            "blinding_metadata_reconciled": True,
        },
    }
    sidecar["integrity"]["artifact_inventory_sha256"] = canonical_sha256(_all_sidecar_artifacts(sidecar))
    sidecar["integrity"]["canonical_payload_sha256"] = _sidecar_payload_hash(sidecar)
    mapping_case = {
        "sample_id": parent_case["sample_id"],
        "blind_case_id": blind,
        "double_review": overlap,
        "families": mapping_families,
        "factorial_cells": factorial_mapping,
    }
    ui = {"evidence_id": evidence_id, "families": ui_families}
    return sidecar, mapping_case, ui


def _source_inventory(repository_root: Path) -> list[dict[str, Any]]:
    paths = (
        repository_root / "src" / "detection" / "baseline_manifest.py",
        repository_root / "src" / "detection" / "identity.py",
        repository_root / "src" / "validation" / "phase2a4_evidence.py",
        repository_root / "src" / "validation" / "phase2a4_package.py",
        repository_root / "src" / "validation" / "phase2a4_rainfall.py",
        repository_root / "src" / "validation" / "package.py",
        repository_root / "src" / "validation" / "validator.py",
        repository_root / "scripts" / "build_phase2a4_method_package.py",
        repository_root / "scripts" / "validate_phase2a4_method_package.py",
        repository_root / "scripts" / "validate_validation_reviews.py",
        repository_root / "docs" / "contracts" / "phase2a" / "reviewer.js",
        repository_root / "docs" / "contracts" / "phase2a" / "reviewer.css",
        repository_root / "docs" / "contracts" / "phase2a" / "PHASE_2A4_REVIEWER_PROTOCOL_V1.md",
        repository_root / "docs" / "contracts" / "phase2a" / "schemas" / "phase2a4-candidate-registry-v1.schema.json",
        repository_root / "docs" / "contracts" / "phase2a" / "schemas" / "phase2a4-method-evidence-v1.schema.json",
        repository_root / "docs" / "contracts" / "phase2a" / "schemas" / "phase2a4-derivative-manifest-v1.schema.json",
        repository_root / "docs" / "contracts" / "phase2a" / "schemas" / "phase2a4-review-export-v1.schema.json",
    )
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise Phase2A4PackageError(f"package generator source missing: {missing}")
    return [_artifact(path, repository_root) for path in paths]


def _phase2a4_runtime_versions() -> dict[str, str]:
    return {
        **_runtime_versions(),
        "phase2a4_package_python": platform.python_version(),
    }


def _validate_package_identity_binding(
    manifest: Mapping[str, Any], mapping: Mapping[str, Any]
) -> None:
    identity = mapping.get("package_identity_inputs")
    if not isinstance(identity, Mapping):
        raise Phase2A4PackageIntegrityError("package identity inputs are missing")
    if (
        identity.get("runtime_versions") != manifest.get("runtime_versions")
        or identity.get("generator_source_inventory")
        != manifest.get("generator_source_inventory")
        or manifest.get("package_id")
        != PACKAGE_ID_PREFIX + canonical_sha256(identity)
    ):
        raise Phase2A4PackageIntegrityError(
            "derivative package runtime/source identity mismatch"
        )


def _copy_parent_material(parent_root: Path, package_root: Path) -> None:
    for slot in REVIEWER_SLOTS:
        shutil.copytree(parent_root / slot, package_root / slot)
    shutil.copytree(parent_root / "coordinator", package_root / "coordinator")
    for relative in ("sampling", "schemas"):
        source = parent_root / relative
        if source.is_dir():
            shutil.copytree(source, package_root / relative)
    for relative in ("PROTOCOL.md", "sources.json"):
        source = parent_root / relative
        if source.is_file():
            destination = package_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


def _schema_binding(path: Path, root: Path) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **_artifact(path, root)}


def _review_package_binding(package_root: Path, slot: str, package_id: str) -> dict[str, str]:
    reviewer_root = package_root / slot
    return {
        "package_id": package_id,
        "assignment_sha256": sha256_file(reviewer_root / "assignment.json"),
        "review_template_sha256": sha256_file(reviewer_root / "review-template.json"),
        "method_evidence_index_sha256": sha256_file(reviewer_root / "method-evidence" / "index.json"),
        "review_schema_sha256": sha256_file(package_root / "schemas" / "validation-review-v1.schema.json"),
    }


def build_phase2a4_derivative_package(
    *,
    parent_root: Path,
    registry_path: Path,
    rainfall_root: Path,
    evidence_root: Path,
    output_root: Path,
    repository_root: Path,
    generated_at: str,
    generation_command: Sequence[str],
) -> dict[str, Any]:
    """Build the complete local derivative and validate it before publication.

    ``output_root`` must not already exist.  Construction uses a sibling staging
    directory and renames it only after all schema, checksum, blinding, parent,
    and reviewer-isolation checks pass.
    """
    parent_root = Path(parent_root).resolve()
    registry_path = Path(registry_path).resolve()
    rainfall_root = Path(rainfall_root).resolve()
    evidence_root = Path(evidence_root).resolve()
    output_root = Path(output_root).resolve()
    repository_root = Path(repository_root).resolve()
    _parse_timestamp(generated_at, label="generated_at")
    if not generation_command or any(not isinstance(value, str) or not value for value in generation_command):
        raise Phase2A4PackageError("generation_command must contain non-empty strings")
    if output_root.exists():
        raise Phase2A4PackageError("output directory already exists; refusing to overwrite")
    for source_root in (parent_root, rainfall_root, evidence_root):
        try:
            output_root.relative_to(source_root)
        except ValueError:
            pass
        else:
            raise Phase2A4PackageError("output directory must not be nested in an input artifact")

    generator_inventory = _source_inventory(repository_root)
    runtime_versions = _phase2a4_runtime_versions()
    validate_validation_package(parent_root)
    parent_manifest, parent_by_blind = _parent_index(parent_root)
    rainfall_manifest = validate_rainfall_reference_artifact(rainfall_root)
    registry = _load_json(registry_path)
    registry_schema_path = repository_root / "docs/contracts/phase2a/schemas/phase2a4-candidate-registry-v1.schema.json"
    method_schema_path = repository_root / "docs/contracts/phase2a/schemas/phase2a4-method-evidence-v1.schema.json"
    manifest_schema_path = repository_root / "docs/contracts/phase2a/schemas/phase2a4-derivative-manifest-v1.schema.json"
    review_export_schema_path = repository_root / "docs/contracts/phase2a/schemas/phase2a4-review-export-v1.schema.json"
    registry_schema = _load_json(registry_schema_path)
    _validate_schema(registry, registry_schema, "candidate registry")
    candidates, registry_cells = _registry_index(registry)
    validate_phase2a4_evidence_artifact(
        evidence_root,
        parent_package_dir=parent_root,
        candidate_registry_path=registry_path,
        rainfall_artifact_dir=rainfall_root,
        baseline_manifest_path=repository_root / "config/baseline_manifest_v1.json",
        repository_root=repository_root,
    )
    evidence_manifest, evidence_records, blinding_key = _load_evidence(
        evidence_root, parent_by_blind=parent_by_blind, registry_path=registry_path
    )
    labels = deterministic_blind_mapping(
        list(parent_by_blind), candidates, blinding_key=blinding_key
    )
    package_identity = {
        "pipeline": "phase2a4-derivative-package-v1",
        "parent_manifest_sha256": ACCEPTED_PARENT_MANIFEST_SHA256,
        "registry_sha256": sha256_file(registry_path),
        "rainfall_manifest_sha256": sha256_file(rainfall_root / "manifest.json"),
        "candidate_evidence_manifest_sha256": sha256_file(evidence_root / "manifest.json"),
        "candidate_evidence_checksums_sha256": blinding_key,
        "generated_at": generated_at,
        "generation_command": list(generation_command),
        "generator_source_inventory": generator_inventory,
        "runtime_versions": runtime_versions,
    }
    package_id = PACKAGE_ID_PREFIX + canonical_sha256(package_identity)

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.staging-", dir=output_root.parent))
    try:
        _copy_parent_material(parent_root, staging)
        (staging / "config").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(registry_path, staging / REGISTRY_RELATIVE_PATH)
        schema_sources = {
            "phase2a4-candidate-registry-v1.schema.json": registry_schema_path,
            "phase2a4-method-evidence-v1.schema.json": method_schema_path,
            "phase2a4-derivative-manifest-v1.schema.json": manifest_schema_path,
            "phase2a4-review-export-v1.schema.json": review_export_schema_path,
        }
        for name, source in schema_sources.items():
            shutil.copyfile(source, staging / "schemas" / name)
        shutil.copyfile(
            repository_root / "docs/contracts/phase2a/reviewer.js",
            staging / "reviewer-a" / "reviewer.js",
        )
        shutil.copyfile(
            repository_root / "docs/contracts/phase2a/reviewer.css",
            staging / "reviewer-a" / "reviewer.css",
        )
        shutil.copyfile(staging / "reviewer-a" / "reviewer.js", staging / "reviewer-b" / "reviewer.js")
        shutil.copyfile(staging / "reviewer-a" / "reviewer.css", staging / "reviewer-b" / "reviewer.css")
        protocol_source = (
            repository_root
            / "docs/contracts/phase2a/PHASE_2A4_REVIEWER_PROTOCOL_V1.md"
        )
        if not protocol_source.is_file():
            raise Phase2A4PackageError("Phase 2A.4 reviewer protocol is missing")
        for slot in REVIEWER_SLOTS:
            shutil.copyfile(protocol_source, staging / slot / "METHOD_PROTOCOL.md")

        shutil.copytree(evidence_root, staging / "coordinator" / "candidate-evidence")
        shutil.copytree(rainfall_root, staging / "coordinator" / "rainfall-reference")
        registry_artifact = _artifact(staging / REGISTRY_RELATIVE_PATH, staging)
        overlap_ids = set(_load_json(parent_root / "reviewer-b" / "assignment.json")["blind_case_ids"])
        mapping_cases: list[dict[str, Any]] = []
        sidecars: dict[str, dict[str, Any]] = {}
        ui_by_blind: dict[str, dict[str, Any]] = {}
        method_schema = _load_json(method_schema_path)
        for blind in sorted(parent_by_blind):
            sidecar, mapping_case, ui = _build_case_material(
                package_root=staging,
                evidence_root=evidence_root,
                record=evidence_records[blind],
                parent_case=parent_by_blind[blind],
                package_id=package_id,
                registry_artifact=registry_artifact,
                candidate_ids=candidates,
                registry_cells=registry_cells,
                labels=labels[blind],
                blinding_key=blinding_key,
                overlap=blind in overlap_ids,
            )
            _validate_schema(sidecar, method_schema, f"method evidence {blind}")
            sidecars[blind] = sidecar
            mapping_cases.append(mapping_case)
            ui_by_blind[blind] = ui
            relative = Path("method-evidence") / f"{blind}.json"
            write_canonical_json(staging / "reviewer-a" / relative, sidecar)
            if blind in overlap_ids:
                write_canonical_json(staging / "reviewer-b" / relative, sidecar)
            write_canonical_json(staging / "coordinator" / "method-evidence" / f"{blind}.json", sidecar)

        blinding_map: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "package_id": package_id,
            "mapping_id": "",
            "registry_binding": {
                "registry_id": REGISTRY_ID,
                "registry_version": SCHEMA_VERSION,
                "path": REGISTRY_RELATIVE_PATH,
                "bytes": registry_artifact["bytes"],
                "sha256": registry_artifact["sha256"],
            },
            "parent_binding": {
                "phase2a3_package_id": ACCEPTED_PARENT_PACKAGE_ID,
                "population_snapshot_id": ACCEPTED_POPULATION_ID,
                "phase2a3_manifest_sha256": ACCEPTED_PARENT_MANIFEST_SHA256,
            },
            "blinding_derivation": {
                "version": "phase2a4-balanced-keyed-blinding-v1",
                "coordinator_only_evidence_checksums_sha256": blinding_key,
                "exact_balance_per_family": {family: {"A_candidate_0": 30, "A_candidate_1": 30} for family in METHOD_FAMILIES},
            },
            "package_identity_inputs": package_identity,
            "cases": mapping_cases,
        }
        map_identity = copy.deepcopy(blinding_map)
        map_identity.pop("mapping_id")
        blinding_map["mapping_id"] = "p2a4-blinding-map-v1-" + canonical_sha256(map_identity)
        write_canonical_json(staging / "coordinator" / "blinding-map.json", blinding_map)

        for slot in REVIEWER_SLOTS:
            assignment = _load_json(parent_root / slot / "assignment.json")
            blind_ids = assignment["blind_case_ids"]
            cases: list[dict[str, Any]] = []
            reviews: list[dict[str, Any]] = []
            slot_ui: dict[str, Any] = {}
            for blind in blind_ids:
                parent_case_path = parent_root / slot / "cases" / f"{blind}.json"
                case = _load_json(parent_case_path)
                methods = case["review_fields"]["method_comparisons"]
                for family in METHOD_FAMILIES:
                    methods[family] = copy.deepcopy(sidecars[blind]["review_method_metadata"][family])
                cases.append(case)
                reviews.append(copy.deepcopy(case["review_fields"]))
                slot_ui[blind] = ui_by_blind[blind]
                write_canonical_json(staging / slot / "cases" / f"{blind}.json", case)
            review_template = {"schema_version": SCHEMA_VERSION, "reviewer_slot": slot, "reviews": reviews}
            write_canonical_json(staging / slot / "review-template.json", review_template)
            write_canonical_json(staging / slot / "method-evidence" / "index.json", slot_ui)
            package_binding = _review_package_binding(staging, slot, package_id)
            html = _html_document(
                reviewer_slot=slot,
                cases=cases,
                reviews=reviews,
                method_evidence=slot_ui,
                package_phase="phase2a4",
                package_binding=package_binding,
            )
            (staging / slot / "index.html").write_text(html, encoding="utf-8", newline="\n")

        manifest_inventory_before = _inventory(staging)
        mapping_artifact = _artifact(staging / "coordinator" / "blinding-map.json", staging)
        reviewer_packages = []
        for slot in REVIEWER_SLOTS:
            subset = [item for item in manifest_inventory_before if item["path"].startswith(f"{slot}/")]
            reviewer_packages.append(
                {
                    "reviewer_slot": slot,
                    "case_count": len(_load_json(staging / slot / "assignment.json")["blind_case_ids"]),
                    "directory": slot,
                    "artifact_inventory_sha256": _inventory_digest(subset),
                    "true_candidate_mapping_present": False,
                    "other_reviewer_outputs_present": False,
                }
            )
        evidence_status_counts = Counter(
            cell["availability"] for sidecar in sidecars.values() for cell in sidecar["factorial_results"]
        )
        rainfall_binding = evidence_manifest.get("rainfall_reference", {})
        rainfall_id = rainfall_manifest.get("artifact_id")
        rainfall_manifest_sha = sha256_file(rainfall_root / "manifest.json")
        rainfall_plan_sha = rainfall_manifest.get("plan_sha256")
        if (
            rainfall_binding.get("artifact_id") not in (None, rainfall_id)
            or rainfall_binding.get("manifest_sha256") not in (None, rainfall_manifest_sha)
            or rainfall_binding.get("plan_sha256") not in (None, rainfall_plan_sha)
        ):
            raise Phase2A4PackageError("candidate evidence rainfall binding mismatch")
        schema_bindings = {
            "candidate_registry": _schema_binding(staging / "schemas" / "phase2a4-candidate-registry-v1.schema.json", staging),
            "method_evidence": _schema_binding(staging / "schemas" / "phase2a4-method-evidence-v1.schema.json", staging),
            "derivative_manifest": _schema_binding(staging / "schemas" / "phase2a4-derivative-manifest-v1.schema.json", staging),
            "phase2a4_review_export": _schema_binding(staging / "schemas" / "phase2a4-review-export-v1.schema.json", staging),
            "phase2a3_review": _schema_binding(staging / "schemas" / "validation-review-v1.schema.json", staging),
        }
        if (
            _source_inventory(repository_root) != generator_inventory
            or _phase2a4_runtime_versions() != runtime_versions
        ):
            raise Phase2A4PackageError(
                "package generator source or runtime changed during construction"
            )
        artifact_inventory = _inventory(staging)
        manifest: dict[str, Any] = {
            "$schema": PACKAGE_SCHEMA_URL,
            "schema_version": SCHEMA_VERSION,
            "package_id": package_id,
            "package_type": "phase2a4_provisional_blinded_method_comparison_derivative",
            "scientific_status": "provisional_audit_inputs_only",
            "method_decision_status": "none",
            "generated_at": generated_at,
            "generation_command": list(generation_command),
            "runtime_versions": runtime_versions,
            "generator_source_inventory": generator_inventory,
            "local_only": True,
            "parent_binding": {
                "phase2a3_package_id": ACCEPTED_PARENT_PACKAGE_ID,
                "population_snapshot_id": ACCEPTED_POPULATION_ID,
                "phase2a3_manifest_sha256": ACCEPTED_PARENT_MANIFEST_SHA256,
                "scientific_status": "provisional_audit_inputs_only",
                "parent_artifact_inventory_sha256": _inventory_digest(parent_manifest["artifact_inventory"]),
                "parent_package_mutated": False,
                "canonical_observation_or_event_ids_inferred": False,
            },
            "registry_binding": {
                "registry_id": REGISTRY_ID,
                "registry_version": SCHEMA_VERSION,
                "path": REGISTRY_RELATIVE_PATH,
                "bytes": registry_artifact["bytes"],
                "sha256": registry_artifact["sha256"],
            },
            "schema_bindings": schema_bindings,
            "factorial_design": {
                "design_id": "phase2a4-full-factorial-2x2x2-v1",
                "type": "full_factorial",
                "factor_order": ["drought_adjustment", "cloud_mask", "daily_composition"],
                "candidate_ids": {family: list(candidates[family]) for family in METHOD_FAMILIES},
                "expected_cell_count_per_case": 8,
                "same_frozen_cases": True,
                "same_source_scene_set_within_case": True,
                "same_case_window_within_case": True,
                "other_factors_compared_as_paired_strata": True,
                "desired_total_tuning_performed": False,
            },
            "case_population": {
                "primary_case_count": 60,
                "double_review_case_count": 12,
                "case_replacement_performed": False,
                "missing_cases_retained": True,
                "blind_case_ids_sha256": canonical_sha256(sorted(parent_by_blind)),
                "method_evidence_sidecar_count": 60,
                "evidence_status_counts": dict(sorted(evidence_status_counts.items())),
            },
            "source_provenance": {
                "monitoring_extent_id": "araripe-implementation-rectangle-v1",
                "monitoring_extent_geometry_sha256": ACCEPTED_EXTENT_GEOMETRY_SHA256,
                "baseline_version": "1.0.0",
                "baseline_manifest_sha256": ACCEPTED_BASELINE_MANIFEST_SHA256,
                "sentinel_catalog": "https://earth-search.aws.element84.com/v1",
                "sentinel_collection": "sentinel-2-l2a",
                "case_window_evaluation": "fixed_20m_windows_aligned_to_accepted_reference_grid",
                "stac_item_json_hashes_bound": True,
                "unsigned_asset_urls_bound": True,
                "asset_checksums_and_http_metadata_bound": True,
                "remote_assets_range_read": True,
                "local_window_checksums_cover_full_remote_assets": False,
                "rainfall_artifact_id": rainfall_id,
                "rainfall_manifest_sha256": rainfall_manifest_sha,
                "rainfall_plan_sha256": rainfall_plan_sha,
                "rainfall_full_upstream_cog_checksums_available": False,
            },
            "review": {
                "review_schema_version": SCHEMA_VERSION,
                "primary_case_count": 60,
                "double_review_case_count": 12,
                "isolated_reviewer_workflow": True,
                "primary_change_assessment_required_before_method_reveal": True,
                "primary_fields_locked_after_method_reveal": True,
                "human_labels_present": False,
                "qualified_reviewer_evidence_present": False,
                "mapbiomas_and_contextual_signature_policy_modified": False,
            },
            "blinding": {
                "reviewer_option_labels": ["A", "B"],
                "true_mapping_coordinator_only": True,
                "mapping_artifact": mapping_artifact,
                "mapping_distributed_to_reviewers": False,
                "mapping_bijection_validated": True,
                "deterministic_display_order_validated": True,
                "double_review_evidence_identical": True,
                "double_review_order_independently_derived": True,
                "reviewer_packages": reviewer_packages,
            },
            "decision_state": {
                "selected_candidates": {family: None for family in METHOD_FAMILIES},
                "drought_adjustment_activated": False,
                "cloud_mask_locked": False,
                "daily_composition_locked": False,
                "release_or_replay_authorized": False,
            },
            "claims": {
                "qualified_human_labels_present": False,
                "scientific_accuracy_claim": False,
                "tool_integrity_interpreted_as_scientific_accuracy": False,
                "method_promoted_or_activated": False,
                "raw_detection_modified": False,
                "missing_evidence_interpreted_as_zero": False,
                "canonical_identity_inferred": False,
                "phase2a5_policy_modified": False,
                "baseline_rebuilt": False,
                "current_year_replayed": False,
            },
            "integrity": {
                "schema_validated": True,
                "checksum_file_validated": True,
                "artifact_inventory_reconciled": True,
                "parent_binding_reconciled": True,
                "registry_binding_reconciled": True,
                "all_sidecars_validated": True,
                "all_factorial_cells_reconciled": True,
                "case_windows_reconciled": True,
                "source_scene_provenance_reconciled": True,
                "contributing_scene_counts_reconciled": True,
                "coverage_reconciled": True,
                "mapping_bijection_reconciled": True,
                "reviewer_isolation_reconciled": True,
                "missing_evidence_retained": True,
            },
            "generation_limitations": [
                "No qualified reviewer labels or scientific method decision are present.",
                "Technical integrity does not establish scientific accuracy.",
                "Remote raster range-window checksums do not verify complete upstream assets.",
                "Missing and failed cells remain retained and were not replaced or interpreted as zero.",
            ],
            "artifact_inventory_rule": (
                "artifact_inventory contains every immutable derivative file except manifest.json and "
                "CHECKSUMS.sha256; CHECKSUMS.sha256 includes manifest.json and every inventoried file "
                "and excludes only itself."
            ),
            "artifact_inventory": artifact_inventory,
            "checksum_file": "CHECKSUMS.sha256",
        }
        _validate_schema(manifest, _load_json(manifest_schema_path), "derivative manifest")
        write_canonical_json(staging / "manifest.json", manifest)
        _write_checksums(staging, artifact_inventory)
        validate_phase2a4_derivative_package(
            staging,
            parent_root=parent_root,
            registry_path=registry_path,
            rainfall_root=rainfall_root,
            evidence_root=evidence_root,
            repository_root=repository_root,
        )
        os.replace(staging, output_root)
        return manifest
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _verify_method_artifact(root: Path, artifact: Mapping[str, Any]) -> None:
    path = _safe_path(root, artifact["path"], error_type=Phase2A4PackageIntegrityError)
    if (
        not path.is_file()
        or path.stat().st_size != artifact["bytes"]
        or sha256_file(path) != artifact["sha256"]
    ):
        raise Phase2A4PackageIntegrityError(f"method artifact mismatch: {artifact['path']}")


def _validate_window(source: Mapping[str, Any]) -> None:
    if source["reference_grid"] != REFERENCE_GRID or source["coverage_contract"] != COVERAGE_CONTRACT:
        raise Phase2A4PackageIntegrityError("reference grid or coverage contract mismatch")
    window = copy.deepcopy(source["case_window"])
    digest = window.pop("window_definition_sha256")
    if canonical_sha256(window) != digest:
        raise Phase2A4PackageIntegrityError("case-window definition hash mismatch")
    col, row, width, height = (
        window["column_offset"], window["row_offset"], window["width"], window["height"]
    )
    if col + width > REFERENCE_GRID["width"] or row + height > REFERENCE_GRID["height"]:
        raise Phase2A4PackageIntegrityError("case window exceeds accepted grid")
    expected_transform = [20.0, 0.0, 290080.0 + 20.0 * col, 0.0, -20.0, 9231780.0 - 20.0 * row]
    expected_bounds = [
        expected_transform[2],
        expected_transform[5] - 20.0 * height,
        expected_transform[2] + 20.0 * width,
        expected_transform[5],
    ]
    if window["transform"] != expected_transform or window["bounds"] != expected_bounds:
        raise Phase2A4PackageIntegrityError("case-window transform or bounds mismatch")


def _validate_source_binding(sidecar: Mapping[str, Any]) -> None:
    source = sidecar["source_binding"]
    query = copy.deepcopy(source["query"])
    request_payload = {
        "stac_endpoint": source["stac_endpoint"],
        "collection": source["collection_id"],
        "intersects": query["intersects"],
        "datetime": query["datetime"],
        "query": {"eo:cloud_cover": {"lt": query["eo_cloud_cover_lt"]}},
        "max_items": query["result_limit"],
        "pagination_policy": query["pagination_policy"],
    }
    if (
        canonical_sha256(request_payload) != query["canonical_payload_sha256"]
        or canonical_geometry_sha256(query["intersects"])[1]
        != query["intersects_geometry_sha256"]
        or query["target_date"] != sidecar["parent_case"]["target_date"]
    ):
        raise Phase2A4PackageIntegrityError("source query fingerprint/date mismatch")
    scene_ids = [scene["item_id"] for scene in source["source_scenes"]]
    if len(scene_ids) != len(set(scene_ids)) or canonical_sha256(scene_ids) != source["source_scene_ids_sha256"]:
        raise Phase2A4PackageIntegrityError("source scene identity digest mismatch")
    for scene in source["source_scenes"]:
        observed = scene["observed_at"][:10]
        if observed != query["target_date"]:
            raise Phase2A4PackageIntegrityError("source scene falls outside deterministic same-day query")
        parsed_self = urlsplit(scene["self_href"])
        if parsed_self.query or parsed_self.fragment or parsed_self.username or parsed_self.password:
            raise Phase2A4PackageIntegrityError("source self URL is signed or contains userinfo")
        keys = [asset["asset_key"] for asset in scene["assets"]]
        if keys != list(ASSET_KEYS):
            raise Phase2A4PackageIntegrityError("source assets are not the fixed eight-key order")
        for asset in scene["assets"]:
            provider_href = asset["provider_href"]
            href = asset["unsigned_href"]
            if asset["href_resolution_policy"] != _ASSET_HREF_RESOLUTION_POLICY:
                raise Phase2A4PackageIntegrityError(
                    "source asset transport-resolution policy mismatch"
                )
            if href:
                parsed = urlsplit(href)
                if parsed.query or parsed.fragment or parsed.username or parsed.password:
                    raise Phase2A4PackageIntegrityError("source asset URL is signed or contains userinfo")
                try:
                    raw, expected_href = _resolve_provider_asset_hrefs(
                        provider_href,
                        label=f"source asset {scene['item_id']}/{asset['asset_key']}",
                    )
                except ValueError as exc:
                    raise Phase2A4PackageIntegrityError(
                        "source provider/read asset URL binding mismatch"
                    ) from exc
                if raw != provider_href or expected_href != href:
                    raise Phase2A4PackageIntegrityError(
                        "source provider/read asset URL binding mismatch"
                    )
            elif provider_href is not None:
                raise Phase2A4PackageIntegrityError(
                    "missing source asset retains an unmatched provider URL"
                )
    _validate_window(source)


def _assert_blank_review(review: Mapping[str, Any]) -> None:
    blank_fields = {
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
        "usability": {
            "review_duration_seconds": None,
            "missing_or_confusing_evidence": [],
            "tool_issue": None,
        },
        "notes": None,
    }
    if any(review.get(name) != value for name, value in blank_fields.items()):
        raise Phase2A4PackageIntegrityError("review package contains a human assessment")
    methods = review.get("method_comparisons")
    if not isinstance(methods, Mapping) or set(methods) != set(
        METHOD_FAMILIES + PRESERVED_METHOD_FAMILIES
    ):
        raise Phase2A4PackageIntegrityError("review package method fields are invalid")
    for family in METHOD_FAMILIES + PRESERVED_METHOD_FAMILIES:
        method = methods[family]
        if any(method.get(key) is not None for key in ("preference", "reviewer_confidence", "evidence_reason")) or method.get("selected_or_activated") is not False:
            raise Phase2A4PackageIntegrityError("method review is not blank")
        if family in PRESERVED_METHOD_FAMILIES and method != {
            "availability": "not_generated_in_2a3",
            "option_a": None,
            "option_b": None,
            "display_order": [],
            "preference": None,
            "reviewer_confidence": None,
            "evidence_reason": None,
            "selected_or_activated": False,
        }:
            raise Phase2A4PackageIntegrityError(
                "Phase 2A.5 method field changed in Phase 2A.4"
            )


def _compare_parent_review_material(package_root: Path, parent_root: Path) -> None:
    for slot in REVIEWER_SLOTS:
        if (package_root / slot / "assignment.json").read_bytes() != (parent_root / slot / "assignment.json").read_bytes():
            raise Phase2A4PackageIntegrityError(f"{slot} assignment/order changed")
        assignment = _load_json(package_root / slot / "assignment.json", error_type=Phase2A4PackageIntegrityError)
        template = _load_json(package_root / slot / "review-template.json", error_type=Phase2A4PackageIntegrityError)
        if [review["blind_case_id"] for review in template["reviews"]] != assignment["blind_case_ids"]:
            raise Phase2A4PackageIntegrityError(f"{slot} template order mismatch")
        for blind in assignment["blind_case_ids"]:
            derived = _load_json(package_root / slot / "cases" / f"{blind}.json", error_type=Phase2A4PackageIntegrityError)
            parent = _load_json(parent_root / slot / "cases" / f"{blind}.json", error_type=Phase2A4PackageIntegrityError)
            for family in PRESERVED_METHOD_FAMILIES:
                if derived["review_fields"]["method_comparisons"][family] != parent["review_fields"]["method_comparisons"][family]:
                    raise Phase2A4PackageIntegrityError(f"Phase 2A.5 method field changed: {blind}/{family}")
            normalized = copy.deepcopy(derived)
            for family in METHOD_FAMILIES:
                normalized["review_fields"]["method_comparisons"][family] = copy.deepcopy(
                    parent["review_fields"]["method_comparisons"][family]
                )
            if normalized != parent:
                raise Phase2A4PackageIntegrityError(f"base Phase 2A.3 case/evidence changed: {slot}/{blind}")
            _assert_blank_review(derived["review_fields"])


def _reviewer_leakage_scan(
    package_root: Path,
    *,
    registry: Mapping[str, Any],
    mapping: Mapping[str, Any],
) -> None:
    candidate_strings = [
        candidate
        for family in METHOD_FAMILIES
        for candidate in registry["families"][family]["candidate_ids"]
    ]
    sample_ids = [case["sample_id"] for case in mapping["cases"]]
    cell_ids = [cell["cell_id"] for cell in registry["factorial_design"]["treatment_cells"]]
    forbidden = [value.encode("utf-8") for value in (*candidate_strings, *sample_ids, *cell_ids)]
    for slot in REVIEWER_SLOTS:
        for path in (package_root / slot).rglob("*"):
            if path.is_file():
                payload = path.read_bytes()
                if any(token in payload for token in forbidden):
                    raise Phase2A4PackageIntegrityError(f"true mapping leaked into {slot}: {path.relative_to(package_root)}")
        for path in sorted((package_root / slot / "method-evidence").glob("*.json")):
            value = _load_json(path, error_type=Phase2A4PackageIntegrityError)

            def keys(item: Any) -> Iterable[str]:
                if isinstance(item, Mapping):
                    for key, nested in item.items():
                        yield str(key)
                        yield from keys(nested)
                elif isinstance(item, list):
                    for nested in item:
                        yield from keys(nested)

            forbidden_semantic_keys = {
                "candidate_id",
                "cell_id",
                "drought_status",
                "spi3",
                "z_threshold_adjustment",
            }
            leaked = forbidden_semantic_keys.intersection(keys(value))
            if leaked:
                raise Phase2A4PackageIntegrityError(
                    f"semantic method identity leaked into {slot}: "
                    f"{path.relative_to(package_root)} ({sorted(leaked)})"
                )


def _validate_overlap(package_root: Path) -> None:
    overlap = _load_json(package_root / "reviewer-b" / "assignment.json", error_type=Phase2A4PackageIntegrityError)["blind_case_ids"]
    for blind in overlap:
        for path_a in sorted((package_root / "reviewer-a" / "method-evidence" / blind).rglob("*")):
            if path_a.is_file():
                relative = path_a.relative_to(package_root / "reviewer-a")
                path_b = package_root / "reviewer-b" / relative
                if not path_b.is_file() or path_a.read_bytes() != path_b.read_bytes():
                    raise Phase2A4PackageIntegrityError(f"overlap panel bytes differ: {blind}/{relative}")
        sidecar_relative = Path("method-evidence") / f"{blind}.json"
        if (package_root / "reviewer-a" / sidecar_relative).read_bytes() != (package_root / "reviewer-b" / sidecar_relative).read_bytes():
            raise Phase2A4PackageIntegrityError(f"overlap sidecar bytes differ: {blind}")


def _validate_mapping(
    mapping: Mapping[str, Any],
    *,
    registry: Mapping[str, Any],
    sidecars: Mapping[str, Mapping[str, Any]],
) -> None:
    identity = copy.deepcopy(mapping)
    mapping_id = identity.pop("mapping_id")
    if mapping_id != "p2a4-blinding-map-v1-" + canonical_sha256(identity):
        raise Phase2A4PackageIntegrityError("blinding mapping ID mismatch")
    candidates, cells = _registry_index(registry)
    key = mapping["blinding_derivation"]["coordinator_only_evidence_checksums_sha256"]
    expected_labels = deterministic_blind_mapping(list(sidecars), candidates, blinding_key=key)
    mapping_cases = mapping.get("cases")
    if not isinstance(mapping_cases, list) or len(mapping_cases) != 60:
        raise Phase2A4PackageIntegrityError("blinding mapping must contain exactly 60 cases")
    mapped_blind_ids = [case.get("blind_case_id") for case in mapping_cases]
    if len(set(mapped_blind_ids)) != 60 or set(mapped_blind_ids) != set(sidecars):
        raise Phase2A4PackageIntegrityError("blinding mapping case population is not bijective")
    seen = Counter()
    for case in mapping_cases:
        blind = case["blind_case_id"]
        if blind not in sidecars:
            raise Phase2A4PackageIntegrityError("mapping references unknown blind case")
        factorial_cells = case.get("factorial_cells")
        if not isinstance(factorial_cells, list):
            raise Phase2A4PackageIntegrityError("mapping factorial cells are missing")
        mapped_cells = {item["cell_id"]: item for item in factorial_cells}
        if len(factorial_cells) != 8 or set(mapped_cells) != set(cells):
            raise Phase2A4PackageIntegrityError("mapping is not bijective over factorial cells")
        for cell_id, factors in cells.items():
            mapped = mapped_cells[cell_id]
            if (
                mapped.get("blind_cell_id") != _blind_cell_id(key, blind, cell_id)
                or any(mapped.get(family) != factors[family] for family in METHOD_FAMILIES)
            ):
                raise Phase2A4PackageIntegrityError("blind-cell identifier or factors do not rederive")
        sidecar_cells = {item["blind_cell_id"] for item in sidecars[blind]["factorial_results"]}
        if {item["blind_cell_id"] for item in mapped_cells.values()} != sidecar_cells:
            raise Phase2A4PackageIntegrityError("blind-cell mapping does not reconcile")
        for family in METHOD_FAMILIES:
            for label in ("A", "B"):
                candidate = case["families"][family][label]["candidate_id"]
                if candidate != expected_labels[blind][family][label]:
                    raise Phase2A4PackageIntegrityError("deterministic candidate display mapping mismatch")
                if candidate == candidates[family][0] and label == "A":
                    seen[family] += 1
            a = case["families"][family]["A"]
            b = case["families"][family]["B"]
            if {a["candidate_id"], b["candidate_id"]} != set(candidates[family]):
                raise Phase2A4PackageIntegrityError("A/B candidate mapping is not bijective")
            for option in (a, b):
                candidate = option["candidate_id"]
                expected_cells = {
                    _blind_cell_id(key, blind, cell_id)
                    for cell_id, factors in cells.items()
                    if factors[family] == candidate
                }
                if (
                    option.get("blind_option_id")
                    != _blind_option_id(key, blind, family, candidate)
                    or set(option.get("blind_cell_ids", [])) != expected_cells
                ):
                    raise Phase2A4PackageIntegrityError("blind option identifiers do not rederive")
            comparison = sidecars[blind]["comparisons"][family]
            if (
                comparison["option_a"]["blind_option_id"] != a["blind_option_id"]
                or comparison["option_b"]["blind_option_id"] != b["blind_option_id"]
                or set(comparison["option_a"]["blind_cell_ids"]) != set(a["blind_cell_ids"])
                or set(comparison["option_b"]["blind_cell_ids"]) != set(b["blind_cell_ids"])
            ):
                raise Phase2A4PackageIntegrityError("sidecar option mapping does not reconcile")
    if any(seen[family] != 30 for family in METHOD_FAMILIES):
        raise Phase2A4PackageIntegrityError("A/B display mapping is not exactly balanced")


def _validate_packaged_evidence_mapping_binding(
    mapping: Mapping[str, Any], evidence_root: Path
) -> None:
    """Bind self-contained blinding and package identity to packaged evidence."""
    evidence_root = Path(evidence_root).resolve()
    manifest_sha256 = sha256_file(evidence_root / "manifest.json")
    checksums_sha256 = sha256_file(evidence_root / "CHECKSUMS.sha256")
    identity = mapping.get("package_identity_inputs")
    derivation = mapping.get("blinding_derivation")
    if not isinstance(identity, Mapping) or not isinstance(derivation, Mapping):
        raise Phase2A4PackageIntegrityError(
            "blinding mapping evidence bindings are missing"
        )
    if (
        identity.get("candidate_evidence_manifest_sha256") != manifest_sha256
        or identity.get("candidate_evidence_checksums_sha256") != checksums_sha256
        or derivation.get("coordinator_only_evidence_checksums_sha256")
        != checksums_sha256
    ):
        raise Phase2A4PackageIntegrityError(
            "packaged candidate-evidence blinding or identity binding mismatch"
        )


def _validate_sidecar_semantics(sidecar: Mapping[str, Any], reviewer_root: Path) -> None:
    if sidecar["integrity"]["canonical_payload_sha256"] != _sidecar_payload_hash(sidecar):
        raise Phase2A4PackageIntegrityError("method sidecar canonical payload hash mismatch")
    artifacts = _all_sidecar_artifacts(sidecar)
    if sidecar["integrity"]["artifact_inventory_sha256"] != canonical_sha256(artifacts):
        raise Phase2A4PackageIntegrityError("method sidecar artifact inventory hash mismatch")
    for artifact in artifacts:
        _verify_method_artifact(reviewer_root, artifact)
    _validate_source_binding(sidecar)
    source_ids = [scene["item_id"] for scene in sidecar["source_binding"]["source_scenes"]]
    window = sidecar["source_binding"]["case_window"]
    pixel_count = window["width"] * window["height"]
    if len(sidecar["factorial_results"]) != 8 or len({cell["blind_cell_id"] for cell in sidecar["factorial_results"]}) != 8:
        raise Phase2A4PackageIntegrityError("sidecar does not contain eight unique blind cells")
    for cell in sidecar["factorial_results"]:
        if cell["ordered_source_scene_ids"] != source_ids:
            raise Phase2A4PackageIntegrityError("factorial cell changed source-scene set/order")
        coverage = cell["coverage"]
        if coverage is not None:
            valid = coverage["valid_pixel_count"]
            expected_fraction = valid / pixel_count
            if coverage["case_window_pixel_count"] != pixel_count or abs(coverage["valid_coverage_fraction"] - expected_fraction) > 1e-12:
                raise Phase2A4PackageIntegrityError("cell valid coverage arithmetic mismatch")
            accepted = expected_fraction >= 0.2
            reason = None if accepted else "valid_coverage_below_threshold"
            if coverage["accepted"] is not accepted or coverage["rejection_reason"] != reason:
                raise Phase2A4PackageIntegrityError("cell coverage acceptance mismatch")
            expected_availability = (
                "available" if accepted else "rejected_low_coverage"
            )
            if cell["availability"] != expected_availability:
                raise Phase2A4PackageIntegrityError(
                    "cell availability does not match fixed coverage policy"
                )
        elif cell["availability"] in {"available", "rejected_low_coverage"}:
            raise Phase2A4PackageIntegrityError(
                "reviewable cell is missing fixed-window coverage"
            )
        selected_total = 0
        detector_valid_total = 0
        contributor_ids: set[str] = set()
        for contributor in cell["contributing_scenes"]:
            scene_id = contributor["scene_id"]
            if scene_id not in source_ids or scene_id in contributor_ids:
                raise Phase2A4PackageIntegrityError("cell contributor is duplicated or outside source set")
            contributor_ids.add(scene_id)
            selected_total += contributor["selected_pixel_count"]
            detector_valid_total += contributor["detector_valid_pixel_count"]
            scene_valid = contributor["scene_valid_pixel_count"]
            if (
                contributor["detector_valid_pixel_count"]
                > contributor["selected_pixel_count"]
                or contributor["selected_pixel_count"] > scene_valid
                or abs(contributor["scene_valid_coverage_fraction"] - scene_valid / pixel_count) > 1e-12
            ):
                raise Phase2A4PackageIntegrityError("contributing-scene coverage arithmetic mismatch")
        if coverage is not None and detector_valid_total != coverage["valid_pixel_count"]:
            raise Phase2A4PackageIntegrityError(
                "detector-valid contributing pixels do not equal detector coverage"
            )
        if selected_total > pixel_count:
            raise Phase2A4PackageIntegrityError(
                "selected composition pixels exceed the fixed case window"
            )
    all_cells = {cell["blind_cell_id"] for cell in sidecar["factorial_results"]}
    for family in METHOD_FAMILIES:
        comparison = sidecar["comparisons"][family]
        a = set(comparison["option_a"]["blind_cell_ids"])
        b = set(comparison["option_b"]["blind_cell_ids"])
        if len(a) != 4 or len(b) != 4 or a & b or a | b != all_cells:
            raise Phase2A4PackageIntegrityError("comparison options do not partition eight paired strata")
        if comparison["selected_or_activated"] is not False:
            raise Phase2A4PackageIntegrityError("method was selected or activated")


def validate_phase2a4_derivative_package(
    package_root: Path,
    *,
    parent_root: Path | None = None,
    registry_path: Path | None = None,
    rainfall_root: Path | None = None,
    evidence_root: Path | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Deeply validate the derivative and optional immutable source bindings."""
    root = Path(package_root).resolve()
    if not root.is_dir():
        raise Phase2A4PackageIntegrityError(f"package directory does not exist: {root}")
    manifest = _load_json(root / "manifest.json", error_type=Phase2A4PackageIntegrityError)
    _verify_checksum_artifact(root, manifest, error_type=Phase2A4PackageIntegrityError)
    manifest_schema = _load_json(root / "schemas" / "phase2a4-derivative-manifest-v1.schema.json", error_type=Phase2A4PackageIntegrityError)
    method_schema = _load_json(root / "schemas" / "phase2a4-method-evidence-v1.schema.json", error_type=Phase2A4PackageIntegrityError)
    registry_schema = _load_json(root / "schemas" / "phase2a4-candidate-registry-v1.schema.json", error_type=Phase2A4PackageIntegrityError)
    review_schema = _load_json(root / "schemas" / "validation-review-v1.schema.json", error_type=Phase2A4PackageIntegrityError)
    review_export_schema = _load_json(root / "schemas" / "phase2a4-review-export-v1.schema.json", error_type=Phase2A4PackageIntegrityError)
    _validate_schema(manifest, manifest_schema, "derivative manifest")
    Draft202012Validator.check_schema(method_schema)
    Draft202012Validator.check_schema(registry_schema)
    Draft202012Validator.check_schema(review_schema)
    Draft202012Validator.check_schema(review_export_schema)
    if manifest["artifact_inventory"] != _inventory(root):
        raise Phase2A4PackageIntegrityError("manifest artifact inventory is not canonical")
    registry = _load_json(root / REGISTRY_RELATIVE_PATH, error_type=Phase2A4PackageIntegrityError)
    _validate_schema(registry, registry_schema, "candidate registry")
    candidates, registry_cells = _registry_index(registry)
    registry_artifact = _artifact(root / REGISTRY_RELATIVE_PATH, root)
    if manifest["registry_binding"] != {
        "registry_id": REGISTRY_ID,
        "registry_version": SCHEMA_VERSION,
        **registry_artifact,
    }:
        raise Phase2A4PackageIntegrityError("manifest registry binding mismatch")
    expected_schema_bindings = {
        "candidate_registry": _schema_binding(root / "schemas" / "phase2a4-candidate-registry-v1.schema.json", root),
        "method_evidence": _schema_binding(root / "schemas" / "phase2a4-method-evidence-v1.schema.json", root),
        "derivative_manifest": _schema_binding(root / "schemas" / "phase2a4-derivative-manifest-v1.schema.json", root),
        "phase2a4_review_export": _schema_binding(root / "schemas" / "phase2a4-review-export-v1.schema.json", root),
        "phase2a3_review": _schema_binding(root / "schemas" / "validation-review-v1.schema.json", root),
    }
    if manifest["schema_bindings"] != expected_schema_bindings:
        raise Phase2A4PackageIntegrityError("manifest schema bindings do not reconcile")
    mapping = _load_json(
        root / "coordinator" / "blinding-map.json",
        error_type=Phase2A4PackageIntegrityError,
    )
    _validate_package_identity_binding(manifest, mapping)
    try:
        validate_phase2a4_evidence_artifact(
            root / "coordinator" / "candidate-evidence",
            candidate_registry_path=root / REGISTRY_RELATIVE_PATH,
            rainfall_artifact_dir=root / "coordinator" / "rainfall-reference",
        )
    except Exception as exc:
        raise Phase2A4PackageIntegrityError(
            f"packaged candidate evidence failed deep validation: {exc}"
        ) from exc
    _validate_packaged_evidence_mapping_binding(
        mapping, root / "coordinator" / "candidate-evidence"
    )
    sidecars: dict[str, dict[str, Any]] = {}
    sidecar_paths = sorted((root / "coordinator" / "method-evidence").glob("*.json"))
    if len(sidecar_paths) != 60:
        raise Phase2A4PackageIntegrityError("coordinator must contain exactly 60 method sidecars")
    for path in sidecar_paths:
        sidecar = _load_json(path, error_type=Phase2A4PackageIntegrityError)
        _validate_schema(sidecar, method_schema, f"method evidence {path.name}")
        blind = sidecar["parent_case"]["blind_case_id"]
        if blind in sidecars or path.stem != blind:
            raise Phase2A4PackageIntegrityError("duplicate or misnamed method sidecar")
        if sidecar["derivative_package_id"] != manifest["package_id"]:
            raise Phase2A4PackageIntegrityError("sidecar package binding mismatch")
        _validate_sidecar_semantics(sidecar, root / "reviewer-a")
        sidecars[blind] = sidecar
    if set(sidecars) != {case["blind_case_id"] for case in mapping["cases"]}:
        raise Phase2A4PackageIntegrityError("mapping and sidecar case populations differ")
    _validate_mapping(mapping, registry=registry, sidecars=sidecars)
    _validate_overlap(root)
    _reviewer_leakage_scan(root, registry=registry, mapping=mapping)

    for slot in REVIEWER_SLOTS:
        assignment = _load_json(root / slot / "assignment.json", error_type=Phase2A4PackageIntegrityError)
        reviews = _load_json(root / slot / "review-template.json", error_type=Phase2A4PackageIntegrityError)
        ui = _load_json(root / slot / "method-evidence" / "index.json", error_type=Phase2A4PackageIntegrityError)
        cases = [
            _load_json(root / slot / "cases" / f"{blind}.json", error_type=Phase2A4PackageIntegrityError)
            for blind in assignment["blind_case_ids"]
        ]
        expected_html = _html_document(
            reviewer_slot=slot,
            cases=cases,
            reviews=reviews["reviews"],
            method_evidence=ui,
            package_phase="phase2a4",
            package_binding=_review_package_binding(root, slot, manifest["package_id"]),
        )
        if (root / slot / "index.html").read_text(encoding="utf-8") != expected_html:
            raise Phase2A4PackageIntegrityError(f"{slot} HTML payload does not reconcile")
        for review in reviews["reviews"]:
            _validate_schema(review, review_schema, f"{slot} review template")
            _assert_blank_review(review)
            blind = review["blind_case_id"]
            if review != next(case["review_fields"] for case in cases if case["blind_case_id"] == blind):
                raise Phase2A4PackageIntegrityError(f"{slot} case/template review mismatch: {blind}")
            if _load_json(root / slot / "method-evidence" / f"{blind}.json", error_type=Phase2A4PackageIntegrityError) != sidecars[blind]:
                raise Phase2A4PackageIntegrityError(f"{slot} sidecar differs from coordinator: {blind}")

    actual_counts = Counter(cell["availability"] for value in sidecars.values() for cell in value["factorial_results"])
    if manifest["case_population"]["evidence_status_counts"] != dict(sorted(actual_counts.items())):
        raise Phase2A4PackageIntegrityError("manifest evidence status counts mismatch")
    if manifest["case_population"]["blind_case_ids_sha256"] != canonical_sha256(sorted(sidecars)):
        raise Phase2A4PackageIntegrityError("manifest blind-case population hash mismatch")

    if parent_root is not None:
        parent = Path(parent_root).resolve()
        validate_validation_package(parent)
        parent_manifest, parent_index = _parent_index(parent)
        if set(parent_index) != set(sidecars):
            raise Phase2A4PackageIntegrityError("derivative case population changed from parent")
        if manifest["parent_binding"]["parent_artifact_inventory_sha256"] != _inventory_digest(parent_manifest["artifact_inventory"]):
            raise Phase2A4PackageIntegrityError("parent artifact-inventory binding mismatch")
        for blind, sidecar in sidecars.items():
            expected = parent_index[blind]
            parent_case = sidecar["parent_case"]
            if (
                parent_case["target_date"] != expected["target_date"]
                or parent_case["target_geometry_sha256"] != expected["target_geometry_sha256"]
                or parent_case["canonical_observation_id"] is not None
                or parent_case["canonical_event_id"] is not None
            ):
                raise Phase2A4PackageIntegrityError(f"parent case binding mismatch: {blind}")
        _compare_parent_review_material(root, parent)
    if registry_path is not None and (root / REGISTRY_RELATIVE_PATH).read_bytes() != Path(registry_path).resolve().read_bytes():
        raise Phase2A4PackageIntegrityError("packaged registry differs from source registry")
    if rainfall_root is not None:
        rainfall = validate_rainfall_reference_artifact(Path(rainfall_root).resolve())
        source = manifest["source_provenance"]
        if (
            source["rainfall_artifact_id"] != rainfall["artifact_id"]
            or source["rainfall_manifest_sha256"] != sha256_file(Path(rainfall_root).resolve() / "manifest.json")
            or source["rainfall_plan_sha256"] != rainfall["plan_sha256"]
        ):
            raise Phase2A4PackageIntegrityError("rainfall source binding mismatch")
        packaged = root / "coordinator" / "rainfall-reference"
        for relative in ("manifest.json", "CHECKSUMS.sha256"):
            if (packaged / relative).read_bytes() != (Path(rainfall_root).resolve() / relative).read_bytes():
                raise Phase2A4PackageIntegrityError("packaged rainfall artifact differs from source")
    if evidence_root is not None:
        source = Path(evidence_root).resolve()
        if registry_path is None or rainfall_root is None:
            raise Phase2A4PackageIntegrityError(
                "deep candidate-evidence validation requires registry and rainfall sources"
            )
        try:
            validate_phase2a4_evidence_artifact(
                source,
                parent_package_dir=parent_root,
                candidate_registry_path=registry_path,
                rainfall_artifact_dir=rainfall_root,
                baseline_manifest_path=(
                    Path(repository_root).resolve() / "config/baseline_manifest_v1.json"
                    if repository_root is not None
                    else None
                ),
                repository_root=repository_root,
            )
        except Exception as exc:
            raise Phase2A4PackageIntegrityError(
                f"candidate evidence deep validation failed: {exc}"
            ) from exc
        if mapping["blinding_derivation"]["coordinator_only_evidence_checksums_sha256"] != sha256_file(source / "CHECKSUMS.sha256"):
            raise Phase2A4PackageIntegrityError("candidate-evidence blinding input mismatch")
        packaged = root / "coordinator" / "candidate-evidence"
        for relative in ("manifest.json", "CHECKSUMS.sha256"):
            if (packaged / relative).read_bytes() != (source / relative).read_bytes():
                raise Phase2A4PackageIntegrityError("packaged candidate evidence differs from source")
    if repository_root is not None:
        expected = _source_inventory(Path(repository_root).resolve())
        if (
            manifest["generator_source_inventory"] != expected
            or manifest["runtime_versions"] != _phase2a4_runtime_versions()
        ):
            raise Phase2A4PackageIntegrityError(
                "generator source or runtime inventory mismatch"
            )
    return manifest


def _primary_snapshot(review: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "change_assessment": copy.deepcopy(review["change_assessment"]),
        "temporal_assessment": copy.deepcopy(review["temporal_assessment"]),
        "land_cover_assessment": copy.deepcopy(review["land_cover_assessment"]),
    }


def _primary_assessment_complete(review: Mapping[str, Any]) -> bool:
    change = review.get("change_assessment", {})
    temporal = review.get("temporal_assessment", {})
    land_cover = review.get("land_cover_assessment", {})
    return all(
        (
            change.get("change_label"),
            change.get("reason"),
            change.get("evidence_sufficiency"),
            temporal.get("confidence"),
            temporal.get("reason"),
            land_cover.get("context"),
            land_cover.get("confidence"),
            land_cover.get("reason"),
        )
    )


def _method_assessment_started(review: Mapping[str, Any]) -> bool:
    methods = review.get("method_comparisons", {})
    return any(
        any(methods.get(family, {}).get(field) for field in ("preference", "reviewer_confidence", "evidence_reason"))
        for family in (*METHOD_FAMILIES, *PRESERVED_METHOD_FAMILIES)
    )


def _immutable_method_metadata(method: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(method.get(key))
        for key in (
            "availability",
            "option_a",
            "option_b",
            "display_order",
            "selected_or_activated",
        )
    }


def validate_phase2a4_review_export(
    package_root: Path,
    review_export_path: Path,
) -> dict[str, Any]:
    """Validate one package-bound isolated review without accuracy inference."""
    root = Path(package_root).resolve()
    export_path = Path(review_export_path).resolve()
    manifest = validate_phase2a4_derivative_package(root)
    export = _load_json(export_path, error_type=Phase2A4PackageIntegrityError)
    export_schema = _load_json(
        root / "schemas" / "phase2a4-review-export-v1.schema.json",
        error_type=Phase2A4PackageIntegrityError,
    )
    _validate_schema(export, export_schema, export_path.name)
    slot = export["reviewer_slot"]
    reviewer_root = root / slot
    expected_binding = _review_package_binding(root, slot, manifest["package_id"])
    if export["package_binding"] != expected_binding:
        raise Phase2A4PackageIntegrityError(
            "review export is bound to a different derivative package or template"
        )

    assignment = _load_json(
        reviewer_root / "assignment.json", error_type=Phase2A4PackageIntegrityError
    )
    expected_ids = assignment["blind_case_ids"]
    reviews = export["reviews"]
    review_ids = [review.get("blind_case_id") for review in reviews]
    reveal_state = export["reveal_state"]
    reveal_ids = [item.get("blind_case_id") for item in reveal_state]
    if review_ids != expected_ids or reveal_ids != expected_ids:
        raise Phase2A4PackageIntegrityError(
            "review and reveal-state IDs/order do not match the isolated assignment"
        )

    review_schema = _load_json(
        root / "schemas" / "validation-review-v1.schema.json",
        error_type=Phase2A4PackageIntegrityError,
    )
    template = _load_json(
        reviewer_root / "review-template.json",
        error_type=Phase2A4PackageIntegrityError,
    )
    template_by_id = {item["blind_case_id"]: item for item in template["reviews"]}
    status_counts: Counter[str] = Counter()
    for review, reveal in zip(reviews, reveal_state, strict=True):
        blind = review["blind_case_id"]
        _validate_schema(review, review_schema, f"{export_path.name}:{blind}")
        original = template_by_id[blind]
        for family in (*METHOD_FAMILIES, *PRESERVED_METHOD_FAMILIES):
            actual_method = review["method_comparisons"][family]
            original_method = original["method_comparisons"][family]
            if _immutable_method_metadata(actual_method) != _immutable_method_metadata(original_method):
                raise Phase2A4PackageIntegrityError(
                    f"review export changed immutable method metadata: {blind}/{family}"
                )
        revealed = reveal["revealed"]
        locked = reveal["locked_primary"]
        if revealed:
            if not _primary_assessment_complete(review) or locked != _primary_snapshot(review):
                raise Phase2A4PackageIntegrityError(
                    f"revealed method evidence does not preserve the locked primary assessment: {blind}"
                )
        elif locked is not None or _method_assessment_started(review):
            raise Phase2A4PackageIntegrityError(
                f"method assessment or primary lock precedes reveal: {blind}"
            )
        if _method_assessment_started(review) and not revealed:
            raise Phase2A4PackageIntegrityError(f"method assessment precedes reveal: {blind}")
        if review["review_status"] == "complete":
            if not (
                review["reviewer"]["pseudonymous_id"]
                and review["reviewer"]["qualification_attested"]
                and review["reviewer"]["independence_attested"]
            ):
                raise Phase2A4PackageIntegrityError(
                    f"complete review lacks reviewer identity/attestations: {blind}"
                )
            for family in (*METHOD_FAMILIES, *PRESERVED_METHOD_FAMILIES):
                method = review["method_comparisons"][family]
                if method["availability"] != "not_generated_in_2a3" and not all(
                    (method["preference"], method["reviewer_confidence"], method["evidence_reason"])
                ):
                    raise Phase2A4PackageIntegrityError(
                        f"complete review lacks generated method assessment: {blind}/{family}"
                    )
        status_counts[review["review_status"]] += 1
    reviewer_ids = {
        review["reviewer"]["pseudonymous_id"]
        for review in reviews
        if review["reviewer"]["pseudonymous_id"] is not None
    }
    if len(reviewer_ids) > 1:
        raise Phase2A4PackageIntegrityError(
            "one reviewer export contains multiple pseudonymous reviewer IDs"
        )
    return {
        "reviewer_slot": slot,
        "assigned_case_count": len(reviews),
        "revealed_case_count": sum(item["revealed"] for item in reveal_state),
        "status_counts": dict(sorted(status_counts.items())),
        "claim_scope": "review_process_validation_only_no_accuracy_metrics",
        "status": "valid",
    }


__all__ = [
    "Phase2A4PackageError",
    "Phase2A4PackageIntegrityError",
    "build_phase2a4_derivative_package",
    "deterministic_blind_mapping",
    "validate_phase2a4_derivative_package",
    "validate_phase2a4_review_export",
]
