"""Build and validate the additive Phase 2A.5 blinded review derivative.

The Phase 2A.3 validation package and Phase 2A.4 method-comparison derivative
are immutable inputs.  This module validates both, copies the Phase 2A.4 tree,
and adds only blinded MapBiomas and contextual-signature comparisons.  The
Phase 2A.4 candidate registry and blinding map are deliberately treated as
opaque bytes here: they are neither parsed nor rewritten.
"""

from __future__ import annotations

import copy
import datetime as dt
import html
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

from jsonschema import Draft202012Validator, FormatChecker

from src.detection.baseline_manifest import sha256_file
from src.detection.identity import canonical_sha256, identity_sha256
from src.validation.package import _runtime_versions, write_canonical_json
from src.validation.phase2a4_package import validate_phase2a4_derivative_package
from src.validation.validator import validate_validation_package


SCHEMA_VERSION = "1.0.0"
PACKAGE_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a5-derivative-manifest-v1.schema.json"
)
EVIDENCE_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a5-method-evidence-v1.schema.json"
)
REVIEW_EXPORT_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a5-review-export-v1.schema.json"
)
PACKAGE_ID_PREFIX = "p2a5-derivative-package-v1-"
EVIDENCE_ID_PREFIX = "p2a5-method-evidence-v1-"
MAPPING_ID_PREFIX = "p2a5-blinding-map-v1-"
BLIND_OPTION_PREFIX = "p2a5-blind-option-v1-"
NEW_METHOD_FAMILIES = ("mapbiomas", "contextual_signature")
PRESERVED_METHOD_FAMILIES = (
    "cloud_mask",
    "daily_composition",
    "drought_adjustment",
)
ALL_METHOD_FAMILIES = PRESERVED_METHOD_FAMILIES + NEW_METHOD_FAMILIES
REVIEWER_SLOTS = ("reviewer-a", "reviewer-b")
CHECKSUM_LINE = re.compile(r"^(?P<sha>[0-9a-f]{64})  (?P<path>[^\n]+)$")
BLIND_CASE_PATTERN = re.compile(r"^p2a3-blind-v1-[0-9a-f]{24}$")
SAMPLE_ID_PREFIX = "p2a3-sample-v1-"
ACCEPTED_PHASE2A4_PACKAGE_ID = (
    "p2a4-derivative-package-v1-"
    "b229831f12841d1f1c3e0676726835fa04242855f3927c2228cd91d7490a2bf1"
)
ACCEPTED_PHASE2A4_MANIFEST_SHA256 = (
    "561ded42bc6c73bff5fbf0269d7f4283900d54ea10993527b63ed8899ed38d03"
)
ACCEPTED_PHASE2A4_CHECKSUMS_SHA256 = (
    "ca77890baf12765dcfb789e2a5bb25b8faaf8f533586c6b393f96758c28ec900"
)
ALLOWED_PANEL_STATUS = {
    "available",
    "partial",
    "unreviewable",
    "unavailable",
    "missing",
    "error",
}
INTENTIONALLY_REPLACED_PHASE2A4_PATHS = {
    f"{slot}/{name}"
    for slot in REVIEWER_SLOTS
    for name in ("index.html", "review-template.json", "reviewer.js")
}
GENERATOR_SOURCE_PATHS = (
    "src/detection/baseline_manifest.py",
    "src/detection/identity.py",
    "src/validation/package.py",
    "src/validation/validator.py",
    "src/validation/phase2a4_package.py",
    "src/validation/phase2a5_context.py",
    "src/validation/phase2a5_evidence.py",
    "src/validation/phase2a5_package.py",
    "scripts/build_phase2a5_method_package.py",
    "scripts/validate_phase2a5_method_package.py",
    "scripts/validate_phase2a5_reviews.py",
    "docs/contracts/phase2a/phase2a5-reviewer.js",
    "docs/contracts/phase2a/PHASE_2A5_CONTEXT_COMPARISON_V1.md",
    "docs/contracts/phase2a/PHASE_2A5_REVIEWER_PROTOCOL_V1.md",
    "docs/contracts/phase2a/schemas/phase2a5-method-evidence-v1.schema.json",
    "docs/contracts/phase2a/schemas/phase2a5-derivative-manifest-v1.schema.json",
    "docs/contracts/phase2a/schemas/phase2a5-review-export-v1.schema.json",
)
PACKAGED_GENERATOR_MATERIAL = {
    "docs/contracts/phase2a/phase2a5-reviewer.js": (
        "reviewer-a/reviewer.js",
        "reviewer-b/reviewer.js",
    ),
    "docs/contracts/phase2a/PHASE_2A5_CONTEXT_COMPARISON_V1.md": (
        "PHASE2A5_CONTEXT_COMPARISON.md",
    ),
    "docs/contracts/phase2a/PHASE_2A5_REVIEWER_PROTOCOL_V1.md": (
        "reviewer-a/CONTEXT_PROTOCOL.md",
        "reviewer-b/CONTEXT_PROTOCOL.md",
    ),
    "docs/contracts/phase2a/schemas/phase2a5-method-evidence-v1.schema.json": (
        "schemas/phase2a5-method-evidence-v1.schema.json",
    ),
    "docs/contracts/phase2a/schemas/phase2a5-derivative-manifest-v1.schema.json": (
        "schemas/phase2a5-derivative-manifest-v1.schema.json",
    ),
    "docs/contracts/phase2a/schemas/phase2a5-review-export-v1.schema.json": (
        "schemas/phase2a5-review-export-v1.schema.json",
    ),
}


class Phase2A5PackageError(ValueError):
    """Raised when a build input violates a Phase 2A.5 boundary."""


class Phase2A5PackageIntegrityError(Phase2A5PackageError):
    """Raised when a Phase 2A.5 derivative fails deep reconciliation."""


def _acquire_build_lock(target: Path) -> Path:
    """Reserve one sibling lock without replacing a stale or active lock."""
    lock = target.parent / f".{target.name}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise Phase2A5PackageError(
            f"exclusive build lock already exists; refusing to continue: {lock}"
        ) from exc
    except OSError as exc:
        raise Phase2A5PackageError(
            f"cannot create exclusive build lock {lock}: {exc}"
        ) from exc
    try:
        os.write(descriptor, f"target={target.name}\n".encode("utf-8"))
    except OSError as exc:
        try:
            lock.unlink()
        except OSError:
            pass
        raise Phase2A5PackageError(
            f"cannot initialize exclusive build lock {lock}: {exc}"
        ) from exc
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
        raise Phase2A5PackageError(
            f"output appeared during construction; refusing to overwrite: {target}"
        )
    try:
        staging.rename(target)
    except FileExistsError as exc:
        raise Phase2A5PackageError(
            f"output appeared during construction; refusing to overwrite: {target}"
        ) from exc
    except OSError as exc:
        raise Phase2A5PackageError(
            f"cannot publish derivative package {target}: {exc}"
        ) from exc


def _load_json(
    path: Path, *, error_type: type[ValueError] = Phase2A5PackageError
) -> Any:
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


def _schema_binding(path: Path, root: Path) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **_artifact(path, root)}


def _method_artifact(path: Path, root: Path) -> dict[str, Any]:
    return {
        **_artifact(path, root),
        "media_type": mimetypes.guess_type(path.name)[0]
        or "application/octet-stream",
        "role": "blinded_context_comparison_panel",
    }


def _safe_path(
    root: Path, relative: str, *, error_type: type[ValueError]
) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise error_type(f"unsafe artifact path: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise error_type(f"artifact path escapes root: {relative}") from exc
    return resolved


def _validate_schema(
    value: Any,
    schema: Mapping[str, Any],
    label: str,
    *,
    error_type: type[ValueError] = Phase2A5PackageIntegrityError,
) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise error_type(f"{label} schema violation at {location}: {first.message}")


def _parse_timestamp(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise Phase2A5PackageError(f"{label} must be an RFC 3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise Phase2A5PackageError(
            f"{label} must be an RFC 3339 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise Phase2A5PackageError(f"{label} must include an offset")
    return value


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
    if any(not isinstance(path, str) for path in paths) or len(paths) != len(
        set(paths)
    ):
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
        *(
            {"path": item["path"], "sha256": item["sha256"]}
            for item in inventory
        ),
    ]
    payload = "".join(
        f"{item['sha256']}  {item['path']}\n"
        for item in sorted(entries, key=lambda item: item["path"])
    )
    (root / "CHECKSUMS.sha256").write_text(payload, encoding="utf-8", newline="\n")


def _source_inventory(repository_root: Path) -> list[dict[str, Any]]:
    paths = tuple(repository_root / relative for relative in GENERATOR_SOURCE_PATHS)
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise Phase2A5PackageError(f"package generator source missing: {missing}")
    return [_artifact(path, repository_root) for path in paths]


def _phase2a5_runtime_versions() -> dict[str, str]:
    return {**_runtime_versions(), "phase2a5_package_python": platform.python_version()}


def _validate_packaged_generator_material(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    repository_root: Path,
) -> None:
    inventory = manifest.get("generator_source_inventory")
    if not isinstance(inventory, list) or [
        item.get("path") for item in inventory if isinstance(item, Mapping)
    ] != list(GENERATOR_SOURCE_PATHS):
        raise Phase2A5PackageIntegrityError(
            "generator source inventory paths or deterministic order changed"
        )
    by_path = {item["path"]: item for item in inventory}
    if len(by_path) != len(GENERATOR_SOURCE_PATHS):
        raise Phase2A5PackageIntegrityError(
            "generator source inventory contains duplicate paths"
        )
    if inventory != _source_inventory(Path(repository_root).resolve()):
        raise Phase2A5PackageIntegrityError(
            "generator source inventory differs from canonical repository bytes"
        )
    for source, destinations in PACKAGED_GENERATOR_MATERIAL.items():
        expected = by_path[source]
        for relative in destinations:
            destination = root / relative
            if (
                not destination.is_file()
                or destination.stat().st_size != expected.get("bytes")
                or sha256_file(destination) != expected.get("sha256")
            ):
                raise Phase2A5PackageIntegrityError(
                    f"packaged generator material differs from its source binding: {relative}"
                )


def _parent_case_index(
    phase2a3_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    manifest = _load_json(phase2a3_root / "manifest.json")
    crosswalk = _load_json(phase2a3_root / "coordinator/crosswalk.json")
    mappings = crosswalk.get("mappings")
    if not isinstance(mappings, list) or len(mappings) != 60:
        raise Phase2A5PackageError(
            "Phase 2A.3 crosswalk must retain exactly 60 cases"
        )
    result: dict[str, dict[str, str]] = {}
    for mapping in mappings:
        blind = mapping.get("blind_case_id")
        sample = mapping.get("sample_id")
        if (
            not isinstance(blind, str)
            or not BLIND_CASE_PATTERN.fullmatch(blind)
            or not isinstance(sample, str)
            or not sample.startswith(SAMPLE_ID_PREFIX)
            or blind in result
        ):
            raise Phase2A5PackageError("invalid Phase 2A.3 crosswalk mapping")
        result[blind] = {"blind_case_id": blind, "sample_id": sample}
    if len(result) != 60:
        raise Phase2A5PackageError("duplicate Phase 2A.3 blind case identity")
    return manifest, result


def _candidate_ids(registry: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    family_records = {
        "mapbiomas": registry.get("strong_subset"),
        "contextual_signature": registry.get("contextual_signature"),
    }
    legacy_families = registry.get("families")
    if isinstance(legacy_families, Mapping):
        family_records = {
            family: legacy_families.get(family) for family in NEW_METHOD_FAMILIES
        }
    output: dict[str, tuple[str, str]] = {}
    for family in NEW_METHOD_FAMILIES:
        family_record = family_records.get(family)
        if not isinstance(family_record, Mapping):
            raise Phase2A5PackageError(f"registry family is missing: {family}")
        ids = family_record.get("candidate_ids")
        if not isinstance(ids, list):
            candidates = family_record.get("candidates")
            if isinstance(candidates, list):
                ids = [item.get("candidate_id") for item in candidates]
        if (
            not isinstance(ids, list)
            or len(ids) != 2
            or len(set(ids)) != 2
            or any(not isinstance(item, str) or not item for item in ids)
        ):
            raise Phase2A5PackageError(
                f"{family} must define exactly two unique candidate IDs"
            )
        output[family] = (ids[0], ids[1])
    return output


def deterministic_phase2a5_blind_mapping(
    blind_case_ids: Sequence[str],
    candidate_ids: Mapping[str, Sequence[str]],
    *,
    blinding_key: str,
) -> dict[str, dict[str, dict[str, str]]]:
    """Create an order-invariant, exact 30/30 keyed A/B mapping."""
    ids = sorted(blind_case_ids)
    if len(ids) != 60 or len(set(ids)) != 60:
        raise Phase2A5PackageError(
            "balanced Phase 2A.5 blinding requires exactly 60 unique cases"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", blinding_key):
        raise Phase2A5PackageError("blinding key must be a SHA-256 digest")
    result: dict[str, dict[str, dict[str, str]]] = {blind: {} for blind in ids}
    for family in NEW_METHOD_FAMILIES:
        pair = tuple(candidate_ids.get(family, ()))
        if len(pair) != 2 or len(set(pair)) != 2:
            raise Phase2A5PackageError(f"{family} does not have two candidates")
        ranked = sorted(
            ids,
            key=lambda blind: identity_sha256(
                "phase2a5-balanced-option-order-v1",
                blinding_key,
                family,
                blind,
            ),
        )
        first_is_a = set(ranked[:30])
        for blind in ids:
            a, b = pair if blind in first_is_a else (pair[1], pair[0])
            result[blind][family] = {"A": a, "B": b}
    return result


def _blind_option_id(
    blinding_key: str, blind: str, family: str, candidate_id: str
) -> str:
    return BLIND_OPTION_PREFIX + identity_sha256(
        "phase2a5-blind-option-v1",
        blinding_key,
        blind,
        family,
        candidate_id,
    )[:24]


def _record_artifact(descriptor: Mapping[str, Any]) -> Mapping[str, Any]:
    record = descriptor.get("record")
    if record is None:
        record = descriptor.get("case_evidence")
    if not isinstance(record, Mapping):
        raise Phase2A5PackageError("evidence case descriptor lacks a record artifact")
    return record


def _verify_input_artifact(
    root: Path, artifact: Mapping[str, Any], *, label: str
) -> Path:
    path_value = artifact.get("path")
    if not isinstance(path_value, str):
        raise Phase2A5PackageError(f"{label} path is missing")
    path = _safe_path(root, path_value, error_type=Phase2A5PackageError)
    if (
        not path.is_file()
        or path.stat().st_size != artifact.get("bytes")
        or sha256_file(path) != artifact.get("sha256")
    ):
        raise Phase2A5PackageError(f"{label} checksum mismatch")
    return path


def _assert_no_human_or_decision_claim(record: Mapping[str, Any]) -> None:
    forbidden_truthy = {
        "qualified_human_label_present",
        "qualified_human_labels_present",
        "scientific_accuracy_claim",
        "selected_or_activated",
        "method_selected_or_activated",
        "policy_selected_or_frozen",
        "threshold_selected",
        "raw_detection_modified",
        "case_replaced",
        "canonical_identity_inferred",
    }

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key in forbidden_truthy and nested is not False:
                    raise Phase2A5PackageError(
                        f"candidate evidence exceeds provisional boundary: {key}"
                    )
                if key in {
                    "qualified_label",
                    "accepted_label",
                    "selected_candidate_id",
                    "selected_strong_subset_candidate_id",
                    "selected_contextual_signature_candidate_id",
                    "accepted_policy_id",
                    "accepted_observation_id",
                    "accepted_event_id",
                    "public_wording_approval",
                    "acceptance_record_id",
                } and nested is not None:
                    raise Phase2A5PackageError(
                        f"candidate evidence contains a decision or label: {key}"
                    )
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(record)


def _load_phase2a5_evidence(
    evidence_root: Path,
    *,
    parent_by_blind: Mapping[str, Mapping[str, str]],
    candidate_ids: Mapping[str, tuple[str, str]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    manifest = _load_json(evidence_root / "manifest.json")
    manifest_schema_path = (
        evidence_root
        / "schemas/phase2a5-context-evidence-manifest-v1.schema.json"
    )
    case_schema_path = (
        evidence_root / "schemas/phase2a5-context-evidence-case-v1.schema.json"
    )
    if not manifest_schema_path.is_file() or not case_schema_path.is_file():
        raise Phase2A5PackageError(
            "Phase 2A.5 evidence schemas are missing from the artifact"
        )
    manifest_schema = _load_json(manifest_schema_path)
    case_schema = _load_json(case_schema_path)
    _validate_schema(
        manifest,
        manifest_schema,
        "Phase 2A.5 evidence manifest",
        error_type=Phase2A5PackageError,
    )
    _verify_checksum_artifact(
        evidence_root, manifest, error_type=Phase2A5PackageError
    )
    descriptors = manifest.get("cases")
    if not isinstance(descriptors, list) or len(descriptors) != 60:
        raise Phase2A5PackageError(
            "Phase 2A.5 evidence must retain exactly 60 case descriptors"
        )
    if descriptors != sorted(descriptors, key=lambda item: item.get("blind_case_id", "")):
        raise Phase2A5PackageError("Phase 2A.5 evidence cases must be sorted")
    records: dict[str, dict[str, Any]] = {}
    for descriptor in descriptors:
        blind = descriptor.get("blind_case_id")
        sample = descriptor.get("sample_id")
        if (
            blind not in parent_by_blind
            or parent_by_blind[blind]["sample_id"] != sample
            or blind in records
        ):
            raise Phase2A5PackageError(
                "Phase 2A.5 evidence case population or mapping mismatch"
            )
        record_path = _verify_input_artifact(
            evidence_root, _record_artifact(descriptor), label=f"case {blind}"
        )
        record = _load_json(record_path)
        _validate_schema(
            record,
            case_schema,
            f"Phase 2A.5 evidence case {blind}",
            error_type=Phase2A5PackageError,
        )
        if record.get("sample_id") != sample or record.get("blind_case_id") != blind:
            raise Phase2A5PackageError(f"case evidence identity mismatch: {blind}")
        panels = record.get("candidate_panels")
        if not isinstance(panels, Mapping) or set(panels) != set(
            NEW_METHOD_FAMILIES
        ):
            raise Phase2A5PackageError(
                f"case evidence family inventory mismatch: {blind}"
            )
        for family in NEW_METHOD_FAMILIES:
            family_panels = panels[family]
            if not isinstance(family_panels, Mapping) or set(family_panels) != set(
                candidate_ids[family]
            ):
                raise Phase2A5PackageError(
                    f"case evidence candidate inventory mismatch: {blind}/{family}"
                )
            for candidate, panel in family_panels.items():
                if not isinstance(panel, Mapping):
                    raise Phase2A5PackageError(
                        f"invalid candidate panel: {blind}/{family}/{candidate}"
                    )
                status = panel.get("status")
                if status not in ALLOWED_PANEL_STATUS:
                    raise Phase2A5PackageError(
                        f"invalid panel status: {blind}/{family}/{candidate}"
                    )
                path_value = panel.get("path")
                if status in {"available", "partial"}:
                    _verify_input_artifact(
                        evidence_root,
                        panel,
                        label=f"panel {blind}/{family}/{candidate}",
                    )
                    if not isinstance(panel.get("media_type"), str):
                        raise Phase2A5PackageError(
                            f"panel media type is missing: {blind}/{family}/{candidate}"
                        )
                elif path_value is not None:
                    raise Phase2A5PackageError(
                        f"unreviewable panel names a path: {blind}/{family}/{candidate}"
                    )
        _assert_no_human_or_decision_claim(record)
        records[blind] = record
    if set(records) != set(parent_by_blind):
        raise Phase2A5PackageError(
            "Phase 2A.5 evidence silently replaced or omitted a frozen case"
        )
    _assert_no_human_or_decision_claim(manifest)
    return manifest, records, sha256_file(evidence_root / "CHECKSUMS.sha256")


def _deep_validate_phase2a5_evidence_source(
    *,
    evidence_root: Path,
    evidence_manifest: Mapping[str, Any],
    phase2a3_root: Path,
    registry_path: Path,
    context_manifest_path: Path,
    repository_root: Path,
) -> None:
    parent_record = evidence_manifest.get("parents", {}).get("phase2a4", {})
    parent_manifest_record = parent_record.get("manifest")
    if not isinstance(parent_manifest_record, Mapping) or not isinstance(
        parent_manifest_record.get("path"), str
    ):
        raise Phase2A5PackageError(
            "Phase 2A.5 evidence lacks its Phase 2A.4 provenance path"
        )
    parent_manifest_path = _safe_path(
        repository_root,
        parent_manifest_record["path"],
        error_type=Phase2A5PackageError,
    )
    if parent_manifest_path.name != "manifest.json":
        raise Phase2A5PackageError(
            "Phase 2A.5 evidence Phase 2A.4 binding is not a manifest"
        )
    if context_manifest_path.name != "manifest.json":
        raise Phase2A5PackageError(
            "Phase 2A.5 context input must be the artifact manifest.json"
        )
    try:
        from src.validation.phase2a5_evidence import (
            validate_phase2a5_evidence_artifact,
        )

        validated = validate_phase2a5_evidence_artifact(
            evidence_root,
            parent_phase2a3_dir=phase2a3_root,
            parent_phase2a4_dir=parent_manifest_path.parent,
            candidate_registry_path=registry_path,
            context_artifact_dir=context_manifest_path.parent,
            repository_root=repository_root,
        )
    except Exception as exc:
        raise Phase2A5PackageError(
            f"Phase 2A.5 source evidence failed deep validation: {exc}"
        ) from exc
    if validated != evidence_manifest:
        raise Phase2A5PackageError(
            "Phase 2A.5 evidence validator returned a different manifest"
        )


def _copy_verified_panel(
    evidence_root: Path,
    panel: Mapping[str, Any],
    destinations: Sequence[Path],
) -> None:
    source = _verify_input_artifact(evidence_root, panel, label="candidate panel")
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if sha256_file(destination) != panel["sha256"]:
            raise Phase2A5PackageError("copied candidate panel checksum mismatch")


def _comparison_availability(
    panels: Sequence[Mapping[str, Any]],
) -> tuple[str, str | None]:
    statuses = [panel.get("status") for panel in panels]
    if all(status == "available" for status in statuses):
        return "available", None
    if any(status in {"available", "partial"} for status in statuses):
        return "partial", "Evidence is partial and retained without replacement."
    return "unreviewable", "Evidence is unavailable and retained without replacement."


def _sidecar_payload_hash(sidecar: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(sidecar)
    payload["integrity"].pop("canonical_payload_sha256", None)
    return canonical_sha256(payload)


def _all_sidecar_artifacts(sidecar: Mapping[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for family in NEW_METHOD_FAMILIES:
        comparison = sidecar["comparisons"][family]
        for option_name in ("option_a", "option_b"):
            for artifact in comparison[option_name]["artifacts"]:
                if artifact not in artifacts:
                    artifacts.append(artifact)
    return sorted(artifacts, key=lambda item: item["path"])


def _build_case_material(
    *,
    package_root: Path,
    evidence_root: Path,
    record: Mapping[str, Any],
    package_id: str,
    labels: Mapping[str, Mapping[str, str]],
    blinding_key: str,
    overlap: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    blind = record["blind_case_id"]
    reviewer_roots = [package_root / "reviewer-a"]
    if overlap:
        reviewer_roots.append(package_root / "reviewer-b")
    comparisons: dict[str, Any] = {}
    methods: dict[str, Any] = {}
    mapping_families: dict[str, Any] = {}
    ui_families: dict[str, Any] = {}
    for family in NEW_METHOD_FAMILIES:
        family_panels = record["candidate_panels"][family]
        option_records: dict[str, Any] = {}
        option_ui: dict[str, Any] = {}
        mapping_families[family] = {}
        panels = []
        for label in ("A", "B"):
            candidate = labels[family][label]
            panel = family_panels[candidate]
            panels.append(panel)
            artifact: dict[str, Any] | None = None
            if panel["status"] in {"available", "partial"}:
                suffix = Path(panel["path"]).suffix.lower() or ".bin"
                relative = (
                    Path("context-evidence") / blind / family / f"{label}{suffix}"
                )
                destinations = [root / relative for root in reviewer_roots]
                _copy_verified_panel(evidence_root, panel, destinations)
                artifact = _method_artifact(
                    package_root / "reviewer-a" / relative,
                    package_root / "reviewer-a",
                )
            blind_option = _blind_option_id(
                blinding_key, blind, family, candidate
            )
            option_records[label] = {
                "blind_option_id": blind_option,
                "artifacts": [] if artifact is None else [artifact],
            }
            status = (
                panel["status"]
                if panel["status"] in {"available", "partial"}
                else "unreviewable"
            )
            option_ui[label] = {
                "status": status,
                "reason": (
                    None
                    if status == "available"
                    else "Evidence is incomplete and retained without replacement."
                ),
                "local_path": None if artifact is None else artifact["path"],
                "media_type": None if artifact is None else artifact["media_type"],
            }
            mapping_families[family][label] = {
                "candidate_id": candidate,
                "blind_option_id": blind_option,
                "source_panel": copy.deepcopy(dict(panel)),
            }
        availability, reason = _comparison_availability(panels)
        comparisons[family] = {
            "availability": availability,
            "reason": reason,
            "display_order": ["A", "B"],
            "option_a": option_records["A"],
            "option_b": option_records["B"],
            "primary_assessment_required_first": True,
            "selected_or_activated": False,
        }
        methods[family] = {
            "availability": availability,
            "option_a": option_records["A"]["blind_option_id"],
            "option_b": option_records["B"]["blind_option_id"],
            "display_order": ["A", "B"],
            "preference": None,
            "reviewer_confidence": None,
            "evidence_reason": None,
            "selected_or_activated": False,
        }
        ui_families[family] = {"options": option_ui}
    sidecar: dict[str, Any] = {
        "$schema": EVIDENCE_SCHEMA_URL,
        "schema_version": SCHEMA_VERSION,
        "evidence_id": EVIDENCE_ID_PREFIX
        + identity_sha256("phase2a5-method-evidence-v1", package_id, blind),
        "derivative_package_id": package_id,
        "scientific_status": "provisional_blinded_context_comparison_evidence",
        "parent_case": {
            "blind_case_id": blind,
            "canonical_observation_id": None,
            "canonical_event_id": None,
        },
        "comparisons": comparisons,
        "review_method_metadata": methods,
        "missing_evidence_policy": {
            "case_replaced": False,
            "missing_evidence_retained": True,
            "missing_interpreted_as_zero": False,
        },
        "claims": {
            "qualified_human_label_present": False,
            "scientific_accuracy_claim": False,
            "method_selected_or_activated": False,
            "raw_detection_modified": False,
            "canonical_identity_inferred": False,
            "cause_inferred": False,
        },
        "integrity": {
            "canonical_payload_sha256": "0" * 64,
            "canonical_payload_hash_rule": (
                "RFC8785_SHA256_with_integrity.canonical_payload_sha256_omitted"
            ),
            "artifact_inventory_sha256": "0" * 64,
            "parent_case_reconciled": True,
            "blinding_metadata_reconciled": True,
        },
    }
    sidecar["integrity"]["artifact_inventory_sha256"] = canonical_sha256(
        _all_sidecar_artifacts(sidecar)
    )
    sidecar["integrity"]["canonical_payload_sha256"] = _sidecar_payload_hash(
        sidecar
    )
    mapping_case = {
        "sample_id": record["sample_id"],
        "blind_case_id": blind,
        "double_review": overlap,
        "families": mapping_families,
    }
    ui = {"evidence_id": sidecar["evidence_id"], "families": ui_families}
    return sidecar, mapping_case, ui


def _assert_blank_review(review: Mapping[str, Any]) -> None:
    expected = {
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
    if any(review.get(key) != value for key, value in expected.items()):
        raise Phase2A5PackageIntegrityError(
            "review package contains a human assessment"
        )
    methods = review.get("method_comparisons")
    if not isinstance(methods, Mapping) or set(methods) != set(
        ALL_METHOD_FAMILIES
    ):
        raise Phase2A5PackageIntegrityError("review method inventory is invalid")
    for family in ALL_METHOD_FAMILIES:
        method = methods[family]
        if (
            any(
                method.get(key) is not None
                for key in ("preference", "reviewer_confidence", "evidence_reason")
            )
            or method.get("selected_or_activated") is not False
        ):
            raise Phase2A5PackageIntegrityError("method review is not blank")


def _review_package_binding(
    package_root: Path, slot: str, package_id: str, phase2a4_package_id: str
) -> dict[str, str]:
    reviewer_root = package_root / slot
    return {
        "package_id": package_id,
        "phase2a4_parent_package_id": phase2a4_package_id,
        "assignment_sha256": sha256_file(reviewer_root / "assignment.json"),
        "review_template_sha256": sha256_file(
            reviewer_root / "review-template.json"
        ),
        "method_evidence_index_sha256": sha256_file(
            reviewer_root / "method-evidence/index.json"
        ),
        "context_evidence_index_sha256": sha256_file(
            reviewer_root / "context-evidence/index.json"
        ),
        "review_schema_sha256": sha256_file(
            package_root / "schemas/validation-review-v1.schema.json"
        ),
    }


def _html_document(
    *,
    reviewer_slot: str,
    cases: Sequence[Mapping[str, Any]],
    reviews: Sequence[Mapping[str, Any]],
    method_evidence: Mapping[str, Any],
    context_evidence: Mapping[str, Any],
    package_binding: Mapping[str, Any],
) -> str:
    payload = json.dumps(
        {
            "package_phase": "phase2a5",
            "reviewer_slot": reviewer_slot,
            "cases": list(cases),
            "reviews": list(reviews),
            "method_evidence": dict(method_evidence),
            "context_evidence": dict(context_evidence),
            "package_binding": dict(package_binding),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    title = html.escape(f"Araripe Phase 2A.5 — {reviewer_slot}")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><link rel="stylesheet" href="reviewer.css"></head>
<body><header><strong>{title}</strong><div id="profile"></div><nav>
<button id="prev" type="button">Previous</button><span id="counter"></span>
<button id="next" type="button">Next</button><button id="export" type="button">Export review JSON</button>
<label class="import">Import/resume JSON <input id="import" type="file" accept="application/json"></label>
</nav></header><main><p class="warning">Provisional blinded comparison only. It is not a scientific accuracy result, cause attribution, method decision, or activation.</p>
<p id="progress"></p><div id="app"></div></main>
<script id="payload" type="application/json">{payload}</script><script src="reviewer.js"></script></body></html>"""


def _copy_phase2a4_parent(
    phase2a4_root: Path, staging: Path
) -> tuple[dict[str, Any], bytes, bytes]:
    manifest_bytes = (phase2a4_root / "manifest.json").read_bytes()
    checksums_bytes = (phase2a4_root / "CHECKSUMS.sha256").read_bytes()
    parent_manifest = json.loads(manifest_bytes)
    shutil.copytree(phase2a4_root, staging, dirs_exist_ok=True)
    parent_binding_root = staging / "coordinator/phase2a4-parent-binding"
    parent_binding_root.mkdir(parents=True, exist_ok=True)
    (parent_binding_root / "manifest.json").write_bytes(manifest_bytes)
    (parent_binding_root / "CHECKSUMS.sha256").write_bytes(checksums_bytes)
    for slot in REVIEWER_SLOTS:
        source = phase2a4_root / slot / "review-template.json"
        shutil.copyfile(source, parent_binding_root / f"{slot}-review-template.json")
    return parent_manifest, manifest_bytes, checksums_bytes


def _copy_new_sources(
    *,
    staging: Path,
    registry_path: Path,
    context_manifest_path: Path,
    evidence_root: Path,
) -> dict[str, dict[str, Any]]:
    coordinator_inputs = staging / "coordinator/phase2a5-inputs"
    coordinator_inputs.mkdir(parents=True, exist_ok=True)
    registry_destination = coordinator_inputs / "context-candidate-registry.json"
    context_destination = coordinator_inputs / "context-manifest.json"
    context_checksums_source = context_manifest_path.parent / "CHECKSUMS.sha256"
    context_checksums_destination = coordinator_inputs / "context-CHECKSUMS.sha256"
    if not context_checksums_source.is_file():
        raise Phase2A5PackageError(
            "Phase 2A.5 context checksum inventory is missing"
        )
    shutil.copyfile(registry_path, registry_destination)
    shutil.copyfile(context_manifest_path, context_destination)
    shutil.copyfile(context_checksums_source, context_checksums_destination)
    evidence_destination = staging / "coordinator/phase2a5-evidence"
    shutil.copytree(evidence_root, evidence_destination)
    return {
        "registry": _artifact(registry_destination, staging),
        "context_manifest": _artifact(context_destination, staging),
        "context_checksums": _artifact(context_checksums_destination, staging),
        "evidence_manifest": _artifact(evidence_destination / "manifest.json", staging),
        "evidence_checksums": _artifact(
            evidence_destination / "CHECKSUMS.sha256", staging
        ),
    }


def build_phase2a5_derivative_package(
    *,
    phase2a3_parent_root: Path,
    phase2a4_derivative_root: Path,
    registry_path: Path,
    context_manifest_path: Path,
    evidence_root: Path,
    output_root: Path,
    repository_root: Path,
    generated_at: str,
    generation_command: Sequence[str],
) -> dict[str, Any]:
    """Build a local-only Phase 2A.5 derivative without changing either parent."""
    phase2a3_parent_root = Path(phase2a3_parent_root).resolve()
    phase2a4_derivative_root = Path(phase2a4_derivative_root).resolve()
    registry_path = Path(registry_path).resolve()
    context_manifest_path = Path(context_manifest_path).resolve()
    evidence_root = Path(evidence_root).resolve()
    # Do not resolve the final destination component: a broken symlink is an
    # existing path for no-clobber purposes and must remain observable below.
    output_root = Path(output_root).absolute()
    repository_root = Path(repository_root).resolve()
    _parse_timestamp(generated_at, label="generated_at")
    if not generation_command or any(
        not isinstance(value, str) or not value for value in generation_command
    ):
        raise Phase2A5PackageError(
            "generation_command must contain non-empty strings"
        )
    if os.path.lexists(output_root):
        raise Phase2A5PackageError(
            "output directory already exists; refusing to overwrite"
        )
    for source in (
        phase2a3_parent_root,
        phase2a4_derivative_root,
        evidence_root,
        context_manifest_path.parent,
    ):
        try:
            output_root.relative_to(source)
        except ValueError:
            pass
        else:
            raise Phase2A5PackageError(
                "output directory must not be nested in an input artifact"
            )

    try:
        validate_validation_package(phase2a3_parent_root)
    except Exception as exc:
        raise Phase2A5PackageError(
            f"Phase 2A.3 parent failed validation: {exc}"
        ) from exc
    phase2a3_manifest, parent_by_blind = _parent_case_index(
        phase2a3_parent_root
    )
    try:
        phase2a4_manifest = validate_phase2a4_derivative_package(
            phase2a4_derivative_root, parent_root=phase2a3_parent_root
        )
    except Exception as exc:
        raise Phase2A5PackageError(
            f"Phase 2A.4 parent failed validation: {exc}"
        ) from exc
    if (
        phase2a4_manifest.get("package_id") != ACCEPTED_PHASE2A4_PACKAGE_ID
        or sha256_file(phase2a4_derivative_root / "manifest.json")
        != ACCEPTED_PHASE2A4_MANIFEST_SHA256
        or sha256_file(phase2a4_derivative_root / "CHECKSUMS.sha256")
        != ACCEPTED_PHASE2A4_CHECKSUMS_SHA256
    ):
        raise Phase2A5PackageError(
            "Phase 2A.4 input is not the exact frozen provenance-bound derivative"
        )
    registry = _load_json(registry_path)
    candidates = _candidate_ids(registry)
    context_manifest = _load_json(context_manifest_path)
    if not isinstance(context_manifest, Mapping):
        raise Phase2A5PackageError("context manifest must be a JSON object")
    evidence_manifest, evidence_records, blinding_key = _load_phase2a5_evidence(
        evidence_root,
        parent_by_blind=parent_by_blind,
        candidate_ids=candidates,
    )
    _deep_validate_phase2a5_evidence_source(
        evidence_root=evidence_root,
        evidence_manifest=evidence_manifest,
        phase2a3_root=phase2a3_parent_root,
        registry_path=registry_path,
        context_manifest_path=context_manifest_path,
        repository_root=repository_root,
    )
    labels = deterministic_phase2a5_blind_mapping(
        list(parent_by_blind), candidates, blinding_key=blinding_key
    )
    generator_inventory = _source_inventory(repository_root)
    runtime_versions = _phase2a5_runtime_versions()
    package_identity = {
        "pipeline": "phase2a5-derivative-package-v1",
        "phase2a3_manifest_sha256": sha256_file(
            phase2a3_parent_root / "manifest.json"
        ),
        "phase2a4_manifest_sha256": sha256_file(
            phase2a4_derivative_root / "manifest.json"
        ),
        "phase2a4_checksums_sha256": sha256_file(
            phase2a4_derivative_root / "CHECKSUMS.sha256"
        ),
        "registry_sha256": sha256_file(registry_path),
        "context_manifest_sha256": sha256_file(context_manifest_path),
        "context_checksums_sha256": sha256_file(
            context_manifest_path.parent / "CHECKSUMS.sha256"
        ),
        "evidence_manifest_sha256": sha256_file(evidence_root / "manifest.json"),
        "evidence_checksums_sha256": blinding_key,
        "generated_at": generated_at,
        "generation_command": list(generation_command),
        "generator_source_inventory": generator_inventory,
        "runtime_versions": runtime_versions,
    }
    package_id = PACKAGE_ID_PREFIX + canonical_sha256(package_identity)

    output_root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _acquire_build_lock(output_root)
    staging: Path | None = None
    try:
        if os.path.lexists(output_root):
            raise Phase2A5PackageError(
                "output directory appeared during input validation; "
                "refusing to overwrite"
            )
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output_root.name}.staging-", dir=output_root.parent
            )
        )
        parent_manifest, _, _ = _copy_phase2a4_parent(
            phase2a4_derivative_root, staging
        )
        source_artifacts = _copy_new_sources(
            staging=staging,
            registry_path=registry_path,
            context_manifest_path=context_manifest_path,
            evidence_root=evidence_root,
        )
        schema_root = repository_root / "docs/contracts/phase2a/schemas"
        schema_sources = {
            name: schema_root / name
            for name in (
                "phase2a5-method-evidence-v1.schema.json",
                "phase2a5-derivative-manifest-v1.schema.json",
                "phase2a5-review-export-v1.schema.json",
            )
        }
        for name, source in schema_sources.items():
            shutil.copyfile(source, staging / "schemas" / name)
        reviewer_script = (
            repository_root / "docs/contracts/phase2a/phase2a5-reviewer.js"
        )
        context_protocol = (
            repository_root
            / "docs/contracts/phase2a/PHASE_2A5_REVIEWER_PROTOCOL_V1.md"
        )
        shutil.copyfile(
            repository_root
            / "docs/contracts/phase2a/PHASE_2A5_CONTEXT_COMPARISON_V1.md",
            staging / "PHASE2A5_CONTEXT_COMPARISON.md",
        )
        for slot in REVIEWER_SLOTS:
            shutil.copyfile(reviewer_script, staging / slot / "reviewer.js")
            shutil.copyfile(
                context_protocol, staging / slot / "CONTEXT_PROTOCOL.md"
            )

        overlap_ids = set(
            _load_json(phase2a4_derivative_root / "reviewer-b/assignment.json")[
                "blind_case_ids"
            ]
        )
        method_schema = _load_json(
            schema_sources["phase2a5-method-evidence-v1.schema.json"]
        )
        sidecars: dict[str, dict[str, Any]] = {}
        mapping_cases: list[dict[str, Any]] = []
        ui_by_blind: dict[str, dict[str, Any]] = {}
        for blind in sorted(parent_by_blind):
            sidecar, mapping_case, ui = _build_case_material(
                package_root=staging,
                evidence_root=evidence_root,
                record=evidence_records[blind],
                package_id=package_id,
                labels=labels[blind],
                blinding_key=blinding_key,
                overlap=blind in overlap_ids,
            )
            _validate_schema(
                sidecar,
                method_schema,
                f"Phase 2A.5 method evidence {blind}",
                error_type=Phase2A5PackageError,
            )
            sidecars[blind] = sidecar
            mapping_cases.append(mapping_case)
            ui_by_blind[blind] = ui
            write_canonical_json(
                staging / "reviewer-a/context-evidence" / f"{blind}.json",
                sidecar,
            )
            if blind in overlap_ids:
                write_canonical_json(
                    staging / "reviewer-b/context-evidence" / f"{blind}.json",
                    sidecar,
                )
            write_canonical_json(
                staging / "coordinator/phase2a5-method-evidence" / f"{blind}.json",
                sidecar,
            )

        mapping: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "package_id": package_id,
            "mapping_id": "",
            "registry_binding": source_artifacts["registry"],
            "context_manifest_binding": source_artifacts["context_manifest"],
            "context_checksums_binding": source_artifacts["context_checksums"],
            "evidence_binding": {
                "manifest": source_artifacts["evidence_manifest"],
                "checksums": source_artifacts["evidence_checksums"],
            },
            "blinding_derivation": {
                "version": "phase2a5-balanced-keyed-blinding-v1",
                "coordinator_only_evidence_checksums_sha256": blinding_key,
                "exact_balance_per_family": {
                    family: {"A_candidate_0": 30, "A_candidate_1": 30}
                    for family in NEW_METHOD_FAMILIES
                },
            },
            "package_identity_inputs": package_identity,
            "cases": mapping_cases,
        }
        mapping_identity = copy.deepcopy(mapping)
        mapping_identity.pop("mapping_id")
        mapping["mapping_id"] = MAPPING_ID_PREFIX + canonical_sha256(
            mapping_identity
        )
        write_canonical_json(
            staging / "coordinator/phase2a5-blinding-map.json", mapping
        )

        review_schema = _load_json(
            staging / "schemas/validation-review-v1.schema.json"
        )
        for slot in REVIEWER_SLOTS:
            assignment = _load_json(staging / slot / "assignment.json")
            blind_ids = assignment["blind_case_ids"]
            parent_template = _load_json(
                phase2a4_derivative_root / slot / "review-template.json"
            )
            parent_reviews = {
                review["blind_case_id"]: review
                for review in parent_template["reviews"]
            }
            reviews: list[dict[str, Any]] = []
            slot_ui: dict[str, Any] = {}
            cases = [
                _load_json(staging / slot / "cases" / f"{blind}.json")
                for blind in blind_ids
            ]
            for blind in blind_ids:
                review = copy.deepcopy(parent_reviews[blind])
                for family in NEW_METHOD_FAMILIES:
                    review["method_comparisons"][family] = copy.deepcopy(
                        sidecars[blind]["review_method_metadata"][family]
                    )
                _validate_schema(
                    review,
                    review_schema,
                    f"{slot} blank review {blind}",
                    error_type=Phase2A5PackageError,
                )
                _assert_blank_review(review)
                reviews.append(review)
                slot_ui[blind] = ui_by_blind[blind]
            write_canonical_json(
                staging / slot / "review-template.json",
                {
                    "schema_version": SCHEMA_VERSION,
                    "reviewer_slot": slot,
                    "reviews": reviews,
                },
            )
            write_canonical_json(
                staging / slot / "context-evidence/index.json", slot_ui
            )
            old_ui = _load_json(staging / slot / "method-evidence/index.json")
            binding = _review_package_binding(
                staging, slot, package_id, phase2a4_manifest["package_id"]
            )
            (staging / slot / "index.html").write_text(
                _html_document(
                    reviewer_slot=slot,
                    cases=cases,
                    reviews=reviews,
                    method_evidence=old_ui,
                    context_evidence=slot_ui,
                    package_binding=binding,
                ),
                encoding="utf-8",
                newline="\n",
            )

        if (
            _source_inventory(repository_root) != generator_inventory
            or _phase2a5_runtime_versions() != runtime_versions
        ):
            raise Phase2A5PackageError(
                "package generator source or runtime changed during construction"
            )
        inventory_before_manifest = _inventory(staging)
        reviewer_packages = []
        for slot in REVIEWER_SLOTS:
            subset = [
                item
                for item in inventory_before_manifest
                if item["path"].startswith(f"{slot}/")
            ]
            reviewer_packages.append(
                {
                    "reviewer_slot": slot,
                    "case_count": len(
                        _load_json(staging / slot / "assignment.json")[
                            "blind_case_ids"
                        ]
                    ),
                    "artifact_inventory_sha256": _inventory_digest(subset),
                    "true_candidate_mapping_present": False,
                    "coordinator_material_present": False,
                }
            )
        availability_counts = Counter(
            sidecar["comparisons"][family]["availability"]
            for sidecar in sidecars.values()
            for family in NEW_METHOD_FAMILIES
        )
        schema_bindings = {
            "method_evidence": _schema_binding(
                staging / "schemas/phase2a5-method-evidence-v1.schema.json",
                staging,
            ),
            "derivative_manifest": _schema_binding(
                staging / "schemas/phase2a5-derivative-manifest-v1.schema.json",
                staging,
            ),
            "review_export": _schema_binding(
                staging / "schemas/phase2a5-review-export-v1.schema.json",
                staging,
            ),
            "validation_review": _schema_binding(
                staging / "schemas/validation-review-v1.schema.json", staging
            ),
        }
        mapping_artifact = _artifact(
            staging / "coordinator/phase2a5-blinding-map.json", staging
        )
        artifact_inventory = inventory_before_manifest
        manifest: dict[str, Any] = {
            "$schema": PACKAGE_SCHEMA_URL,
            "schema_version": SCHEMA_VERSION,
            "package_id": package_id,
            "package_type": "phase2a5_provisional_blinded_context_comparison_derivative",
            "scientific_status": "provisional_audit_inputs_only",
            "method_decision_status": "none",
            "generated_at": generated_at,
            "generation_command": list(generation_command),
            "runtime_versions": runtime_versions,
            "generator_source_inventory": generator_inventory,
            "local_only": True,
            "parent_bindings": {
                "phase2a3": {
                    "package_id": phase2a3_manifest["package_id"],
                    "manifest_sha256": sha256_file(
                        phase2a3_parent_root / "manifest.json"
                    ),
                    "artifact_inventory_sha256": _inventory_digest(
                        phase2a3_manifest["artifact_inventory"]
                    ),
                    "mutated": False,
                },
                "phase2a4": {
                    "package_id": phase2a4_manifest["package_id"],
                    "manifest_sha256": sha256_file(
                        phase2a4_derivative_root / "manifest.json"
                    ),
                    "checksums_sha256": sha256_file(
                        phase2a4_derivative_root / "CHECKSUMS.sha256"
                    ),
                    "artifact_inventory_sha256": _inventory_digest(
                        parent_manifest["artifact_inventory"]
                    ),
                    "mapping_mutated": False,
                    "candidate_registry_mutated": False,
                    "method_candidates_modified_or_activated": False,
                },
            },
            "source_bindings": source_artifacts,
            "schema_bindings": schema_bindings,
            "case_population": {
                "primary_case_count": 60,
                "double_review_case_count": 12,
                "case_replacement_performed": False,
                "missing_cases_retained": True,
                "blind_case_ids_sha256": canonical_sha256(
                    sorted(parent_by_blind)
                ),
                "context_evidence_sidecar_count": 60,
                "comparison_availability_counts": dict(
                    sorted(availability_counts.items())
                ),
            },
            "review": {
                "isolated_reviewer_workflow": True,
                "primary_assessment_required_before_all_five_family_reveal": True,
                "primary_fields_locked_after_reveal": True,
                "human_labels_present": False,
                "qualified_reviewer_evidence_present": False,
                "blank_review_state_preserved": True,
            },
            "blinding": {
                "reviewer_option_labels": ["A", "B"],
                "true_mapping_coordinator_only": True,
                "mapping_artifact": mapping_artifact,
                "mapping_distributed_to_reviewers": False,
                "exact_balance_per_new_family": True,
                "double_review_evidence_identical": True,
                "reviewer_packages": reviewer_packages,
            },
            "decision_state": {
                "phase2a4": copy.deepcopy(phase2a4_manifest["decision_state"]),
                "phase2a5": {
                    "selected_candidates": {
                        family: None for family in NEW_METHOD_FAMILIES
                    },
                    "strong_subset_threshold_selected": False,
                    "contextual_signature_policy_frozen": False,
                    "public_wording_approved": False,
                    "release_or_replay_authorized": False,
                },
            },
            "claims": {
                "qualified_human_labels_present": False,
                "scientific_accuracy_claim": False,
                "method_promoted_or_activated": False,
                "raw_detection_modified": False,
                "missing_evidence_interpreted_as_zero": False,
                "canonical_identity_inferred": False,
                "cause_inferred": False,
                "baseline_rebuilt": False,
                "current_year_replayed": False,
                "phase2a4_candidates_modified": False,
            },
            "integrity": {
                "schema_validated": True,
                "checksum_file_validated": True,
                "artifact_inventory_reconciled": True,
                "phase2a3_parent_reconciled": True,
                "phase2a4_parent_reconciled": True,
                "phase2a4_opaque_material_preserved": True,
                "case_population_reconciled": True,
                "mapping_bijection_reconciled": True,
                "reviewer_isolation_reconciled": True,
                "blank_reviews_reconciled": True,
                "missing_evidence_retained": True,
            },
            "generation_limitations": [
                "No qualified reviewer labels or scientific method decision are present.",
                "Technical integrity does not establish scientific accuracy.",
                "MapBiomas context is not an omission or recall reference.",
                "No cause is inferred from labels, context, signatures, or tool checks.",
                "Missing and partial evidence remains explicit and no case was replaced.",
            ],
            "artifact_inventory_rule": (
                "Every file except manifest.json and CHECKSUMS.sha256 is listed "
                "with exact bytes and SHA-256."
            ),
            "artifact_inventory": artifact_inventory,
            "checksum_file": "CHECKSUMS.sha256",
        }
        manifest_schema = _load_json(
            schema_sources["phase2a5-derivative-manifest-v1.schema.json"]
        )
        _validate_schema(
            manifest,
            manifest_schema,
            "Phase 2A.5 derivative manifest",
            error_type=Phase2A5PackageError,
        )
        write_canonical_json(staging / "manifest.json", manifest)
        _write_checksums(staging, artifact_inventory)
        validate_phase2a5_derivative_package(
            staging,
            phase2a3_parent_root=phase2a3_parent_root,
            phase2a4_derivative_root=phase2a4_derivative_root,
            registry_path=registry_path,
            context_manifest_path=context_manifest_path,
            repository_root=repository_root,
        )
        _publish_directory_no_clobber(staging, output_root)
        return manifest
    except Exception:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        _release_build_lock(lock_path)


def _validate_parent_phase2a4_bytes(
    root: Path, parent_manifest: Mapping[str, Any]
) -> None:
    for item in parent_manifest["artifact_inventory"]:
        relative = item["path"]
        if relative in INTENTIONALLY_REPLACED_PHASE2A4_PATHS:
            continue
        path = _safe_path(root, relative, error_type=Phase2A5PackageIntegrityError)
        if (
            not path.is_file()
            or path.stat().st_size != item["bytes"]
            or sha256_file(path) != item["sha256"]
        ):
            raise Phase2A5PackageIntegrityError(
                f"Phase 2A.4 opaque artifact changed: {relative}"
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


def _primary_snapshot(review: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "change_assessment": copy.deepcopy(review["change_assessment"]),
        "temporal_assessment": copy.deepcopy(review["temporal_assessment"]),
        "land_cover_assessment": copy.deepcopy(review["land_cover_assessment"]),
        "contextual_signature": copy.deepcopy(review["contextual_signature"]),
    }


def _primary_assessment_complete(review: Mapping[str, Any]) -> bool:
    change = review.get("change_assessment", {})
    temporal = review.get("temporal_assessment", {})
    land_cover = review.get("land_cover_assessment", {})
    signature = review.get("contextual_signature", {})
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
            signature.get("label"),
            signature.get("reason"),
        )
    )


def _method_assessment_started(review: Mapping[str, Any]) -> bool:
    methods = review.get("method_comparisons", {})
    return any(
        any(
            methods.get(family, {}).get(field)
            for field in ("preference", "reviewer_confidence", "evidence_reason")
        )
        for family in ALL_METHOD_FAMILIES
    )


def _validate_sidecar(
    sidecar: Mapping[str, Any], reviewer_root: Path
) -> None:
    if sidecar["integrity"]["canonical_payload_sha256"] != _sidecar_payload_hash(
        sidecar
    ):
        raise Phase2A5PackageIntegrityError(
            "context sidecar canonical payload hash mismatch"
        )
    artifacts = _all_sidecar_artifacts(sidecar)
    if sidecar["integrity"]["artifact_inventory_sha256"] != canonical_sha256(
        artifacts
    ):
        raise Phase2A5PackageIntegrityError(
            "context sidecar artifact inventory hash mismatch"
        )
    for artifact in artifacts:
        path = _safe_path(
            reviewer_root,
            artifact["path"],
            error_type=Phase2A5PackageIntegrityError,
        )
        if (
            not path.is_file()
            or path.stat().st_size != artifact["bytes"]
            or sha256_file(path) != artifact["sha256"]
        ):
            raise Phase2A5PackageIntegrityError(
                f"context panel checksum mismatch: {artifact['path']}"
            )
    for family in NEW_METHOD_FAMILIES:
        comparison = sidecar["comparisons"][family]
        if comparison["selected_or_activated"] is not False:
            raise Phase2A5PackageIntegrityError(
                "Phase 2A.5 method was selected or activated"
            )
        option_ids = {
            comparison["option_a"]["blind_option_id"],
            comparison["option_b"]["blind_option_id"],
        }
        if len(option_ids) != 2:
            raise Phase2A5PackageIntegrityError(
                "blinded comparison is not bijective"
            )


def _validate_new_mapping(
    mapping: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    candidates: Mapping[str, tuple[str, str]],
    sidecars: Mapping[str, Mapping[str, Any]],
) -> None:
    expected_mapping_keys = {
        "schema_version",
        "package_id",
        "mapping_id",
        "registry_binding",
        "context_manifest_binding",
        "context_checksums_binding",
        "evidence_binding",
        "blinding_derivation",
        "package_identity_inputs",
        "cases",
    }
    if set(mapping) != expected_mapping_keys:
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 mapping fields are unexpected or missing"
        )
    if (
        mapping.get("schema_version") != SCHEMA_VERSION
        or mapping.get("package_id") != manifest.get("package_id")
    ):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 mapping package identity mismatch"
        )
    identity = copy.deepcopy(mapping)
    mapping_id = identity.pop("mapping_id", None)
    if mapping_id != MAPPING_ID_PREFIX + canonical_sha256(identity):
        raise Phase2A5PackageIntegrityError("Phase 2A.5 mapping ID mismatch")
    package_identity = mapping.get("package_identity_inputs")
    expected_package_identity = {
        "pipeline": "phase2a5-derivative-package-v1",
        "phase2a3_manifest_sha256": manifest["parent_bindings"]["phase2a3"][
            "manifest_sha256"
        ],
        "phase2a4_manifest_sha256": manifest["parent_bindings"]["phase2a4"][
            "manifest_sha256"
        ],
        "phase2a4_checksums_sha256": manifest["parent_bindings"]["phase2a4"][
            "checksums_sha256"
        ],
        "registry_sha256": manifest["source_bindings"]["registry"]["sha256"],
        "context_manifest_sha256": manifest["source_bindings"][
            "context_manifest"
        ]["sha256"],
        "context_checksums_sha256": manifest["source_bindings"][
            "context_checksums"
        ]["sha256"],
        "evidence_manifest_sha256": manifest["source_bindings"][
            "evidence_manifest"
        ]["sha256"],
        "evidence_checksums_sha256": manifest["source_bindings"][
            "evidence_checksums"
        ]["sha256"],
        "generated_at": manifest["generated_at"],
        "generation_command": manifest["generation_command"],
        "generator_source_inventory": manifest["generator_source_inventory"],
        "runtime_versions": manifest["runtime_versions"],
    }
    if (
        package_identity != expected_package_identity
        or manifest["package_id"]
        != PACKAGE_ID_PREFIX + canonical_sha256(package_identity)
    ):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 package identity binding mismatch"
        )
    expected_balance_declaration = {
        family: {"A_candidate_0": 30, "A_candidate_1": 30}
        for family in NEW_METHOD_FAMILIES
    }
    blinding_derivation = mapping.get("blinding_derivation")
    if (
        not isinstance(blinding_derivation, Mapping)
        or set(blinding_derivation)
        != {
            "version",
            "coordinator_only_evidence_checksums_sha256",
            "exact_balance_per_family",
        }
        or blinding_derivation.get("version")
        != "phase2a5-balanced-keyed-blinding-v1"
        or blinding_derivation.get("exact_balance_per_family")
        != expected_balance_declaration
    ):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 blinding derivation declaration changed"
        )
    key = blinding_derivation["coordinator_only_evidence_checksums_sha256"]
    expected = deterministic_phase2a5_blind_mapping(
        list(sidecars), candidates, blinding_key=key
    )
    cases = mapping.get("cases")
    if not isinstance(cases, list) or len(cases) != 60:
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 mapping must contain exactly 60 cases"
        )
    if cases != sorted(cases, key=lambda item: item.get("blind_case_id", "")):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 mapping cases are not in deterministic blind-ID order"
        )
    if {case.get("blind_case_id") for case in cases} != set(sidecars):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 mapping population is not bijective"
        )
    balance = Counter()
    for case in cases:
        if set(case) != {"sample_id", "blind_case_id", "double_review", "families"}:
            raise Phase2A5PackageIntegrityError(
                "Phase 2A.5 mapping case fields are unexpected or missing"
            )
        blind = case["blind_case_id"]
        if set(case["families"]) != set(NEW_METHOD_FAMILIES):
            raise Phase2A5PackageIntegrityError(
                "Phase 2A.5 mapping family fields are unexpected or missing"
            )
        for family in NEW_METHOD_FAMILIES:
            values = case["families"][family]
            if set(values) != {"A", "B"}:
                raise Phase2A5PackageIntegrityError(
                    "Phase 2A.5 A/B mapping is incomplete"
                )
            for label in ("A", "B"):
                if set(values[label]) != {
                    "candidate_id",
                    "blind_option_id",
                    "source_panel",
                }:
                    raise Phase2A5PackageIntegrityError(
                        "Phase 2A.5 mapped option fields are unexpected or missing"
                    )
                candidate = values[label]["candidate_id"]
                if candidate != expected[blind][family][label]:
                    raise Phase2A5PackageIntegrityError(
                        "deterministic Phase 2A.5 mapping mismatch"
                    )
                if values[label]["blind_option_id"] != _blind_option_id(
                    key, blind, family, candidate
                ):
                    raise Phase2A5PackageIntegrityError(
                        "Phase 2A.5 opaque option ID does not rederive"
                    )
            if {
                values["A"]["candidate_id"],
                values["B"]["candidate_id"],
            } != set(candidates[family]):
                raise Phase2A5PackageIntegrityError(
                    "Phase 2A.5 candidate mapping is not bijective"
                )
            if values["A"]["candidate_id"] == candidates[family][0]:
                balance[family] += 1
            comparison = sidecars[blind]["comparisons"][family]
            if (
                comparison["option_a"]["blind_option_id"]
                != values["A"]["blind_option_id"]
                or comparison["option_b"]["blind_option_id"]
                != values["B"]["blind_option_id"]
            ):
                raise Phase2A5PackageIntegrityError(
                    "sidecar and coordinator mapping do not reconcile"
                )
    if any(balance[family] != 30 for family in NEW_METHOD_FAMILIES):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 A/B mapping is not exactly balanced"
        )


def _validate_source_evidence_mapping(
    mapping: Mapping[str, Any],
    *,
    records: Mapping[str, Mapping[str, Any]],
    sidecars: Mapping[str, Mapping[str, Any]],
) -> None:
    mapping_by_blind = {
        case["blind_case_id"]: case for case in mapping.get("cases", [])
    }
    if set(mapping_by_blind) != set(records) or set(records) != set(sidecars):
        raise Phase2A5PackageIntegrityError(
            "source evidence, mapping, and sidecar populations differ"
        )
    for blind, record in records.items():
        mapped = mapping_by_blind[blind]
        if mapped["sample_id"] != record["sample_id"]:
            raise Phase2A5PackageIntegrityError(
                f"source evidence sample binding mismatch: {blind}"
            )
        for family in NEW_METHOD_FAMILIES:
            comparison = sidecars[blind]["comparisons"][family]
            source_panels = [
                mapped["families"][family][label]["source_panel"]
                for label in ("A", "B")
            ]
            expected_availability, expected_reason = _comparison_availability(
                source_panels
            )
            if (
                comparison["availability"] != expected_availability
                or comparison["reason"] != expected_reason
                or comparison["display_order"] != ["A", "B"]
                or comparison["primary_assessment_required_first"] is not True
                or comparison["selected_or_activated"] is not False
            ):
                raise Phase2A5PackageIntegrityError(
                    f"reviewer comparison status differs from source evidence: "
                    f"{blind}/{family}"
                )
            for label, option_name in (("A", "option_a"), ("B", "option_b")):
                option = mapped["families"][family][label]
                candidate = option["candidate_id"]
                source_panel = record["candidate_panels"][family][candidate]
                if option["source_panel"] != source_panel:
                    raise Phase2A5PackageIntegrityError(
                        f"coordinator source panel binding mismatch: "
                        f"{blind}/{family}/{label}"
                    )
                artifacts = comparison[option_name]["artifacts"]
                if source_panel["status"] in {"available", "partial"}:
                    suffix = Path(source_panel["path"]).suffix.lower() or ".bin"
                    expected_path = (
                        Path("context-evidence")
                        / blind
                        / family
                        / f"{label}{suffix}"
                    ).as_posix()
                    expected_artifact = {
                        "path": expected_path,
                        "bytes": source_panel["bytes"],
                        "sha256": source_panel["sha256"],
                        "media_type": mimetypes.guess_type(expected_path)[0]
                        or "application/octet-stream",
                        "role": "blinded_context_comparison_panel",
                    }
                    if artifacts != [expected_artifact]:
                        raise Phase2A5PackageIntegrityError(
                            f"reviewer panel differs from source evidence: "
                            f"{blind}/{family}/{label}"
                        )
                elif artifacts:
                    raise Phase2A5PackageIntegrityError(
                        f"unreviewable source gained a reviewer panel: "
                        f"{blind}/{family}/{label}"
                    )
            metadata = sidecars[blind]["review_method_metadata"][family]
            expected_metadata = {
                "availability": expected_availability,
                "option_a": comparison["option_a"]["blind_option_id"],
                "option_b": comparison["option_b"]["blind_option_id"],
                "display_order": ["A", "B"],
                "preference": None,
                "reviewer_confidence": None,
                "evidence_reason": None,
                "selected_or_activated": False,
            }
            if metadata != expected_metadata:
                raise Phase2A5PackageIntegrityError(
                    f"review method metadata differs from source evidence: "
                    f"{blind}/{family}"
                )


def _expected_context_ui(
    sidecar: Mapping[str, Any], mapping_case: Mapping[str, Any]
) -> dict[str, Any]:
    families: dict[str, Any] = {}
    for family in NEW_METHOD_FAMILIES:
        options: dict[str, Any] = {}
        comparison = sidecar["comparisons"][family]
        for label, option_name in (("A", "option_a"), ("B", "option_b")):
            panel = mapping_case["families"][family][label]["source_panel"]
            artifacts = comparison[option_name]["artifacts"]
            artifact = artifacts[0] if artifacts else None
            status = (
                panel["status"]
                if panel["status"] in {"available", "partial"}
                else "unreviewable"
            )
            options[label] = {
                "status": status,
                "reason": (
                    None
                    if status == "available"
                    else "Evidence is incomplete and retained without replacement."
                ),
                "local_path": None if artifact is None else artifact["path"],
                "media_type": None if artifact is None else artifact["media_type"],
            }
        families[family] = {"options": options}
    return {"evidence_id": sidecar["evidence_id"], "families": families}


def _semantic_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _semantic_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _semantic_keys(nested)


def _reviewer_leakage_scan(
    package_root: Path,
    *,
    registry: Mapping[str, Any],
    mapping: Mapping[str, Any],
) -> None:
    candidates = [
        candidate
        for pair in _candidate_ids(registry).values()
        for candidate in pair
    ]
    sample_ids = [case["sample_id"] for case in mapping["cases"]]
    forbidden = [value.encode("utf-8") for value in (*candidates, *sample_ids)]
    forbidden_keys = {
        "candidate_id",
        "sample_id",
        "threshold",
        "thresholds",
        "class_mapping",
        "mapping_id",
        "strong_subset_membership",
        "natural_vegetation_fraction",
    }
    for slot in REVIEWER_SLOTS:
        reviewer_root = package_root / slot
        for path in reviewer_root.rglob("*"):
            if not path.is_file():
                continue
            payload = path.read_bytes()
            if any(token in payload for token in forbidden):
                raise Phase2A5PackageIntegrityError(
                    f"true Phase 2A.5 identity leaked into {slot}: "
                    f"{path.relative_to(package_root)}"
                )
            if path.suffix.lower() == ".json":
                value = _load_json(
                    path, error_type=Phase2A5PackageIntegrityError
                )
                leaked = forbidden_keys.intersection(_semantic_keys(value))
                if leaked:
                    raise Phase2A5PackageIntegrityError(
                        f"semantic Phase 2A.5 identity leaked into {slot}: "
                        f"{path.relative_to(package_root)} ({sorted(leaked)})"
                    )


def _validate_overlap(package_root: Path) -> None:
    overlap = _load_json(
        package_root / "reviewer-b/assignment.json",
        error_type=Phase2A5PackageIntegrityError,
    )["blind_case_ids"]
    for blind in overlap:
        relative_sidecar = Path("context-evidence") / f"{blind}.json"
        if (
            package_root / "reviewer-a" / relative_sidecar
        ).read_bytes() != (
            package_root / "reviewer-b" / relative_sidecar
        ).read_bytes():
            raise Phase2A5PackageIntegrityError(
                f"overlap context sidecar differs: {blind}"
            )
        panel_root = package_root / "reviewer-a/context-evidence" / blind
        for path_a in panel_root.rglob("*"):
            if path_a.is_file():
                relative = path_a.relative_to(package_root / "reviewer-a")
                path_b = package_root / "reviewer-b" / relative
                if not path_b.is_file() or path_a.read_bytes() != path_b.read_bytes():
                    raise Phase2A5PackageIntegrityError(
                        f"overlap context panel differs: {blind}/{relative}"
                    )


def _validate_reviewer_material(
    root: Path,
    *,
    manifest: Mapping[str, Any],
    sidecars: Mapping[str, Mapping[str, Any]],
    mapping: Mapping[str, Any],
) -> None:
    review_schema = _load_json(
        root / "schemas/validation-review-v1.schema.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    parent_binding_root = root / "coordinator/phase2a4-parent-binding"
    mapping_by_blind = {
        case["blind_case_id"]: case for case in mapping["cases"]
    }
    for slot in REVIEWER_SLOTS:
        assignment = _load_json(
            root / slot / "assignment.json",
            error_type=Phase2A5PackageIntegrityError,
        )
        template = _load_json(
            root / slot / "review-template.json",
            error_type=Phase2A5PackageIntegrityError,
        )
        old_template = _load_json(
            parent_binding_root / f"{slot}-review-template.json",
            error_type=Phase2A5PackageIntegrityError,
        )
        expected_ids = assignment["blind_case_ids"]
        if [review["blind_case_id"] for review in template["reviews"]] != expected_ids:
            raise Phase2A5PackageIntegrityError(
                f"{slot} template order differs from assignment"
            )
        old_by_blind = {
            review["blind_case_id"]: review for review in old_template["reviews"]
        }
        context_ui = _load_json(
            root / slot / "context-evidence/index.json",
            error_type=Phase2A5PackageIntegrityError,
        )
        if set(context_ui) != set(expected_ids):
            raise Phase2A5PackageIntegrityError(
                f"{slot} context index population mismatch"
            )
        cases = []
        for review in template["reviews"]:
            blind = review["blind_case_id"]
            _validate_schema(review, review_schema, f"{slot} review {blind}")
            _assert_blank_review(review)
            old = old_by_blind[blind]
            normalized = copy.deepcopy(review)
            for family in NEW_METHOD_FAMILIES:
                normalized["method_comparisons"][family] = copy.deepcopy(
                    old["method_comparisons"][family]
                )
            if normalized != old:
                raise Phase2A5PackageIntegrityError(
                    f"Phase 2A.4 review metadata changed: {slot}/{blind}"
                )
            for family in PRESERVED_METHOD_FAMILIES:
                if (
                    review["method_comparisons"][family]
                    != old["method_comparisons"][family]
                ):
                    raise Phase2A5PackageIntegrityError(
                        f"Phase 2A.4 family metadata changed: {slot}/{blind}/{family}"
                    )
            for family in NEW_METHOD_FAMILIES:
                if (
                    review["method_comparisons"][family]
                    != sidecars[blind]["review_method_metadata"][family]
                ):
                    raise Phase2A5PackageIntegrityError(
                        f"Phase 2A.5 family metadata mismatch: {slot}/{blind}/{family}"
                    )
            reviewer_sidecar = _load_json(
                root / slot / "context-evidence" / f"{blind}.json",
                error_type=Phase2A5PackageIntegrityError,
            )
            if reviewer_sidecar != sidecars[blind]:
                raise Phase2A5PackageIntegrityError(
                    f"reviewer context sidecar differs from coordinator: {slot}/{blind}"
                )
            if context_ui[blind] != _expected_context_ui(
                sidecars[blind], mapping_by_blind[blind]
            ):
                raise Phase2A5PackageIntegrityError(
                    f"reviewer context index differs from source evidence: {slot}/{blind}"
                )
            cases.append(
                _load_json(
                    root / slot / "cases" / f"{blind}.json",
                    error_type=Phase2A5PackageIntegrityError,
                )
            )
        old_ui = _load_json(
            root / slot / "method-evidence/index.json",
            error_type=Phase2A5PackageIntegrityError,
        )
        binding = _review_package_binding(
            root,
            slot,
            manifest["package_id"],
            manifest["parent_bindings"]["phase2a4"]["package_id"],
        )
        expected_html = _html_document(
            reviewer_slot=slot,
            cases=cases,
            reviews=template["reviews"],
            method_evidence=old_ui,
            context_evidence=context_ui,
            package_binding=binding,
        )
        if (root / slot / "index.html").read_text(encoding="utf-8") != expected_html:
            raise Phase2A5PackageIntegrityError(
                f"{slot} HTML payload does not reconcile"
            )


def validate_phase2a5_derivative_package(
    package_root: Path,
    *,
    phase2a3_parent_root: Path | None = None,
    phase2a4_derivative_root: Path | None = None,
    registry_path: Path | None = None,
    context_manifest_path: Path | None = None,
    evidence_root: Path | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Deeply validate a self-contained derivative and optional source inputs."""
    root = Path(package_root).resolve()
    repository_root = (
        Path(repository_root).resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[2]
    )
    registry_path = (
        Path(registry_path).resolve()
        if registry_path is not None
        else repository_root / "config/phase2a5_context_candidates_v1.json"
    )
    if not root.is_dir():
        raise Phase2A5PackageIntegrityError(
            f"package directory does not exist: {root}"
        )
    manifest = _load_json(
        root / "manifest.json", error_type=Phase2A5PackageIntegrityError
    )
    _verify_checksum_artifact(
        root, manifest, error_type=Phase2A5PackageIntegrityError
    )
    manifest_schema = _load_json(
        root / "schemas/phase2a5-derivative-manifest-v1.schema.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    method_schema = _load_json(
        root / "schemas/phase2a5-method-evidence-v1.schema.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    export_schema = _load_json(
        root / "schemas/phase2a5-review-export-v1.schema.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    review_schema = _load_json(
        root / "schemas/validation-review-v1.schema.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    _validate_schema(manifest, manifest_schema, "Phase 2A.5 derivative manifest")
    Draft202012Validator.check_schema(method_schema)
    Draft202012Validator.check_schema(export_schema)
    Draft202012Validator.check_schema(review_schema)
    actual_inventory = _inventory(root)
    if manifest["artifact_inventory"] != actual_inventory:
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 artifact inventory is not canonical"
        )

    expected_schema_bindings = {
        "method_evidence": _schema_binding(
            root / "schemas/phase2a5-method-evidence-v1.schema.json", root
        ),
        "derivative_manifest": _schema_binding(
            root / "schemas/phase2a5-derivative-manifest-v1.schema.json", root
        ),
        "review_export": _schema_binding(
            root / "schemas/phase2a5-review-export-v1.schema.json", root
        ),
        "validation_review": _schema_binding(
            root / "schemas/validation-review-v1.schema.json", root
        ),
    }
    if manifest["schema_bindings"] != expected_schema_bindings:
        raise Phase2A5PackageIntegrityError("schema bindings do not reconcile")
    _validate_packaged_generator_material(
        root, manifest, repository_root=repository_root
    )

    parent_binding_root = root / "coordinator/phase2a4-parent-binding"
    parent_manifest_path = parent_binding_root / "manifest.json"
    parent_checksums_path = parent_binding_root / "CHECKSUMS.sha256"
    parent_manifest = _load_json(
        parent_manifest_path, error_type=Phase2A5PackageIntegrityError
    )
    phase2a4_binding = manifest["parent_bindings"]["phase2a4"]
    if (
        parent_manifest.get("package_id") != ACCEPTED_PHASE2A4_PACKAGE_ID
        or sha256_file(parent_manifest_path) != ACCEPTED_PHASE2A4_MANIFEST_SHA256
        or sha256_file(parent_checksums_path)
        != ACCEPTED_PHASE2A4_CHECKSUMS_SHA256
        or sha256_file(parent_manifest_path)
        != phase2a4_binding["manifest_sha256"]
        or sha256_file(parent_checksums_path)
        != phase2a4_binding["checksums_sha256"]
        or _inventory_digest(parent_manifest["artifact_inventory"])
        != phase2a4_binding["artifact_inventory_sha256"]
        or parent_manifest["package_id"] != phase2a4_binding["package_id"]
        or manifest["decision_state"]["phase2a4"]
        != parent_manifest["decision_state"]
    ):
        raise Phase2A5PackageIntegrityError(
            "embedded Phase 2A.4 parent binding mismatch"
        )
    _validate_parent_phase2a4_bytes(root, parent_manifest)

    registry_artifact = manifest["source_bindings"]["registry"]
    registry_file = _safe_path(
        root,
        registry_artifact["path"],
        error_type=Phase2A5PackageIntegrityError,
    )
    registry = _load_json(
        registry_file, error_type=Phase2A5PackageIntegrityError
    )
    try:
        candidates = _candidate_ids(registry)
    except Phase2A5PackageError as exc:
        raise Phase2A5PackageIntegrityError(
            f"packaged Phase 2A.5 registry is invalid: {exc}"
        ) from exc
    for name, relative in (
        ("registry", "coordinator/phase2a5-inputs/context-candidate-registry.json"),
        ("context_manifest", "coordinator/phase2a5-inputs/context-manifest.json"),
        ("context_checksums", "coordinator/phase2a5-inputs/context-CHECKSUMS.sha256"),
        ("evidence_manifest", "coordinator/phase2a5-evidence/manifest.json"),
        ("evidence_checksums", "coordinator/phase2a5-evidence/CHECKSUMS.sha256"),
    ):
        if manifest["source_bindings"][name] != _artifact(root / relative, root):
            raise Phase2A5PackageIntegrityError(
                f"Phase 2A.5 source binding does not reconcile: {name}"
            )
    mapping = _load_json(
        root / "coordinator/phase2a5-blinding-map.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    if manifest["blinding"]["mapping_artifact"] != _artifact(
        root / "coordinator/phase2a5-blinding-map.json", root
    ):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 manifest mapping artifact binding mismatch"
        )
    sidecar_paths = sorted(
        (root / "coordinator/phase2a5-method-evidence").glob("*.json")
    )
    if len(sidecar_paths) != 60:
        raise Phase2A5PackageIntegrityError(
            "coordinator must contain exactly 60 Phase 2A.5 sidecars"
        )
    sidecars: dict[str, dict[str, Any]] = {}
    for path in sidecar_paths:
        sidecar = _load_json(path, error_type=Phase2A5PackageIntegrityError)
        _validate_schema(sidecar, method_schema, f"context sidecar {path.name}")
        blind = sidecar["parent_case"]["blind_case_id"]
        if blind in sidecars or path.stem != blind:
            raise Phase2A5PackageIntegrityError(
                "duplicate or misnamed Phase 2A.5 sidecar"
            )
        if sidecar["derivative_package_id"] != manifest["package_id"]:
            raise Phase2A5PackageIntegrityError("sidecar package binding mismatch")
        _validate_sidecar(sidecar, root / "reviewer-a")
        sidecars[blind] = sidecar
    try:
        _validate_new_mapping(
            mapping, manifest=manifest, candidates=candidates, sidecars=sidecars
        )
    except Phase2A5PackageError as exc:
        if isinstance(exc, Phase2A5PackageIntegrityError):
            raise
        raise Phase2A5PackageIntegrityError(
            f"packaged Phase 2A.5 mapping is invalid: {exc}"
        ) from exc
    crosswalk = _load_json(
        root / "coordinator/crosswalk.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    crosswalk_mappings = crosswalk.get("mappings")
    if not isinstance(crosswalk_mappings, list) or len(crosswalk_mappings) != 60:
        raise Phase2A5PackageIntegrityError(
            "preserved Phase 2A.3 crosswalk is not the frozen 60-case mapping"
        )
    parent_by_blind = {
        item["blind_case_id"]: {
            "blind_case_id": item["blind_case_id"],
            "sample_id": item["sample_id"],
        }
        for item in crosswalk_mappings
    }
    if len(parent_by_blind) != 60:
        raise Phase2A5PackageIntegrityError(
            "preserved Phase 2A.3 crosswalk contains duplicate blind IDs"
        )
    try:
        _packaged_evidence_manifest, packaged_records, packaged_key = (
            _load_phase2a5_evidence(
                root / "coordinator/phase2a5-evidence",
                parent_by_blind=parent_by_blind,
                candidate_ids=candidates,
            )
        )
    except Phase2A5PackageError as exc:
        if isinstance(exc, Phase2A5PackageIntegrityError):
            raise
        raise Phase2A5PackageIntegrityError(
            f"packaged Phase 2A.5 evidence is invalid: {exc}"
        ) from exc
    if (
        sha256_file(root / "coordinator/phase2a5-evidence/manifest.json")
        != manifest["source_bindings"]["evidence_manifest"]["sha256"]
        or packaged_key
        != manifest["source_bindings"]["evidence_checksums"]["sha256"]
    ):
        raise Phase2A5PackageIntegrityError(
            "packaged Phase 2A.5 evidence source binding changed"
        )
    _validate_source_evidence_mapping(
        mapping, records=packaged_records, sidecars=sidecars
    )
    overlap_ids = set(
        _load_json(
            root / "reviewer-b/assignment.json",
            error_type=Phase2A5PackageIntegrityError,
        )["blind_case_ids"]
    )
    if any(
        case.get("double_review") is not (case["blind_case_id"] in overlap_ids)
        for case in mapping["cases"]
    ):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 coordinator mapping double-review flags changed"
        )
    if (
        mapping["evidence_binding"]["manifest"]
        != manifest["source_bindings"]["evidence_manifest"]
        or mapping["evidence_binding"]["checksums"]
        != manifest["source_bindings"]["evidence_checksums"]
        or mapping["registry_binding"] != manifest["source_bindings"]["registry"]
        or mapping["context_manifest_binding"]
        != manifest["source_bindings"]["context_manifest"]
        or mapping["context_checksums_binding"]
        != manifest["source_bindings"]["context_checksums"]
    ):
        raise Phase2A5PackageIntegrityError(
            "coordinator mapping source bindings do not reconcile"
        )
    evidence_checksums = _safe_path(
        root,
        manifest["source_bindings"]["evidence_checksums"]["path"],
        error_type=Phase2A5PackageIntegrityError,
    )
    if (
        mapping["blinding_derivation"][
            "coordinator_only_evidence_checksums_sha256"
        ]
        != sha256_file(evidence_checksums)
    ):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 blinding key does not bind packaged evidence"
        )
    _validate_reviewer_material(
        root, manifest=manifest, sidecars=sidecars, mapping=mapping
    )
    _validate_overlap(root)
    _reviewer_leakage_scan(root, registry=registry, mapping=mapping)
    expected_reviewer_packages = []
    for slot in REVIEWER_SLOTS:
        subset = [
            item for item in actual_inventory if item["path"].startswith(f"{slot}/")
        ]
        expected_reviewer_packages.append(
            {
                "reviewer_slot": slot,
                "case_count": len(
                    _load_json(
                        root / slot / "assignment.json",
                        error_type=Phase2A5PackageIntegrityError,
                    )["blind_case_ids"]
                ),
                "artifact_inventory_sha256": _inventory_digest(subset),
                "true_candidate_mapping_present": False,
                "coordinator_material_present": False,
            }
        )
    if manifest["blinding"]["reviewer_packages"] != expected_reviewer_packages:
        raise Phase2A5PackageIntegrityError(
            "isolated reviewer package inventory binding mismatch"
        )

    counts = Counter(
        sidecar["comparisons"][family]["availability"]
        for sidecar in sidecars.values()
        for family in NEW_METHOD_FAMILIES
    )
    population = manifest["case_population"]
    if (
        population["primary_case_count"] != 60
        or population["double_review_case_count"] != 12
        or population["context_evidence_sidecar_count"] != 60
        or population["blind_case_ids_sha256"] != canonical_sha256(sorted(sidecars))
        or population["comparison_availability_counts"]
        != dict(sorted(counts.items()))
    ):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 case population or availability summary mismatch"
        )
    phase2a5_decision = manifest["decision_state"]["phase2a5"]
    if (
        set(phase2a5_decision["selected_candidates"])
        != set(NEW_METHOD_FAMILIES)
        or any(phase2a5_decision["selected_candidates"].values())
        or any(
            phase2a5_decision[key]
            for key in (
                "strong_subset_threshold_selected",
                "contextual_signature_policy_frozen",
                "public_wording_approved",
                "release_or_replay_authorized",
            )
        )
    ):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 derivative contains a scientific decision"
        )

    if phase2a3_parent_root is not None:
        phase2a3_root = Path(phase2a3_parent_root).resolve()
        try:
            validate_validation_package(phase2a3_root)
        except Exception as exc:
            raise Phase2A5PackageIntegrityError(
                f"external Phase 2A.3 parent failed validation: {exc}"
            ) from exc
        binding = manifest["parent_bindings"]["phase2a3"]
        source_manifest = _load_json(phase2a3_root / "manifest.json")
        if (
            binding["package_id"] != source_manifest["package_id"]
            or binding["manifest_sha256"]
            != sha256_file(phase2a3_root / "manifest.json")
            or binding["artifact_inventory_sha256"]
            != _inventory_digest(source_manifest["artifact_inventory"])
        ):
            raise Phase2A5PackageIntegrityError(
                "external Phase 2A.3 parent binding mismatch"
            )
    if phase2a4_derivative_root is not None:
        phase2a4_root = Path(phase2a4_derivative_root).resolve()
        try:
            validate_phase2a4_derivative_package(
                phase2a4_root, parent_root=phase2a3_parent_root
            )
        except Exception as exc:
            raise Phase2A5PackageIntegrityError(
                f"external Phase 2A.4 parent failed validation: {exc}"
            ) from exc
        if (
            (phase2a4_root / "manifest.json").read_bytes()
            != parent_manifest_path.read_bytes()
            or (phase2a4_root / "CHECKSUMS.sha256").read_bytes()
            != parent_checksums_path.read_bytes()
        ):
            raise Phase2A5PackageIntegrityError(
                "packaged Phase 2A.4 binding differs from source"
            )
    if (
        not registry_path.is_file()
        or registry_file.read_bytes() != registry_path.read_bytes()
    ):
        raise Phase2A5PackageIntegrityError(
            "packaged Phase 2A.5 registry differs from canonical source"
        )
    context_file = _safe_path(
        root,
        manifest["source_bindings"]["context_manifest"]["path"],
        error_type=Phase2A5PackageIntegrityError,
    )
    if context_manifest_path is not None and context_file.read_bytes() != Path(
        context_manifest_path
    ).resolve().read_bytes():
        raise Phase2A5PackageIntegrityError(
            "packaged context manifest differs from source"
        )
    if context_manifest_path is not None:
        source_context_checksums = (
            Path(context_manifest_path).resolve().parent / "CHECKSUMS.sha256"
        )
        packaged_context_checksums = (
            root / "coordinator/phase2a5-inputs/context-CHECKSUMS.sha256"
        )
        if (
            not source_context_checksums.is_file()
            or packaged_context_checksums.read_bytes()
            != source_context_checksums.read_bytes()
        ):
            raise Phase2A5PackageIntegrityError(
                "packaged context checksum inventory differs from source"
            )
    if evidence_root is not None:
        source = Path(evidence_root).resolve()
        packaged = root / "coordinator/phase2a5-evidence"
        for relative in ("manifest.json", "CHECKSUMS.sha256"):
            if (packaged / relative).read_bytes() != (source / relative).read_bytes():
                raise Phase2A5PackageIntegrityError(
                    "packaged Phase 2A.5 evidence differs from source"
                )
        if any(
            value is None
            for value in (
                phase2a3_parent_root,
                context_manifest_path,
            )
        ):
            raise Phase2A5PackageIntegrityError(
                "deep source-evidence validation requires the Phase 2A.3 parent, "
                "registry, context manifest, and canonical repository root"
            )
        source_manifest = _load_json(
            source / "manifest.json", error_type=Phase2A5PackageIntegrityError
        )
        try:
            _deep_validate_phase2a5_evidence_source(
                evidence_root=source,
                evidence_manifest=source_manifest,
                phase2a3_root=Path(phase2a3_parent_root).resolve(),
                registry_path=registry_path,
                context_manifest_path=Path(context_manifest_path).resolve(),
                repository_root=repository_root,
            )
        except Phase2A5PackageError as exc:
            raise Phase2A5PackageIntegrityError(str(exc)) from exc
    expected_sources = _source_inventory(repository_root)
    if (
        manifest["generator_source_inventory"] != expected_sources
        or manifest["runtime_versions"] != _phase2a5_runtime_versions()
    ):
        raise Phase2A5PackageIntegrityError(
            "Phase 2A.5 generator source or runtime inventory mismatch"
        )
    return manifest


def validate_phase2a5_review_export(
    package_root: Path, review_export_path: Path
) -> dict[str, Any]:
    """Validate one package-bound isolated review without choosing a policy."""
    root = Path(package_root).resolve()
    export_path = Path(review_export_path).resolve()
    manifest = validate_phase2a5_derivative_package(root)
    export = _load_json(export_path, error_type=Phase2A5PackageIntegrityError)
    export_schema = _load_json(
        root / "schemas/phase2a5-review-export-v1.schema.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    _validate_schema(export, export_schema, export_path.name)
    slot = export["reviewer_slot"]
    expected_binding = _review_package_binding(
        root,
        slot,
        manifest["package_id"],
        manifest["parent_bindings"]["phase2a4"]["package_id"],
    )
    if export["package_binding"] != expected_binding:
        raise Phase2A5PackageIntegrityError(
            "review export is bound to another package or template"
        )
    assignment = _load_json(
        root / slot / "assignment.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    expected_ids = assignment["blind_case_ids"]
    reviews = export["reviews"]
    reveals = export["reveal_state"]
    if (
        [review.get("blind_case_id") for review in reviews] != expected_ids
        or [reveal.get("blind_case_id") for reveal in reveals] != expected_ids
    ):
        raise Phase2A5PackageIntegrityError(
            "review or reveal order differs from isolated assignment"
        )
    review_schema = _load_json(
        root / "schemas/validation-review-v1.schema.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    template = _load_json(
        root / slot / "review-template.json",
        error_type=Phase2A5PackageIntegrityError,
    )
    template_by_blind = {
        review["blind_case_id"]: review for review in template["reviews"]
    }
    status_counts: Counter[str] = Counter()
    for review, reveal in zip(reviews, reveals, strict=True):
        blind = review["blind_case_id"]
        _validate_schema(review, review_schema, f"{export_path.name}:{blind}")
        original = template_by_blind[blind]
        for family in ALL_METHOD_FAMILIES:
            if _immutable_method_metadata(
                review["method_comparisons"][family]
            ) != _immutable_method_metadata(
                original["method_comparisons"][family]
            ):
                raise Phase2A5PackageIntegrityError(
                    f"review changed immutable method metadata: {blind}/{family}"
                )
        if reveal["revealed"]:
            if (
                not _primary_assessment_complete(review)
                or reveal["locked_primary"] != _primary_snapshot(review)
            ):
                raise Phase2A5PackageIntegrityError(
                    f"revealed comparisons do not preserve primary lock: {blind}"
                )
        elif reveal["locked_primary"] is not None or _method_assessment_started(
            review
        ):
            raise Phase2A5PackageIntegrityError(
                f"method fields or primary lock precede reveal: {blind}"
            )
        if review["review_status"] == "complete":
            reviewer = review["reviewer"]
            if not (
                reviewer["pseudonymous_id"]
                and reviewer["qualification_attested"] is True
                and reviewer["independence_attested"] is True
                and _primary_assessment_complete(review)
                and review["usability"]["review_duration_seconds"] is not None
            ):
                raise Phase2A5PackageIntegrityError(
                    f"complete review lacks required primary fields: {blind}"
                )
            for family in ALL_METHOD_FAMILIES:
                method = review["method_comparisons"][family]
                if method["availability"] != "not_generated_in_2a3" and not all(
                    (
                        method["preference"],
                        method["reviewer_confidence"],
                        method["evidence_reason"],
                    )
                ):
                    raise Phase2A5PackageIntegrityError(
                        f"complete review lacks method assessment: {blind}/{family}"
                    )
        status_counts[review["review_status"]] += 1
    reviewer_ids = {
        review["reviewer"]["pseudonymous_id"]
        for review in reviews
        if review["reviewer"]["pseudonymous_id"] is not None
    }
    if len(reviewer_ids) > 1:
        raise Phase2A5PackageIntegrityError(
            "one export contains multiple reviewer identities"
        )
    return {
        "reviewer_slot": slot,
        "assigned_case_count": len(reviews),
        "status_counts": dict(sorted(status_counts.items())),
        "qualified_human_labels_present": any(
            review["review_status"] == "complete" for review in reviews
        ),
        "scientific_decision_produced": False,
    }
