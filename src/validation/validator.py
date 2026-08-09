"""Schema, checksum, identity, and semantic validation for Phase 2A.3."""

from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from shapely.geometry import shape

from src.detection.baseline_manifest import inventory_sha256, sha256_file
from src.detection.identity import (
    canonical_geometry_sha256,
    canonical_sha256,
    identity_sha256,
)
from src.validation.package import (
    METHOD_FAMILIES,
    REQUIRED_EVIDENCE_ROLES,
    _agreement_subset,
    _review_order,
    blank_review,
)
from src.validation.sampling import (
    SAMPLING_DESIGN_VERSION,
    SamplingDesignError,
    _balanced_cell_selection,
)


_CHECKSUM_LINE = re.compile(r"^(?P<sha>[0-9a-f]{64})  (?P<path>[^\n]+)$")
_FORBIDDEN_PREFIXES = ("acq-v1-", "obs-v1-", "evt-v1-")


class ValidationPackageIntegrityError(ValueError):
    """Raised when a generated package violates its integrity contract."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationPackageIntegrityError(f"cannot parse {path}: {exc}") from exc


def _schema(package_root: Path, name: str) -> dict[str, Any]:
    return _load_json(package_root / "schemas" / name)


def _validate_json(value: Any, schema: dict[str, Any], label: str) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise ValidationPackageIntegrityError(
            f"{label} schema violation at {location}: {first.message}"
        )


def _safe_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValidationPackageIntegrityError(f"unsafe package path: {relative}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValidationPackageIntegrityError(
            f"package path escapes root: {relative}"
        ) from exc
    return resolved


def _verify_artifacts(root: Path, manifest: dict[str, Any]) -> None:
    actual_files = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValidationPackageIntegrityError(f"symlink is forbidden: {path}")

    inventory = manifest["artifact_inventory"]
    inventory_paths = [item["path"] for item in inventory]
    if len(inventory_paths) != len(set(inventory_paths)):
        raise ValidationPackageIntegrityError("duplicate artifact inventory path")
    expected = set(inventory_paths) | {"manifest.json", "CHECKSUMS.sha256"}
    if set(actual_files) != expected:
        missing = sorted(expected - set(actual_files))
        unlisted = sorted(set(actual_files) - expected)
        raise ValidationPackageIntegrityError(
            f"package inventory mismatch; missing={missing}, unlisted={unlisted}"
        )
    for item in inventory:
        path = _safe_path(root, item["path"])
        if not path.is_file():
            raise ValidationPackageIntegrityError(f"missing artifact: {item['path']}")
        if path.stat().st_size != item["bytes"]:
            raise ValidationPackageIntegrityError(f"byte mismatch: {item['path']}")
        if sha256_file(path) != item["sha256"]:
            raise ValidationPackageIntegrityError(f"SHA-256 mismatch: {item['path']}")

    checksum_path = root / "CHECKSUMS.sha256"
    recorded: dict[str, str] = {}
    for number, line in enumerate(
        checksum_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = _CHECKSUM_LINE.fullmatch(line)
        if match is None:
            raise ValidationPackageIntegrityError(
                f"invalid CHECKSUMS.sha256 line {number}"
            )
        relative = match.group("path")
        if relative in recorded:
            raise ValidationPackageIntegrityError(
                f"duplicate checksum entry: {relative}"
            )
        recorded[relative] = match.group("sha")
    checksum_expected = expected - {"CHECKSUMS.sha256"}
    if set(recorded) != checksum_expected:
        raise ValidationPackageIntegrityError("checksum inventory does not reconcile")
    for relative, digest in recorded.items():
        if sha256_file(_safe_path(root, relative)) != digest:
            raise ValidationPackageIntegrityError(
                f"checksum-file mismatch: {relative}"
            )


def _verify_source_snapshot(
    root: Path, sources: dict[str, Any], source_dir: Path | None
) -> None:
    population = sources["source_population"]
    artifacts = population["artifacts"]
    if inventory_sha256(artifacts) != population["artifact_inventory_sha256"]:
        raise ValidationPackageIntegrityError("source artifact inventory hash mismatch")
    if sum(item["feature_count"] for item in artifacts) != population["feature_count"]:
        raise ValidationPackageIntegrityError("source feature counts do not reconcile")
    if source_dir is None:
        return
    source_dir = source_dir.resolve()
    for item in artifacts:
        path = source_dir / item["path_label"]
        if not path.is_file():
            raise ValidationPackageIntegrityError(
                f"source artifact missing during revalidation: {item['path_label']}"
            )
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValidationPackageIntegrityError(
                f"source artifact changed: {item['path_label']}"
            )


def _verify_frame(
    root: Path,
    manifest: dict[str, Any],
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    sampling = manifest["sampling"]
    seed = sampling["random_seed"]
    source_count = eligible_count = excluded_count = selected_count = 0
    selected_ids: set[str] = set()
    selected_records: dict[str, dict[str, Any]] = {}
    cell_records: dict[str, list[dict[str, Any]]] = {}
    frame_path = root / "sampling" / "frame.jsonl.gz"
    with gzip.open(frame_path, "rt", encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            source_count += 1
            try:
                unit = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationPackageIntegrityError(
                    f"invalid frame JSON line {number}: {exc}"
                ) from exc
            source_record_id = unit.get("source_record_id")
            if source_record_id is not None:
                expected_source = "p2a3-audit-location-v1-" + identity_sha256(
                    "phase2a3-audit-location-v1",
                    SAMPLING_DESIGN_VERSION,
                    unit["source_artifact_sha256"],
                    f"{unit['source_feature_index']:09d}",
                    unit["geometry_sha256"],
                )
                if source_record_id != expected_source:
                    raise ValidationPackageIntegrityError(
                        f"source record ID mismatch on frame line {number}"
                    )
                expected_rank = identity_sha256(
                    "phase2a3-unit-rank-v1", seed, source_record_id
                )
                if unit.get("random_rank") != expected_rank:
                    raise ValidationPackageIntegrityError(
                        f"random rank mismatch on frame line {number}"
                    )
            if unit.get("canonical_observation_id") is not None or unit.get(
                "canonical_event_id"
            ) is not None:
                raise ValidationPackageIntegrityError(
                    "legacy frame contains an invented canonical identity"
                )
            if unit["eligible"]:
                eligible_count += 1
                cell_records.setdefault(unit["joint_stratum_id"], []).append(unit)
                population = unit["joint_stratum_population"]
                expected_probability = (
                    1.0 / population if unit["selected_joint_stratum"] else 0.0
                )
                if not math.isclose(
                    unit["selection_probability"],
                    expected_probability,
                    rel_tol=0,
                    abs_tol=1e-15,
                ):
                    raise ValidationPackageIntegrityError(
                        f"selection probability mismatch on frame line {number}"
                    )
            else:
                excluded_count += 1
                if unit["selection_probability"] != 0 or unit["selected"]:
                    raise ValidationPackageIntegrityError(
                        "excluded unit has positive probability or is selected"
                    )
            if unit["selected"]:
                selected_count += 1
                expected_sample = "p2a3-sample-v1-" + identity_sha256(
                    "phase2a3-sample-v1",
                    SAMPLING_DESIGN_VERSION,
                    seed,
                    source_record_id,
                )
                if unit["sample_id"] != expected_sample:
                    raise ValidationPackageIntegrityError(
                        f"sample ID mismatch on frame line {number}"
                    )
                selected_ids.add(expected_sample)
                selected_records[expected_sample] = unit

    if source_count != sampling["source_feature_count"]:
        raise ValidationPackageIntegrityError("frame feature count mismatch")
    if eligible_count != sampling["eligible_count"]:
        raise ValidationPackageIntegrityError("frame eligible count mismatch")
    if excluded_count != sampling["excluded_count"]:
        raise ValidationPackageIntegrityError("frame exclusion count mismatch")
    if selected_count != sampling["actual_size"]:
        raise ValidationPackageIntegrityError("frame selected count mismatch")

    actual_selected_cells: set[str] = set()
    for cell_id, members in cell_records.items():
        if any(
            member["joint_stratum_population"] != len(members)
            for member in members
        ):
            raise ValidationPackageIntegrityError(
                f"joint-stratum population mismatch: {cell_id}"
            )
        selected_cell_values = {member["selected_joint_stratum"] for member in members}
        if len(selected_cell_values) != 1:
            raise ValidationPackageIntegrityError(
                f"inconsistent joint-stratum selection: {cell_id}"
            )
        chosen = [member for member in members if member["selected"]]
        if True in selected_cell_values:
            actual_selected_cells.add(cell_id)
            if len(chosen) != 1:
                raise ValidationPackageIntegrityError(
                    f"selected joint stratum must contain one draw: {cell_id}"
                )
            expected = min(
                members,
                key=lambda member: (
                    member["random_rank"],
                    member["source_record_id"],
                ),
            )
            if chosen[0]["source_record_id"] != expected["source_record_id"]:
                raise ValidationPackageIntegrityError(
                    f"selected unit is not the lowest seeded rank: {cell_id}"
                )
        elif chosen:
            raise ValidationPackageIntegrityError(
                f"unselected joint stratum contains a draw: {cell_id}"
            )

    try:
        expected_selected_cells, expected_margins, expected_status = (
            _balanced_cell_selection(
                cell_records,
                target_size=sampling["target_size"],
                seed=seed,
            )
        )
    except SamplingDesignError as exc:
        raise ValidationPackageIntegrityError(
            f"recorded frame cannot reproduce balanced selection: {exc}"
        ) from exc
    if actual_selected_cells != expected_selected_cells:
        raise ValidationPackageIntegrityError(
            "selected joint strata do not match deterministic balanced selection"
        )
    if expected_margins != sampling["sample_margins"]:
        raise ValidationPackageIntegrityError(
            "recorded sample margins do not match deterministic targets"
        )
    if expected_status != sampling["balance_status"]:
        raise ValidationPackageIntegrityError(
            "recorded balance status does not match deterministic selection"
        )

    with gzip.open(
        root / "sampling" / "exclusions.jsonl.gz", "rt", encoding="utf-8"
    ) as exclusions:
        exclusion_lines = sum(1 for _ in exclusions)
    if exclusion_lines != excluded_count:
        raise ValidationPackageIntegrityError("exclusion file count mismatch")
    return selected_ids, selected_records


def _verify_cases(
    root: Path,
    manifest: dict[str, Any],
    selected_ids: set[str],
    selected_records: dict[str, dict[str, Any]],
) -> None:
    case_schema = _schema(root, "validation-case-v1.schema.json")
    review_schema = _schema(root, "validation-review-v1.schema.json")
    seed = manifest["sampling"]["random_seed"]
    sample = _load_json(root / "sampling" / "sample.geojson")
    sample_by_id = {
        feature["properties"]["sample_id"]: feature
        for feature in sample["features"]
    }
    sample_ids = set(sample_by_id)
    if sample_ids != selected_ids or len(sample["features"]) != manifest["sampling"]["actual_size"]:
        raise ValidationPackageIntegrityError("sample GeoJSON does not match frame")
    for sample_id, feature in sample_by_id.items():
        props = feature["properties"]
        if props["canonical_observation_id"] is not None or props["canonical_event_id"] is not None:
            raise ValidationPackageIntegrityError("sample invents a canonical identity")
        canonical, digest = canonical_geometry_sha256(shape(feature["geometry"]))
        unit = selected_records[sample_id]
        if digest != unit["geometry_sha256"] or canonical != feature["geometry"]:
            raise ValidationPackageIntegrityError(
                f"sample geometry does not match frame: {sample_id}"
            )
        if props["source_record_id"] != unit["source_record_id"]:
            raise ValidationPackageIntegrityError(
                f"sample source identity does not match frame: {sample_id}"
            )

    for variable, expected in manifest["sampling"]["sample_margins"].items():
        actual = dict(
            sorted(Counter(unit["strata"][variable] for unit in selected_records.values()).items())
        )
        if actual != expected:
            raise ValidationPackageIntegrityError(
                f"sample margin mismatch: {variable}"
            )

    crosswalk = _load_json(root / "coordinator" / "crosswalk.json")
    mappings = crosswalk["mappings"]
    if crosswalk["population_snapshot_id"] != manifest["population_snapshot_id"]:
        raise ValidationPackageIntegrityError("crosswalk population mismatch")
    if len(mappings) != len(selected_ids) or {
        item["sample_id"] for item in mappings
    } != selected_ids:
        raise ValidationPackageIntegrityError("crosswalk does not cover selected sample")
    if mappings != sorted(mappings, key=lambda item: item["sample_id"]):
        raise ValidationPackageIntegrityError("crosswalk is not in stable sample order")
    expected_agreement = _agreement_subset(list(selected_records.values()), seed)
    for mapping in mappings:
        expected_blind = "p2a3-blind-v1-" + identity_sha256(
            "phase2a3-blind-case-v1", seed, mapping["sample_id"]
        )[:24]
        if mapping["blind_case_id"] != expected_blind:
            raise ValidationPackageIntegrityError("blind case ID mismatch")
        if mapping["double_review"] != (
            mapping["sample_id"] in expected_agreement
        ):
            raise ValidationPackageIntegrityError("agreement subset mismatch")
    mapping_by_blind = {item["blind_case_id"]: item for item in mappings}
    blind_ids = set(mapping_by_blind)
    if len(blind_ids) != len(mappings):
        raise ValidationPackageIntegrityError("duplicate blind case ID")

    expected_double = {
        item["blind_case_id"] for item in mappings if item["double_review"]
    }
    if len(expected_double) != manifest["review"]["double_review_case_count"]:
        raise ValidationPackageIntegrityError("double-review count mismatch")

    cases_a: dict[str, dict[str, Any]] = {}
    for slot, expected_ids in (
        ("reviewer-a", blind_ids),
        ("reviewer-b", expected_double),
    ):
        reviewer_root = root / slot
        if not (reviewer_root / "PROTOCOL.md").is_file():
            raise ValidationPackageIntegrityError(f"{slot} protocol is missing")
        assignment = _load_json(reviewer_root / "assignment.json")
        expected_order = _review_order(
            mappings if slot == "reviewer-a" else [
                item for item in mappings if item["double_review"]
            ],
            seed=seed,
            reviewer_slot=slot,
        )
        if assignment["reviewer_slot"] != slot or assignment["blind_case_ids"] != expected_order:
            raise ValidationPackageIntegrityError(f"{slot} assignment order mismatch")
        if len(expected_order) != len(set(expected_order)):
            raise ValidationPackageIntegrityError(f"{slot} assignment has duplicates")

        case_paths = sorted((reviewer_root / "cases").glob("*.json"))
        if {path.stem for path in case_paths} != expected_ids:
            raise ValidationPackageIntegrityError(f"{slot} case inventory mismatch")
        slot_cases: dict[str, dict[str, Any]] = {}
        for path in case_paths:
            case = _load_json(path)
            label = path.relative_to(root).as_posix()
            _validate_json(case, case_schema, label)
            _validate_json(case["review_fields"], review_schema, f"{label}.review_fields")
            if case["review_fields"] != blank_review(case["blind_case_id"]):
                raise ValidationPackageIntegrityError(
                    f"generated case is not a blank review: {label}"
                )
            mapping = mapping_by_blind[case["blind_case_id"]]
            unit = selected_records[mapping["sample_id"]]
            if case["target_date"] != unit["observed_on"]:
                raise ValidationPackageIntegrityError(
                    f"reviewer target date does not match frame: {label}"
                )
            _, case_digest = canonical_geometry_sha256(shape(case["target_geometry"]))
            if case_digest != unit["geometry_sha256"]:
                raise ValidationPackageIntegrityError(
                    f"reviewer geometry does not match frame: {label}"
                )
            for role in REQUIRED_EVIDENCE_ROLES:
                evidence = case["evidence"][role]
                if evidence["role"] != role:
                    raise ValidationPackageIntegrityError(
                        f"evidence role mismatch: {label}/{role}"
                    )
                local_path = evidence["local_path"]
                if local_path is None:
                    continue
                asset = _safe_path(reviewer_root, local_path)
                if (
                    not asset.is_file()
                    or asset.stat().st_size != evidence["local_bytes"]
                    or sha256_file(asset) != evidence["local_sha256"]
                ):
                    raise ValidationPackageIntegrityError(
                        f"case evidence checksum mismatch: {slot}/{local_path}"
                    )
            slot_cases[case["blind_case_id"]] = case
        if slot == "reviewer-a":
            cases_a = slot_cases
        else:
            for case_id, case in slot_cases.items():
                if case["evidence"] != cases_a[case_id]["evidence"]:
                    raise ValidationPackageIntegrityError(
                        f"double-review evidence differs between reviewers: {case_id}"
                    )

        template = _load_json(reviewer_root / "review-template.json")
        expected_reviews = [blank_review(case_id) for case_id in expected_order]
        if (
            template.get("reviewer_slot") != slot
            or template.get("reviews") != expected_reviews
        ):
            raise ValidationPackageIntegrityError(f"{slot} template is not blank or ordered")
        for review in template["reviews"]:
            _validate_json(review, review_schema, f"{slot}/review-template.json")

        html_path = reviewer_root / "index.html"
        html_text = html_path.read_text(encoding="utf-8")
        payload_match = re.search(
            r'<script id="payload" type="application/json">(.*?)</script>',
            html_text,
            flags=re.DOTALL,
        )
        if payload_match is None:
            raise ValidationPackageIntegrityError(f"{slot} HTML payload is missing")
        try:
            payload = json.loads(payload_match.group(1))
        except json.JSONDecodeError as exc:
            raise ValidationPackageIntegrityError(
                f"{slot} HTML payload is invalid: {exc}"
            ) from exc
        if (
            payload.get("reviewer_slot") != slot
            or payload.get("reviews") != expected_reviews
            or payload.get("cases")
            != [slot_cases[case_id] for case_id in expected_order]
        ):
            raise ValidationPackageIntegrityError(f"{slot} HTML payload mismatch")

        reviewer_bytes = b"".join(
            path.read_bytes()
            for path in sorted(reviewer_root.rglob("*"))
            if path.is_file()
        )
        for sample_id in selected_ids:
            if sample_id.encode("utf-8") in reviewer_bytes:
                raise ValidationPackageIntegrityError(
                    f"{slot} exposes coordinator sample IDs"
                )

    evidence_counts: dict[str, dict[str, int]] = {}
    for role in REQUIRED_EVIDENCE_ROLES:
        evidence_counts[role] = dict(
            sorted(Counter(case["evidence"][role]["status"] for case in cases_a.values()).items())
        )
    if evidence_counts != manifest["review"]["evidence_status_counts"]:
        raise ValidationPackageIntegrityError("evidence status counts do not reconcile")

    coordinator_paths = sorted((root / "coordinator" / "cases").glob("*.json"))
    if {path.stem for path in coordinator_paths} != selected_ids:
        raise ValidationPackageIntegrityError("coordinator case inventory mismatch")
    for path in coordinator_paths:
        case = _load_json(path)
        sample_id = path.stem
        mapping = next(item for item in mappings if item["sample_id"] == sample_id)
        unit = selected_records[sample_id]
        if (
            case["sample_id"] != sample_id
            or case["blind_case_id"] != mapping["blind_case_id"]
            or case["identity_disposition"]["canonical_observation_id"] is not None
            or case["identity_disposition"]["canonical_event_id"] is not None
            or case["source"]["source_record_id"] != unit["source_record_id"]
            or case["reviewer_case"] != cases_a[mapping["blind_case_id"]]
        ):
            raise ValidationPackageIntegrityError(
                f"coordinator case does not reconcile: {sample_id}"
            )

    method_key = _load_json(root / "coordinator" / "method-key.json")
    if method_key["method_decision_status"] != "none":
        raise ValidationPackageIntegrityError("method key claims a decision")
    if any(
        value["selected_or_activated"]
        for value in method_key["families"].values()
    ):
        raise ValidationPackageIntegrityError("method key activates an alternative")


def validate_validation_package(
    package_root: Path,
    *,
    source_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate schemas, source/package checksums, and pilot semantics."""
    package_root = Path(package_root).resolve()
    if not package_root.is_dir():
        raise ValidationPackageIntegrityError(
            f"package directory does not exist: {package_root}"
        )
    manifest = _load_json(package_root / "manifest.json")
    manifest_schema = _schema(
        package_root, "validation-pilot-manifest-v1.schema.json"
    )
    _validate_json(manifest, manifest_schema, "manifest.json")
    generation_identity = {
        "generated_at": manifest["generated_at"],
        "generation_command": manifest["generation_command"],
        "runtime_versions": manifest["runtime_versions"],
    }
    expected_package_id = "p2a3-pilot-package-v1-" + identity_sha256(
        "phase2a3-pilot-package-v1",
        manifest["population_snapshot_id"],
        manifest["sampling"]["design_version"],
        manifest["sampling"]["random_seed"],
        str(manifest["sampling"]["target_size"]),
        canonical_sha256(manifest["artifact_inventory"]),
        canonical_sha256(manifest["generator_source_inventory"]),
        canonical_sha256(manifest["evidence_generation"]),
        canonical_sha256(generation_identity),
    )
    if manifest["package_id"] != expected_package_id:
        raise ValidationPackageIntegrityError("package ID does not bind manifest inputs")
    _verify_artifacts(package_root, manifest)
    sources = _load_json(package_root / "sources.json")
    _verify_source_snapshot(package_root, sources, source_dir)
    if sources["population_snapshot_id"] != manifest["population_snapshot_id"]:
        raise ValidationPackageIntegrityError("population snapshot mismatch")
    selected_ids, selected_records = _verify_frame(package_root, manifest)
    _verify_cases(package_root, manifest, selected_ids, selected_records)
    claims = manifest["claims"]
    if not claims["tool_validation_and_usability_only"] or any(
        claims[name]
        for name in (
            "scientific_accuracy_claim",
            "precision_estimate",
            "recall_estimate",
            "omission_estimate",
            "qualified_human_labels_present",
            "method_promoted_or_activated",
            "raw_detection_modified",
        )
    ):
        raise ValidationPackageIntegrityError("manifest exceeds pilot claim boundary")
    return {
        "package_id": manifest["package_id"],
        "source_feature_count": manifest["sampling"]["source_feature_count"],
        "eligible_count": manifest["sampling"]["eligible_count"],
        "sample_size": manifest["sampling"]["actual_size"],
        "double_review_size": manifest["review"]["double_review_case_count"],
        "artifact_count": len(manifest["artifact_inventory"]) + 2,
        "status": "valid",
    }


def validate_review_export(
    package_root: Path,
    review_export_path: Path,
) -> dict[str, Any]:
    """Validate one isolated reviewer export without calculating accuracy."""
    package_root = Path(package_root).resolve()
    review_export_path = Path(review_export_path).resolve()
    root_manifest = _load_json(package_root / "manifest.json")
    if root_manifest.get("package_type") == "phase2a4_provisional_blinded_method_comparison_derivative":
        from src.validation.phase2a4_package import validate_phase2a4_review_export

        return validate_phase2a4_review_export(package_root, review_export_path)
    validate_validation_package(package_root)
    export = _load_json(review_export_path)
    if set(export) != {"schema_version", "reviewer_slot", "reviews"}:
        raise ValidationPackageIntegrityError(
            "review export must contain only schema_version, reviewer_slot, and reviews"
        )
    if export["schema_version"] != "1.0.0":
        raise ValidationPackageIntegrityError("review export schema version mismatch")
    slot = export["reviewer_slot"]
    if slot not in {"reviewer-a", "reviewer-b"}:
        raise ValidationPackageIntegrityError("unknown reviewer slot")
    reviewer_root = package_root / slot
    assignment = _load_json(reviewer_root / "assignment.json")
    reviews = export["reviews"]
    if not isinstance(reviews, list):
        raise ValidationPackageIntegrityError("reviews must be an array")
    review_ids = [review.get("blind_case_id") for review in reviews]
    if review_ids != assignment["blind_case_ids"] or len(review_ids) != len(
        set(review_ids)
    ):
        raise ValidationPackageIntegrityError(
            "review export IDs/order do not match the isolated assignment"
        )
    review_schema = _schema(package_root, "validation-review-v1.schema.json")
    template = _load_json(reviewer_root / "review-template.json")
    template_by_id = {
        review["blind_case_id"]: review for review in template["reviews"]
    }
    for review in reviews:
        _validate_json(review, review_schema, review_export_path.name)
        original = template_by_id[review["blind_case_id"]]
        for family in METHOD_FAMILIES:
            actual_method = review["method_comparisons"][family]
            original_method = original["method_comparisons"][family]
            for immutable in (
                "availability",
                "option_a",
                "option_b",
                "display_order",
                "selected_or_activated",
            ):
                if actual_method[immutable] != original_method[immutable]:
                    raise ValidationPackageIntegrityError(
                        f"review export changed immutable method metadata: "
                        f"{review['blind_case_id']}/{family}/{immutable}"
                    )
            if (
                review["review_status"] == "complete"
                and actual_method["availability"] == "available"
                and (
                    actual_method["preference"] is None
                    or actual_method["reviewer_confidence"] is None
                    or not actual_method["evidence_reason"]
                )
            ):
                raise ValidationPackageIntegrityError(
                    f"complete review lacks available method assessment: "
                    f"{review['blind_case_id']}/{family}"
                )
    reviewer_ids = {
        review["reviewer"]["pseudonymous_id"]
        for review in reviews
        if review["reviewer"]["pseudonymous_id"] is not None
    }
    if len(reviewer_ids) > 1:
        raise ValidationPackageIntegrityError(
            "one reviewer export contains multiple pseudonymous reviewer IDs"
        )
    status_counts = dict(sorted(Counter(review["review_status"] for review in reviews).items()))
    return {
        "reviewer_slot": slot,
        "assigned_case_count": len(reviews),
        "status_counts": status_counts,
        "claim_scope": "review_process_validation_only_no_accuracy_metrics",
        "status": "valid",
    }
