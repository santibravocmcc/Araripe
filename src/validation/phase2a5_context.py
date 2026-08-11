"""Versioned, non-destructive MapBiomas context for Package 2A.5.

The national rasters are immutable local inputs.  This module verifies their
registered bytes and headers, copies the exact registered native-grid windows
to ignored regional GeoTIFFs without resampling, and records every transform,
histogram, coverage denominator, and checksum in a local audit artifact.

The pure helpers deliberately return annotations.  They never filter a raw
detection, treat MapBiomas as truth, select a threshold, infer a cause, or
alter a Phase 2A.4 method.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import numpy as np
import rasterio
from jsonschema import Draft202012Validator, FormatChecker
from rasterio.transform import Affine, array_bounds
from rasterio.windows import Window, from_bounds


SCHEMA_VERSION = "1.0.0"
PIPELINE_VERSION = "phase2a5-mapbiomas-context-v1"
ARTIFACT_TYPE = "phase2a5_mapbiomas_context"
MANIFEST_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a5-context-manifest-v1.schema.json"
)
REGISTRY_SCHEMA_URL = (
    "https://observatoriodachapadadoararipe.com/data/schemas/"
    "phase2a5-context-candidate-registry-v1.schema.json"
)
COL3_KEY = "mapbiomas_col3_beta_10m_2024"
COL10_KEY = "mapbiomas_col10_1_30m_2024"
COLLECTION_KEYS = (COL3_KEY, COL10_KEY)
CATEGORIES = (
    "natural_vegetation",
    "other_natural_cover",
    "anthropic_cover",
    "uncertain_or_mixed",
    "nodata",
    "unmapped",
)
ASSESSED_SIGNATURE_LABELS = (
    "fire_like",
    "exposed_soil_or_clearing_like",
    "mixed_or_uncertain",
)
SIGNATURE_LABELS = (*ASSESSED_SIGNATURE_LABELS, "not_assessed")
EXPECTED_EXTENT_SOURCE_SHA256 = (
    "2bff31afa6cb74630a437b4fffb96ad88f7f873a3aa1461f337c66f61c209881"
)
EXPECTED_REGISTRY_SHA256 = (
    "848216d90cd95c4886aaade2f5125237517f2dfb3f151dcbc36f349b6d9e3d88"
)
EXPECTED_SOURCE_BINDINGS = {
    COL3_KEY: {
        "local_path": "data/landcover/updated/brazil_lulc_10m_2024.tif",
        "bytes": 6_766_932_375,
        "sha256": "2ba20d400976020b4e7472a37de04fe1755c6f23631008b39da388001a034f59",
        "atbd_path": "data/landcover/updated/ATBD_Col3_10m_Caatinga_v1.pdf",
        "atbd_bytes": 3_364_548,
        "atbd_sha256": "21f960d54b75303a33fcf74d59a91b9575959e6421e3e1b101b4523efa1472b4",
    },
    COL10_KEY: {
        "local_path": "data/landcover/updated/brazil_coverage_2024.tif",
        "bytes": 802_022_037,
        "sha256": "1be96442929c98cdbe0126d5c83d65a8142b61642ec14fb0ad1dfdfa3bf68d6c",
        "atbd_path": "data/landcover/updated/ATBD-Collection-10.1.pdf",
        "atbd_bytes": 4_476_538,
        "atbd_sha256": "859f388422e25aacaaa2fe8024ed631496fc24a1be237a88d58732439ab2ed19",
    },
}


class Phase2A5ContextError(ValueError):
    """Raised when a source, crop, mapping, or provenance binding diverges."""


def _acquire_build_lock(target: Path) -> Path:
    """Reserve one sibling lock without replacing a stale or active lock."""
    lock = target.parent / f".{target.name}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise Phase2A5ContextError(
            f"exclusive build lock already exists; refusing to continue: {lock}"
        ) from exc
    except OSError as exc:
        raise Phase2A5ContextError(f"cannot create exclusive build lock {lock}: {exc}") from exc
    try:
        os.write(descriptor, f"target={target.name}\n".encode("utf-8"))
    except OSError as exc:
        try:
            lock.unlink()
        except OSError:
            pass
        raise Phase2A5ContextError(f"cannot initialize exclusive build lock {lock}: {exc}") from exc
    finally:
        os.close(descriptor)
    return lock


def _release_build_lock(lock: Path) -> None:
    try:
        lock.unlink()
    except FileNotFoundError:
        pass


def _publish_file_no_clobber(source: Path, destination: Path) -> None:
    """Publish one same-filesystem file atomically without replacing any path."""
    linked = False
    try:
        os.link(source, destination)
        linked = True
        source.unlink()
    except FileExistsError as exc:
        raise Phase2A5ContextError(
            f"regional crop appeared during build; refusing overwrite: {destination}"
        ) from exc
    except OSError as exc:
        if linked:
            try:
                destination.unlink()
            except OSError:
                pass
        raise Phase2A5ContextError(
            f"cannot publish regional crop without clobbering {destination}: {exc}"
        ) from exc


def _publish_directory_no_clobber(staging: Path, target: Path) -> None:
    """Publish a staged directory under the cooperative exclusive build lock."""
    if os.path.lexists(target):
        raise Phase2A5ContextError(
            f"context artifact appeared during build; refusing overwrite: {target}"
        )
    try:
        staging.rename(target)
    except FileExistsError as exc:
        raise Phase2A5ContextError(
            f"context artifact appeared during build; refusing overwrite: {target}"
        ) from exc
    except OSError as exc:
        raise Phase2A5ContextError(f"cannot publish context artifact {target}: {exc}") from exc


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
        raise Phase2A5ContextError(f"value is not canonical JSON: {exc}") from exc


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
        raise Phase2A5ContextError(f"cannot parse {path}: {exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _parse_timestamp(value: str, *, label: str) -> None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise Phase2A5ContextError(
            f"{label} must be a timezone-aware RFC3339 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Phase2A5ContextError(f"{label} must include an explicit UTC offset")


def _safe_relative(root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise Phase2A5ContextError(f"path escapes artifact root: {path}") from exc
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        raise Phase2A5ContextError(f"unsafe artifact path: {relative!r}")
    return relative


def _safe_artifact_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise Phase2A5ContextError(f"unsafe artifact path: {relative}")
    path = (root / candidate).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise Phase2A5ContextError(f"artifact path escapes root: {relative}") from exc
    return path


def _artifact(path: Path, root: Path, **extra: Any) -> dict[str, Any]:
    if not path.is_file():
        raise Phase2A5ContextError(f"artifact missing: {path}")
    return {
        "path": _safe_relative(root, path),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        **extra,
    }


def _external_artifact(path: Path, repository_root: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Phase2A5ContextError(f"external input missing: {path}")
    return {
        "path": path.resolve().relative_to(repository_root.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        "scope": "repository_relative_external_input",
    }


def _xattr_bytes(path: Path, name: str) -> bytes:
    """Read provenance xattrs without opening or rewriting the source file."""
    try:
        completed = subprocess.run(
            ["xattr", "-p", name, str(path)],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Phase2A5ContextError(
            f"required access-provenance xattr {name!r} is unavailable for {path}"
        ) from exc
    return completed.stdout


def _verify_access_evidence(
    path: Path,
    record: Mapping[str, Any],
    *,
    source_record: bool,
) -> dict[str, Any]:
    """Verify the exact browser-origin and quarantine records pinned in the registry."""
    origin_name = (
        str(record["browser_origin_xattr"])
        if source_record
        else "com.apple.metadata:kMDItemWhereFroms"
    )
    quarantine_name = (
        str(record["quarantine_xattr"])
        if source_record
        else "com.apple.quarantine"
    )
    origin_raw = _xattr_bytes(path, origin_name)
    quarantine_raw = _xattr_bytes(path, quarantine_name)
    if hashlib.sha256(origin_raw).hexdigest() != record["browser_origin_xattr_sha256"]:
        raise Phase2A5ContextError(f"browser-origin evidence changed for {path}")
    if hashlib.sha256(quarantine_raw).hexdigest() != record["quarantine_xattr_sha256"]:
        raise Phase2A5ContextError(f"browser quarantine evidence changed for {path}")
    # The retained macOS value is a byte-truncated binary-plist fragment rather
    # than a parseable standalone plist.  Its exact SHA-256 is the primary
    # evidence; requiring the registered URL bytes prevents a digest-only
    # record from obscuring what the browser stored.
    if str(record["origin_url"]).encode("utf-8") not in origin_raw:
        raise Phase2A5ContextError(f"registered origin URL is absent from browser evidence: {path}")
    try:
        quarantine = quarantine_raw.decode("utf-8")
        fields = quarantine.split(";")
    except UnicodeDecodeError as exc:
        raise Phase2A5ContextError(f"browser quarantine evidence is not UTF-8: {path}") from exc
    if len(fields) < 3:
        raise Phase2A5ContextError(f"browser quarantine evidence is malformed: {path}")
    if source_record:
        if fields[1].lower() != str(record["timestamp_hex_seconds"]).lower():
            raise Phase2A5ContextError(f"browser access timestamp changed for {path}")
        if fields[2] != record["browser_agent"]:
            raise Phase2A5ContextError(f"browser access agent changed for {path}")
    return {
        "browser_origin_url": record["origin_url"],
        "browser_origin_xattr_sha256": hashlib.sha256(origin_raw).hexdigest(),
        "quarantine_xattr_sha256": hashlib.sha256(quarantine_raw).hexdigest(),
        "quarantine_timestamp_hex_seconds": fields[1],
        "browser_agent": fields[2],
        "registry_accessed_at": record["accessed_at"],
        "verified": True,
    }


def _validate_schema(value: Any, schema: Mapping[str, Any], *, label: str) -> None:
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise Phase2A5ContextError(
            f"{label} schema violation at {location}: {first.message}"
        )


def _require_keys(value: Mapping[str, Any], keys: Iterable[str], *, label: str) -> None:
    missing = sorted(set(keys) - set(value))
    if missing:
        raise Phase2A5ContextError(f"{label} missing keys: {missing}")


def _mapping_lookup(registry: Mapping[str, Any], collection_key: str) -> dict[int, str]:
    if collection_key not in COLLECTION_KEYS:
        raise Phase2A5ContextError(f"unknown collection key: {collection_key}")
    mappings = registry["class_mappings"][collection_key]
    lookup: dict[int, str] = {}
    for category in CATEGORIES[:-1]:
        for raw_code in mappings.get(category, []):
            code = int(raw_code)
            previous = lookup.setdefault(code, category)
            if previous != category:
                raise Phase2A5ContextError(
                    f"class {code} appears in both {previous} and {category}"
                )
    return lookup


def _validate_registry_semantics(registry: Mapping[str, Any]) -> None:
    _require_keys(
        registry,
        (
            "$schema",
            "schema_version",
            "registry_id",
            "monitoring_extent",
            "sources",
            "crop_policy",
            "grid_reconciliation",
            "class_mappings",
            "strong_subset",
            "contextual_signature",
            "licence_and_attribution",
            "decision_state",
        ),
        label="context registry",
    )
    if registry["$schema"] != REGISTRY_SCHEMA_URL or registry["schema_version"] != SCHEMA_VERSION:
        raise Phase2A5ContextError("unexpected context registry schema identity")
    if registry["monitoring_extent"]["source_aoi_sha256"] != EXPECTED_EXTENT_SOURCE_SHA256:
        raise Phase2A5ContextError("accepted extent source checksum changed")
    if set(registry["sources"]) != set(COLLECTION_KEYS):
        raise Phase2A5ContextError("registry source population changed")
    if set(registry["crop_policy"]["crops"]) != set(COLLECTION_KEYS):
        raise Phase2A5ContextError("registry crop population changed")
    if registry["crop_policy"]["resampling"] != "none":
        raise Phase2A5ContextError("native categorical crops must not resample")
    if registry["grid_reconciliation"]["comparison_resampling"] != "nearest_only":
        raise Phase2A5ContextError("categorical reconciliation must use nearest only")
    if registry["class_mappings"]["unknown_code_policy"] != (
        "explicit_unmapped_not_forced_into_any_preferred_category"
    ):
        raise Phase2A5ContextError("unknown MapBiomas codes must remain explicit")
    for collection_key in COLLECTION_KEYS:
        lookup = _mapping_lookup(registry, collection_key)
        source = registry["sources"][collection_key]
        expected_binding = EXPECTED_SOURCE_BINDINGS[collection_key]
        actual_binding = {
            "local_path": source["local_path"],
            "bytes": source["bytes"],
            "sha256": source["sha256"],
            "atbd_path": source["atbd"]["local_path"],
            "atbd_bytes": source["atbd"]["bytes"],
            "atbd_sha256": source["atbd"]["sha256"],
        }
        if actual_binding != expected_binding:
            raise Phase2A5ContextError(f"{collection_key} immutable source binding changed")
        inventory = source["national_inventory"]
        histogram = {int(code): int(count) for code, count in inventory["class_histogram"].items()}
        observed = {code for code, count in histogram.items() if count > 0}
        if observed != set(lookup):
            raise Phase2A5ContextError(
                f"{collection_key} class mapping must cover exactly the observed inventory"
            )
        total = int(source["header"]["width"]) * int(source["header"]["height"])
        if sum(histogram.values()) != total or int(inventory["total_pixel_count"]) != total:
            raise Phase2A5ContextError(f"{collection_key} national inventory total changed")
        nodata_count = histogram.get(int(source["nodata_policy"]["context_value"]), 0)
        if (
            int(inventory["nodata_pixel_count"]) != nodata_count
            or int(inventory["valid_pixel_count"]) != total - nodata_count
        ):
            raise Phase2A5ContextError(f"{collection_key} national NoData accounting changed")
        crop = registry["crop_policy"]["crops"][collection_key]
        crop_histogram = {int(code): int(count) for code, count in crop["expected_class_histogram"].items()}
        crop_total = int(crop["width"]) * int(crop["height"])
        crop_nodata = crop_histogram.get(int(crop["output_nodata"]), 0)
        if (
            sum(crop_histogram.values()) != crop_total
            or int(crop["expected_total_pixel_count"]) != crop_total
            or int(crop["expected_nodata_pixel_count"]) != crop_nodata
            or int(crop["expected_valid_pixel_count"]) != crop_total - crop_nodata
        ):
            raise Phase2A5ContextError(f"{collection_key} registered crop accounting changed")
    strong = registry["strong_subset"]
    if strong["candidate_ids"] != [
        "natural-vegetation-share-0.50-v1",
        "natural-vegetation-share-0.75-v1",
    ]:
        raise Phase2A5ContextError("strong-subset candidate identity changed")
    if [candidate["threshold"] for candidate in strong["candidates"]] != [0.5, 0.75]:
        raise Phase2A5ContextError("strong-subset thresholds changed")
    if any(candidate["selected_or_activated"] for candidate in strong["candidates"]):
        raise Phase2A5ContextError("strong-subset candidate was selected or activated")
    signatures = registry["contextual_signature"]
    if signatures["candidate_ids"] != [
        "dominant-assessed-share-0.60-v1",
        "plurality-assessed-margin-0.15-v1",
    ]:
        raise Phase2A5ContextError("contextual-signature candidates changed")
    if signatures.get("all_touched") is not False:
        raise Phase2A5ContextError("spectral polygon rule must use detector-grid centers")
    if signatures["causal_inference_permitted"] is not False:
        raise Phase2A5ContextError("causal inference cannot be enabled")
    if any(candidate["selected_or_activated"] for candidate in signatures["candidates"]):
        raise Phase2A5ContextError("contextual-signature candidate was selected")
    if any(value is not False for value in registry["decision_state"].values()):
        raise Phase2A5ContextError("Package 2A.5 scientific decision state must remain open")
    primary = registry["sources"][COL3_KEY]["header"]
    secondary = registry["sources"][COL10_KEY]["header"]
    primary_resolution = float(primary["transform"][0])
    secondary_resolution = float(secondary["transform"][0])
    ratio = secondary_resolution / primary_resolution
    x_offset = (float(secondary["transform"][2]) - float(primary["transform"][2])) / primary_resolution
    y_offset = (float(primary["transform"][5]) - float(secondary["transform"][5])) / primary_resolution
    reconciliation = registry["grid_reconciliation"]
    tolerance = float(reconciliation["absolute_tolerance_primary_pixels"])
    expected_ratio = int(reconciliation["resolution_ratio_secondary_to_primary"])
    expected_x, expected_y = reconciliation["secondary_origin_offset_primary_pixels"]
    if (
        abs(ratio - expected_ratio) > tolerance
        or abs(x_offset - int(expected_x)) > tolerance
        or abs(y_offset - int(expected_y)) > tolerance
    ):
        raise Phase2A5ContextError("registered MapBiomas grids are not integer aligned")


def load_context_registry(
    path: Path,
    *,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    """Load and semantically validate the fixed pre-outcome registry."""
    resolved_path = Path(path).resolve()
    if _sha256_file(resolved_path) != EXPECTED_REGISTRY_SHA256:
        raise Phase2A5ContextError("fixed Package 2A.5 registry checksum changed")
    registry = _load_json(resolved_path)
    if not isinstance(registry, Mapping):
        raise Phase2A5ContextError("context registry must be a JSON object")
    if schema_path is not None:
        schema = _load_json(Path(schema_path).resolve())
        _validate_schema(registry, schema, label="context registry")
    _validate_registry_semantics(registry)
    return dict(registry)


def classify_mapbiomas_codes(
    codes: np.ndarray | Sequence[int],
    collection_key: str,
    registry: Mapping[str, Any],
) -> np.ndarray:
    """Map categorical codes without coercing unknown or ambiguous values."""
    lookup = _mapping_lookup(registry, collection_key)
    values = np.asarray(codes)
    labels = np.full(values.shape, "unmapped", dtype="<U24")
    for code, category in lookup.items():
        labels[values == code] = category
    return labels


def summarize_polygon_context(
    values: np.ndarray,
    collection_key: str,
    registry: Mapping[str, Any],
    *,
    valid_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return explicit raw/category/coverage accounting for one polygon."""
    array = np.asarray(values)
    if valid_mask is None:
        selected = np.ones(array.shape, dtype=bool)
    else:
        selected = np.asarray(valid_mask, dtype=bool)
        if selected.shape != array.shape:
            raise Phase2A5ContextError("polygon mask and categorical array shapes differ")
    raw = array[selected]
    labels = classify_mapbiomas_codes(raw, collection_key, registry)
    histogram = {
        str(int(code)): int(count)
        for code, count in zip(*np.unique(raw, return_counts=True), strict=True)
    }
    category_counts = {
        category: int(np.count_nonzero(labels == category)) for category in CATEGORIES
    }
    total = int(raw.size)
    nodata = category_counts["nodata"]
    valid = total - nodata
    mapped_valid = valid - category_counts["unmapped"]
    proportions = {
        category: (
            category_counts[category] / mapped_valid if mapped_valid else None
        )
        for category in CATEGORIES[:4]
    }
    return {
        "collection_id": collection_key,
        "pixel_count": total,
        "total_pixel_count": total,
        "valid_pixel_count": valid,
        "mapped_valid_pixel_count": mapped_valid,
        "nodata_pixel_count": nodata,
        "unmapped_pixel_count": category_counts["unmapped"],
        "valid_coverage_fraction": valid / total if total else None,
        "class_histogram": histogram,
        "category_counts": category_counts,
        "category_proportions": proportions,
    }


def strong_subset_membership(
    natural_fraction: float | None,
    registry: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate every fixed candidate while retaining the source detection."""
    if natural_fraction is not None and not 0 <= float(natural_fraction) <= 1:
        raise Phase2A5ContextError("natural fraction must be in [0, 1] or missing")
    outcomes: dict[str, dict[str, Any]] = {}
    for candidate in registry["strong_subset"]["candidates"]:
        candidate_id = candidate["candidate_id"]
        membership = (
            "not_assessed"
            if natural_fraction is None
            else "included"
            if float(natural_fraction) >= float(candidate["threshold"])
            else "excluded"
        )
        outcomes[candidate_id] = {
            "candidate_id": candidate_id,
            "threshold": float(candidate["threshold"]),
            "natural_fraction": None if natural_fraction is None else float(natural_fraction),
            "membership": membership,
            "reason": "no mapped valid Collection 3 pixels" if natural_fraction is None else None,
            "selected_or_activated": False,
            "raw_detection_retained": True,
        }
    return outcomes


def annotate_threshold_candidates_preserving_raw(
    records: Sequence[Mapping[str, Any]],
    natural_fractions: Sequence[float | None],
    registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Add candidate annotations without dropping, reordering, or relabeling."""
    if len(records) != len(natural_fractions):
        raise Phase2A5ContextError("raw record and natural-fraction counts differ")
    result: list[dict[str, Any]] = []
    for record, fraction in zip(records, natural_fractions, strict=True):
        copied = dict(record)
        copied["phase2a5_strong_subset_candidates"] = strong_subset_membership(
            fraction, registry
        )
        result.append(copied)
    if len(result) != len(records):
        raise Phase2A5ContextError("raw detection count changed")
    for before, after in zip(records, result, strict=True):
        for key, value in before.items():
            if after.get(key) != value:
                raise Phase2A5ContextError("raw detection content changed")
    return result


def calculate_agreement_disagreement(
    primary_codes: np.ndarray,
    secondary_codes: np.ndarray,
    registry: Mapping[str, Any],
    *,
    secondary_is_aligned: bool = False,
) -> dict[str, Any]:
    """Compare aligned categories as context, never as scientific truth."""
    primary = np.asarray(primary_codes)
    secondary = np.asarray(secondary_codes)
    if not secondary_is_aligned:
        raise Phase2A5ContextError(
            "categorical arrays require explicit nearest-aligned secondary evidence"
        )
    if primary.shape != secondary.shape:
        raise Phase2A5ContextError("aligned collection arrays have different shapes")
    left = classify_mapbiomas_codes(primary, COL3_KEY, registry)
    right = classify_mapbiomas_codes(secondary, COL10_KEY, registry)
    joint_valid = (left != "nodata") & (right != "nodata")
    exact_equal = primary == secondary
    joint_valid_count = int(np.count_nonzero(joint_valid))
    exact_agree = int(np.count_nonzero(joint_valid & exact_equal))
    joint_mapped = joint_valid & (left != "unmapped") & (right != "unmapped")
    category_equal = left == right
    joint_mapped_count = int(np.count_nonzero(joint_mapped))
    category_agree = int(np.count_nonzero(joint_mapped & category_equal))
    exact_pairs: Counter[str] = Counter(
        f"{int(a)}|{int(b)}"
        for a, b in zip(primary[joint_valid], secondary[joint_valid], strict=True)
    )
    category_pairs: Counter[str] = Counter(
        f"{a}|{b}" for a, b in zip(left[joint_mapped], right[joint_mapped], strict=True)
    )
    return {
        "status": "available" if joint_mapped_count else "unreviewable",
        "reason": None if joint_mapped_count else "no jointly mapped pixels",
        "comparison_grid": COL3_KEY,
        "resampling": "nearest_only",
        "interpretation": "context_not_scientific_truth",
        "joint_valid_raw_count": joint_valid_count,
        "exact_agreement_count": exact_agree,
        "exact_disagreement_count": joint_valid_count - exact_agree,
        "exact_agreement_fraction": (
            exact_agree / joint_valid_count if joint_valid_count else None
        ),
        "joint_mapped_count": joint_mapped_count,
        "category_agreement_count": category_agree,
        "category_disagreement_count": joint_mapped_count - category_agree,
        "category_agreement_fraction": (
            category_agree / joint_mapped_count if joint_mapped_count else None
        ),
        "exact_pair_histogram": dict(sorted(exact_pairs.items())),
        "category_pair_histogram": dict(sorted(category_pairs.items())),
    }


def classify_contextual_signature_pixels(
    dnbr: np.ndarray,
    post_nbr: np.ndarray,
    bsi: np.ndarray,
) -> np.ndarray:
    """Apply the fixed non-causal pixel rule and retain unassessed values."""
    delta = np.asarray(dnbr)
    post = np.asarray(post_nbr)
    soil = np.asarray(bsi)
    if delta.shape != post.shape or delta.shape != soil.shape:
        raise Phase2A5ContextError("contextual measurement shapes differ")
    labels = np.full(delta.shape, "not_assessed", dtype="<U32")
    finite = np.isfinite(delta) & np.isfinite(post) & np.isfinite(soil)
    fire_like = finite & (delta > 0.27) & (post < 0.10)
    labels[fire_like] = "fire_like"
    exposed = finite & ~fire_like & (soil > 0.10) & (delta > 0.05)
    labels[exposed] = "exposed_soil_or_clearing_like"
    mixed = finite & ~fire_like & ~exposed & (delta > 0.10)
    labels[mixed] = "mixed_or_uncertain"
    return labels


def contextual_signature_proportions(labels: np.ndarray) -> dict[str, Any]:
    """Retain counts and assessed/not-assessed denominators separately."""
    values = np.asarray(labels).astype(str)
    unknown = set(np.unique(values)) - set(SIGNATURE_LABELS)
    if unknown:
        raise Phase2A5ContextError(f"unknown contextual signature labels: {sorted(unknown)}")
    counts = {label: int(np.count_nonzero(values == label)) for label in SIGNATURE_LABELS}
    assessed = sum(counts[label] for label in ASSESSED_SIGNATURE_LABELS)
    total = int(values.size)
    proportions: dict[str, float | None] = {
        label: counts[label] / assessed if assessed else None
        for label in ASSESSED_SIGNATURE_LABELS
    }
    proportions["not_assessed"] = counts["not_assessed"] / total if total else 1.0
    return {
        "counts": counts,
        "class_counts": counts,
        "assessed_pixel_count": assessed,
        "total_pixel_count": total,
        "proportions": proportions,
    }


def aggregate_contextual_signature_candidates(
    strata: Sequence[Mapping[str, Any]],
    registry: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate both polygon rules across every available method stratum."""
    available = [
        stratum
        for stratum in strata
        if stratum.get("status") in {"available", "partial"}
        and sum(
            int(stratum["class_counts"][label]) for label in ASSESSED_SIGNATURE_LABELS
        )
        > 0
    ]
    medians: dict[str, float | None] = {}
    for label in ASSESSED_SIGNATURE_LABELS:
        values = [stratum["proportions"].get(label) for stratum in available]
        finite = [float(value) for value in values if value is not None]
        medians[label] = float(np.median(finite)) if finite else None
    outcomes: dict[str, dict[str, Any]] = {}
    for candidate in registry["contextual_signature"]["candidates"]:
        candidate_id = candidate["candidate_id"]
        if not available or any(value is None for value in medians.values()):
            label = "not_assessed"
            status = "unreviewable"
            reason = "no assessed measurements in any cloud-by-composition stratum"
        else:
            ordered = sorted(
                ((float(value), label) for label, value in medians.items()),
                key=lambda item: (-item[0], item[1]),
            )
            top_share, top_label = ordered[0]
            runner_up = ordered[1][0]
            unique_top = top_share > runner_up
            if candidate["minimum_top_share"] is not None:
                emit = unique_top and top_share >= float(candidate["minimum_top_share"])
            else:
                emit = unique_top and (top_share - runner_up) >= float(
                    candidate["minimum_margin"]
                )
            label = top_label if emit else "mixed_or_uncertain"
            status = (
                "available"
                if len(available) == 4
                and all(stratum.get("status") == "available" for stratum in available)
                else "partial"
            )
            reason = (
                None
                if status == "available"
                else f"{len(available)} of 4 strata contributed assessed evidence"
            )
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


def _runtime_versions() -> dict[str, str]:
    result = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "rasterio": rasterio.__version__,
        "gdal": getattr(rasterio, "__gdal_version__", "unknown"),
        "proj": getattr(rasterio, "__proj_version__", "unknown"),
    }
    for distribution in ("jsonschema",):
        try:
            result[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            result[distribution] = "not-installed"
    return result


def _header_record(dataset: rasterio.io.DatasetReader) -> dict[str, Any]:
    return {
        "driver": dataset.driver,
        "dtype": dataset.dtypes[0],
        "band_count": dataset.count,
        "width": dataset.width,
        "height": dataset.height,
        "crs": dataset.crs.to_string() if dataset.crs else None,
        "transform": list(dataset.transform)[:6],
        "bounds": list(dataset.bounds),
        "nodata": dataset.nodata,
        "area_or_point": dataset.tags().get("AREA_OR_POINT"),
        "tiled": bool(dataset.profile.get("tiled")),
        "block_shape": list(dataset.block_shapes[0]),
        "compression": (
            dataset.compression.name.upper() if dataset.compression is not None else None
        ),
        "predictor": dataset.tags(ns="IMAGE_STRUCTURE").get("PREDICTOR"),
        "overviews": list(dataset.overviews(1)),
    }


def _numeric_equal(left: Any, right: Any, *, tolerance: float = 1e-12) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= tolerance
    if isinstance(left, Sequence) and not isinstance(left, (str, bytes)):
        if not isinstance(right, Sequence) or isinstance(right, (str, bytes)):
            return False
        return len(left) == len(right) and all(
            _numeric_equal(a, b, tolerance=tolerance) for a, b in zip(left, right, strict=True)
        )
    return left == right


def _verify_source_header(
    dataset: rasterio.io.DatasetReader,
    expected: Mapping[str, Any],
    *,
    collection_key: str,
) -> None:
    actual = _header_record(dataset)
    for key in (
        "driver",
        "dtype",
        "band_count",
        "width",
        "height",
        "crs",
        "transform",
        "bounds",
        "nodata",
        "area_or_point",
        "tiled",
        "block_shape",
        "compression",
        "predictor",
        "overviews",
    ):
        if not _numeric_equal(actual[key], expected[key]):
            raise Phase2A5ContextError(
                f"{collection_key} source header {key} mismatch: {actual[key]!r} != {expected[key]!r}"
            )


def _window_from_registry(
    dataset: rasterio.io.DatasetReader,
    registry: Mapping[str, Any],
    collection_key: str,
) -> Window:
    crop = registry["crop_policy"]["crops"][collection_key]
    bounds = registry["monitoring_extent"]["bounds"]
    fractional = from_bounds(*bounds, transform=dataset.transform)
    expected_fractional = crop["fractional_source_window"]
    actual_fractional = [
        fractional.col_off,
        fractional.row_off,
        fractional.width,
        fractional.height,
    ]
    if not _numeric_equal(actual_fractional, expected_fractional, tolerance=1e-8):
        raise Phase2A5ContextError(
            f"{collection_key} fractional extent window changed"
        )
    integer = [int(value) for value in crop["integer_source_window"]]
    expected_outer = [
        int(np.floor(fractional.col_off)),
        int(np.floor(fractional.row_off)),
        int(np.ceil(fractional.col_off + fractional.width))
        - int(np.floor(fractional.col_off)),
        int(np.ceil(fractional.row_off + fractional.height))
        - int(np.floor(fractional.row_off)),
    ]
    if integer != expected_outer:
        raise Phase2A5ContextError(f"{collection_key} registered window is not the exact outer window")
    window = Window(*integer)
    if (
        window.col_off < 0
        or window.row_off < 0
        or window.col_off + window.width > dataset.width
        or window.row_off + window.height > dataset.height
    ):
        raise Phase2A5ContextError(f"{collection_key} crop window escapes source")
    return window


def _histogram(values: np.ndarray) -> dict[str, int]:
    codes, counts = np.unique(np.asarray(values), return_counts=True)
    return {
        str(int(code)): int(count)
        for code, count in zip(codes, counts, strict=True)
    }


def _coverage(values: np.ndarray, nodata_value: int = 0) -> dict[str, Any]:
    total = int(values.size)
    nodata = int(np.count_nonzero(values == nodata_value))
    valid = total - nodata
    return {
        "total_pixel_count": total,
        "valid_pixel_count": valid,
        "nodata_pixel_count": nodata,
        "valid_coverage_fraction": valid / total if total else None,
    }


def _write_crop(
    source: rasterio.io.DatasetReader,
    window: Window,
    destination: Path,
    crop_config: Mapping[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    values = source.read(1, window=window)
    if values.dtype != np.uint8:
        raise Phase2A5ContextError("categorical crop dtype changed")
    transform = source.window_transform(window)
    if not _numeric_equal(list(transform)[:6], crop_config["transform"], tolerance=1e-12):
        raise Phase2A5ContextError("crop transform does not match the registered source window")
    output_bounds = list(array_bounds(values.shape[0], values.shape[1], transform))
    if not _numeric_equal(output_bounds, crop_config["bounds"], tolerance=1e-10):
        raise Phase2A5ContextError("crop bounds do not match the registered source window")
    block_height, block_width = [int(value) for value in crop_config["block_shape"]]
    profile = {
        "driver": "GTiff",
        "height": values.shape[0],
        "width": values.shape[1],
        "count": 1,
        "dtype": "uint8",
        "crs": source.crs,
        "transform": transform,
        "nodata": int(crop_config["output_nodata"]),
        "tiled": True,
        "blockxsize": block_width,
        "blockysize": block_height,
        "compress": "LZW",
        "predictor": 2,
        "interleave": "band",
        "BIGTIFF": "IF_SAFER",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.Env(GDAL_PAM_ENABLED="NO"):
        with rasterio.open(destination, "w", **profile) as output:
            output.write(values, 1)
            output.update_tags(
                AREA_OR_POINT="Area",
                PHASE2A5_TRANSFORM="native_source_grid_outer_window_no_resampling",
            )
    return values, {
        "width": values.shape[1],
        "height": values.shape[0],
        "crs": source.crs.to_string(),
        "transform": list(transform)[:6],
        "bounds": output_bounds,
        "dtype": "uint8",
        "nodata": int(crop_config["output_nodata"]),
        "area_or_point": "Area",
        "tiled": True,
        "block_shape": [block_height, block_width],
        "compression": "LZW",
        "predictor": "2",
        "overviews": [],
        "class_histogram": _histogram(values),
        **_coverage(values, int(crop_config["output_nodata"])),
    }


def _verify_expected_crop_summary(
    summary: Mapping[str, Any], crop: Mapping[str, Any], *, collection_key: str
) -> None:
    expected = {
        "width": crop["width"],
        "height": crop["height"],
        "crs": crop["crs"],
        "transform": crop["transform"],
        "bounds": crop["bounds"],
        "nodata": crop["output_nodata"],
        "area_or_point": "Area",
        "tiled": True,
        "block_shape": crop["block_shape"],
        "compression": "LZW",
        "predictor": "2",
        "overviews": [],
        "class_histogram": crop["expected_class_histogram"],
        "total_pixel_count": crop["expected_total_pixel_count"],
        "valid_pixel_count": crop["expected_valid_pixel_count"],
        "nodata_pixel_count": crop["expected_nodata_pixel_count"],
        "valid_coverage_fraction": crop["expected_valid_coverage_fraction"],
    }
    for key, value in expected.items():
        if not _numeric_equal(summary[key], value, tolerance=1e-10):
            raise Phase2A5ContextError(
                f"{collection_key} crop {key} mismatch: {summary[key]!r} != {value!r}"
            )


def _checksum_inventory(root: Path) -> list[dict[str, Any]]:
    return [
        _artifact(path, root)
        for path in sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.name not in {"manifest.json", "CHECKSUMS.sha256"}
                and "crop-staging" not in path.relative_to(root).parts
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    ]


def _write_checksums(root: Path) -> None:
    paths = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.name != "CHECKSUMS.sha256"
            and "crop-staging" not in path.relative_to(root).parts
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    lines = [f"{_sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in paths]
    (root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _generator_inventory(repository_root: Path) -> list[dict[str, Any]]:
    paths = (
        repository_root / "src/validation/phase2a5_context.py",
        repository_root / "scripts/build_phase2a5_context.py",
        repository_root / "scripts/validate_phase2a5_context.py",
        repository_root / "config/phase2a5_context_candidates_v1.json",
        repository_root
        / "docs/contracts/phase2a/schemas/phase2a5-context-candidate-registry-v1.schema.json",
        repository_root
        / "docs/contracts/phase2a/schemas/phase2a5-context-manifest-v1.schema.json",
    )
    return [
        {
            "path": path.relative_to(repository_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in paths
        if path.is_file()
    ]


def build_phase2a5_context_artifact(
    *,
    repository_root: Path,
    registry_path: Path,
    output_root: Path,
    generated_at: str,
    generation_command: Sequence[str],
) -> dict[str, Any]:
    """Verify sources and atomically create both ignored native-grid crops."""
    repository_root = Path(repository_root).resolve()
    registry_path = Path(registry_path).resolve()
    # Preserve the final path component so a broken symlink remains visible to
    # the no-clobber guards below.  Input paths are still resolved normally.
    output_root = Path(output_root).absolute()
    _parse_timestamp(generated_at, label="generated_at")
    if not generation_command or any(not isinstance(value, str) or not value for value in generation_command):
        raise Phase2A5ContextError("generation_command must contain non-empty strings")
    registry_schema_path = (
        repository_root
        / "docs/contracts/phase2a/schemas/phase2a5-context-candidate-registry-v1.schema.json"
    )
    manifest_schema_path = (
        repository_root
        / "docs/contracts/phase2a/schemas/phase2a5-context-manifest-v1.schema.json"
    )
    for required_schema in (registry_schema_path, manifest_schema_path):
        if not required_schema.is_file():
            raise Phase2A5ContextError(f"required Package 2A.5 schema missing: {required_schema}")
    registry = load_context_registry(
        registry_path,
        schema_path=registry_schema_path,
    )
    crop_destinations = {
        key: repository_root / registry["crop_policy"]["crops"][key]["output_path"]
        for key in COLLECTION_KEYS
    }
    output_root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _acquire_build_lock(output_root)
    staging: Path | None = None
    crop_temps: dict[str, Path] = {}
    moved_crops: list[Path] = []
    published_output = False
    try:
        if os.path.lexists(output_root):
            raise Phase2A5ContextError(
                "context artifact already exists; refusing overwrite"
            )
        existing = [
            path for path in crop_destinations.values() if os.path.lexists(path)
        ]
        if existing:
            raise Phase2A5ContextError(
                f"regional crop already exists; refusing inconsistent rebuild: {existing}"
            )
        staging = Path(
            tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent)
        )
        embedded_registry = staging / "inputs/context-candidate-registry.json"
        embedded_registry.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(registry_path, embedded_registry)
        schema_bindings: dict[str, dict[str, Any]] = {}
        for label, source in (
            ("registry", registry_schema_path),
            ("manifest", manifest_schema_path),
        ):
            destination = staging / "schemas" / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            schema_bindings[label] = _artifact(destination, staging)
        crop_records: dict[str, dict[str, Any]] = {}
        for collection_key in COLLECTION_KEYS:
            source_record = registry["sources"][collection_key]
            source_path = repository_root / source_record["local_path"]
            atbd_path = repository_root / source_record["atbd"]["local_path"]
            for label, path, expected_bytes, expected_sha in (
                ("source", source_path, source_record["bytes"], source_record["sha256"]),
                (
                    "ATBD",
                    atbd_path,
                    source_record["atbd"]["bytes"],
                    source_record["atbd"]["sha256"],
                ),
            ):
                if (
                    not path.is_file()
                    or path.stat().st_size != int(expected_bytes)
                    or _sha256_file(path) != expected_sha
                ):
                    raise Phase2A5ContextError(
                        f"{collection_key} {label} bytes/checksum mismatch"
                    )
            source_access = _verify_access_evidence(
                source_path,
                {**source_record["access_evidence"], "origin_url": source_record["origin_url"]},
                source_record=True,
            )
            atbd_access = _verify_access_evidence(
                atbd_path,
                source_record["atbd"],
                source_record=False,
            )
            crop_config = registry["crop_policy"]["crops"][collection_key]
            temporary_crop = staging / "crop-staging" / f"{collection_key}.tif"
            with rasterio.Env(GDAL_PAM_ENABLED="NO"):
                with rasterio.open(source_path) as source:
                    _verify_source_header(
                        source, source_record["header"], collection_key=collection_key
                    )
                    window = _window_from_registry(source, registry, collection_key)
                    values, summary = _write_crop(
                        source, window, temporary_crop, crop_config
                    )
            _verify_expected_crop_summary(summary, crop_config, collection_key=collection_key)
            crop_temps[collection_key] = temporary_crop
            destination = crop_destinations[collection_key]
            crop_records[collection_key] = {
                "collection_key": collection_key,
                "crop_id": crop_config["crop_id"],
                "role": "primary_detailed_context" if collection_key == COL3_KEY else "secondary_reference_and_disagreement_signal",
                "source": {
                    "source_id": source_record["source_id"],
                    "path": source_record["local_path"],
                    "bytes": source_record["bytes"],
                    "sha256": source_record["sha256"],
                    "atbd_path": source_record["atbd"]["local_path"],
                    "atbd_bytes": source_record["atbd"]["bytes"],
                    "atbd_sha256": source_record["atbd"]["sha256"],
                    "origin_url": source_record["origin_url"],
                    "official_gee_asset": source_record["official_gee_asset"],
                    "collection_identity": source_record["collection_identity"],
                    "product_year": source_record["product_year"],
                    "access_evidence": source_access,
                    "atbd_origin_url": source_record["atbd"]["origin_url"],
                    "atbd_visible_identity": source_record["atbd"]["visible_identity"],
                    "atbd_pdf_metadata_title": source_record["atbd"]["pdf_metadata_title"],
                    "atbd_identity_conflict": source_record["atbd"]["identity_conflict"],
                    "atbd_access_evidence": atbd_access,
                    "source_header": source_record["header"],
                    "nodata_policy": source_record["nodata_policy"],
                    "national_inventory": source_record["national_inventory"],
                    "provenance_limitations": source_record["provenance_limitations"],
                },
                "output": {
                    "path": destination.relative_to(repository_root).as_posix(),
                    "bytes": temporary_crop.stat().st_size,
                    "sha256": _sha256_file(temporary_crop),
                    **summary,
                },
                "transformation": {
                    "policy_id": registry["crop_policy"]["policy_id"],
                    "accepted_extent_id": registry["monitoring_extent"]["extent_id"],
                    "accepted_extent_geometry_sha256": registry["monitoring_extent"]["geometry_sha256"],
                    "fractional_source_window": crop_config["fractional_source_window"],
                    "integer_source_window": crop_config["integer_source_window"],
                    "source_grid_preserved": True,
                    "reprojection": "none",
                    "resampling": "none",
                    "categorical_reconciliation": "nearest_only",
                    "software": _runtime_versions(),
                },
                "class_mapping": {
                    "mapping_version": registry["class_mappings"]["mapping_version"],
                    "mapping": registry["class_mappings"][collection_key],
                    "unknown_code_policy": registry["class_mappings"]["unknown_code_policy"],
                },
                "integrity": {
                    "source_checksum_verified_before_read": True,
                    "source_modified": False,
                    "source_redownloaded": False,
                    "categorical_values_resampled": False,
                },
            }
            del values
        identity = {
            "pipeline_version": PIPELINE_VERSION,
            "registry_sha256": _sha256_file(registry_path),
            "monitoring_extent": registry["monitoring_extent"],
            "crop_outputs": {
                key: {
                    "crop_id": record["crop_id"],
                    "sha256": record["output"]["sha256"],
                    "transform": record["output"]["transform"],
                    "histogram": record["output"]["class_histogram"],
                }
                for key, record in crop_records.items()
            },
        }
        context_id = "p2a5-mapbiomas-context-v1-" + _canonical_sha256(identity)
        manifest = {
            "$schema": MANIFEST_SCHEMA_URL,
            "schema_version": SCHEMA_VERSION,
            "artifact_type": ARTIFACT_TYPE,
            "context_id": context_id,
            "pipeline_version": PIPELINE_VERSION,
            "generated_at": generated_at,
            "generation_command": list(generation_command),
            "runtime_versions": _runtime_versions(),
            "generator_source_inventory": _generator_inventory(repository_root),
            "schema_bindings": schema_bindings,
            "candidate_registry": {
                "registry_id": registry["registry_id"],
                "path": registry_path.relative_to(repository_root).as_posix(),
                "bytes": registry_path.stat().st_size,
                "sha256": _sha256_file(registry_path),
                "embedded": _artifact(embedded_registry, staging),
            },
            "monitoring_extent": registry["monitoring_extent"],
            "crop_policy": registry["crop_policy"],
            "grid_reconciliation": registry["grid_reconciliation"],
            "licence_and_attribution": registry["licence_and_attribution"],
            "crops": crop_records,
            "decision_state": registry["decision_state"],
            "claims": {
                "local_private_only": True,
                "national_sources_unchanged": True,
                "raw_detection_modified": False,
                "method_selected_or_activated": False,
                "scientific_accuracy_claim": False,
                "mapbiomas_is_truth_or_omission_reference": False,
                "phase2a_exit_gate_closed": False,
            },
            "artifact_inventory_rule": "all_internal_files_except_manifest_and_CHECKSUMS",
            "artifact_inventory": [],
            "checksum_file": "CHECKSUMS.sha256",
        }
        manifest["artifact_inventory"] = _checksum_inventory(staging)
        _write_json(staging / "manifest.json", manifest)
        _write_checksums(staging)
        for collection_key, temporary_crop in crop_temps.items():
            destination = crop_destinations[collection_key]
            destination.parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(destination):
                raise Phase2A5ContextError(
                    f"regional crop appeared during build; refusing overwrite: {destination}"
                )
            _publish_file_no_clobber(temporary_crop, destination)
            moved_crops.append(destination)
        shutil.rmtree(staging / "crop-staging", ignore_errors=True)
        _publish_directory_no_clobber(staging, output_root)
        published_output = True
        return validate_phase2a5_context_artifact(
            output_root,
            registry_path=registry_path,
            repository_root=repository_root,
            verify_sources=True,
        )
    except Exception:
        for path in moved_crops:
            try:
                path.unlink()
            except OSError:
                pass
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        if published_output and output_root.exists():
            shutil.rmtree(output_root, ignore_errors=True)
        raise
    finally:
        _release_build_lock(lock_path)


def _verify_checksum_file(root: Path) -> None:
    checksum_path = root / "CHECKSUMS.sha256"
    if not checksum_path.is_file():
        raise Phase2A5ContextError("context CHECKSUMS.sha256 missing")
    expected_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "CHECKSUMS.sha256"
    }
    seen: set[str] = set()
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64 or relative in seen:
            raise Phase2A5ContextError("malformed context checksum inventory")
        path = _safe_artifact_path(root, relative)
        if not path.is_file() or _sha256_file(path) != digest:
            raise Phase2A5ContextError(f"context checksum mismatch: {relative}")
        seen.add(relative)
    if seen != expected_paths:
        raise Phase2A5ContextError("context checksum inventory population mismatch")


def _verify_embedded_context_schemas(
    root: Path, repository_root: Path
) -> tuple[Path, Path, Path, Path]:
    manifest_schema_path = root / "schemas/phase2a5-context-manifest-v1.schema.json"
    registry_schema_embedded_path = (
        root / "schemas/phase2a5-context-candidate-registry-v1.schema.json"
    )
    canonical_manifest_schema_path = (
        repository_root
        / "docs/contracts/phase2a/schemas/phase2a5-context-manifest-v1.schema.json"
    )
    canonical_registry_schema_path = (
        repository_root
        / "docs/contracts/phase2a/schemas/phase2a5-context-candidate-registry-v1.schema.json"
    )
    if any(
        not path.is_file()
        for path in (
            manifest_schema_path,
            registry_schema_embedded_path,
            canonical_manifest_schema_path,
            canonical_registry_schema_path,
        )
    ):
        raise Phase2A5ContextError("context schema binding is missing")
    if manifest_schema_path.read_bytes() != canonical_manifest_schema_path.read_bytes():
        raise Phase2A5ContextError(
            "embedded context manifest schema differs from the contract"
        )
    if (
        registry_schema_embedded_path.read_bytes()
        != canonical_registry_schema_path.read_bytes()
    ):
        raise Phase2A5ContextError(
            "embedded context registry schema differs from the contract"
        )
    return (
        manifest_schema_path,
        registry_schema_embedded_path,
        canonical_manifest_schema_path,
        canonical_registry_schema_path,
    )


def _verify_context_binding_descriptors(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    registry: Mapping[str, Any],
    registry_path: Path,
    repository_root: Path,
    manifest_schema_path: Path,
    registry_schema_embedded_path: Path,
) -> None:
    expected_schema_bindings = {
        "registry": _artifact(registry_schema_embedded_path, root),
        "manifest": _artifact(manifest_schema_path, root),
    }
    if manifest["schema_bindings"] != expected_schema_bindings:
        raise Phase2A5ContextError("context schema bindings do not reconcile")
    embedded = _safe_artifact_path(
        root, manifest["candidate_registry"]["embedded"]["path"]
    )
    if not embedded.is_file() or embedded.read_bytes() != registry_path.read_bytes():
        raise Phase2A5ContextError("embedded registry differs from fixed source")
    expected_candidate_registry = {
        "registry_id": registry["registry_id"],
        "path": registry_path.relative_to(repository_root).as_posix(),
        "bytes": registry_path.stat().st_size,
        "sha256": _sha256_file(registry_path),
        "embedded": _artifact(embedded, root),
    }
    if manifest["candidate_registry"] != expected_candidate_registry:
        raise Phase2A5ContextError("context registry binding does not reconcile")


def validate_phase2a5_context_artifact(
    context_root: Path,
    *,
    registry_path: Path,
    repository_root: Path,
    verify_sources: bool = True,
) -> dict[str, Any]:
    """Deeply validate source bindings, crop bytes, grids, and manifest identity."""
    root = Path(context_root).resolve()
    repository_root = Path(repository_root).resolve()
    registry_path = Path(registry_path).resolve()
    if not root.is_dir():
        raise Phase2A5ContextError(f"context artifact directory missing: {root}")
    manifest = _load_json(root / "manifest.json")
    registry_schema_path = (
        repository_root
        / "docs/contracts/phase2a/schemas/phase2a5-context-candidate-registry-v1.schema.json"
    )
    registry = load_context_registry(
        registry_path,
        schema_path=registry_schema_path,
    )
    (
        manifest_schema_path,
        registry_schema_embedded_path,
        canonical_manifest_schema_path,
        canonical_registry_schema_path,
    ) = _verify_embedded_context_schemas(root, repository_root)
    if canonical_registry_schema_path != registry_schema_path:
        raise Phase2A5ContextError("canonical context registry schema path changed")
    _validate_schema(
        manifest,
        _load_json(canonical_manifest_schema_path),
        label="context manifest",
    )
    _verify_checksum_file(root)
    _verify_context_binding_descriptors(
        root=root,
        manifest=manifest,
        registry=registry,
        registry_path=registry_path,
        repository_root=repository_root,
        manifest_schema_path=manifest_schema_path,
        registry_schema_embedded_path=registry_schema_embedded_path,
    )
    if manifest["monitoring_extent"] != registry["monitoring_extent"]:
        raise Phase2A5ContextError("context extent binding changed")
    if manifest["decision_state"] != registry["decision_state"]:
        raise Phase2A5ContextError("context decision state changed")
    if manifest["generator_source_inventory"] != _generator_inventory(repository_root):
        raise Phase2A5ContextError("context generator source inventory changed")
    expected_inventory = _checksum_inventory(root)
    # The embedded inventory excludes manifest/checksum exactly like the
    # generator.  Recompute records rather than trusting path names.
    if manifest["artifact_inventory"] != expected_inventory:
        raise Phase2A5ContextError("context internal artifact inventory changed")
    for collection_key in COLLECTION_KEYS:
        source_record = registry["sources"][collection_key]
        crop_config = registry["crop_policy"]["crops"][collection_key]
        crop_record = manifest["crops"][collection_key]
        crop_path = repository_root / crop_record["output"]["path"]
        if (
            not crop_path.is_file()
            or crop_path.stat().st_size != crop_record["output"]["bytes"]
            or _sha256_file(crop_path) != crop_record["output"]["sha256"]
        ):
            raise Phase2A5ContextError(f"{collection_key} crop checksum mismatch")
        with rasterio.Env(GDAL_PAM_ENABLED="NO"):
            with rasterio.open(crop_path) as crop:
                if crop.count != 1 or crop.dtypes[0] != "uint8":
                    raise Phase2A5ContextError(f"{collection_key} crop header changed")
                values = crop.read(1)
                summary = {
                    "width": crop.width,
                    "height": crop.height,
                    "crs": crop.crs.to_string(),
                    "transform": list(crop.transform)[:6],
                    "bounds": list(crop.bounds),
                    "dtype": crop.dtypes[0],
                    "nodata": crop.nodata,
                    "area_or_point": crop.tags().get("AREA_OR_POINT"),
                    "tiled": bool(crop.profile.get("tiled")),
                    "block_shape": list(crop.block_shapes[0]),
                    "compression": (
                        crop.compression.name.upper()
                        if crop.compression is not None
                        else None
                    ),
                    "predictor": crop.tags(ns="IMAGE_STRUCTURE").get("PREDICTOR"),
                    "overviews": list(crop.overviews(1)),
                    "class_histogram": _histogram(values),
                    **_coverage(values, int(crop_config["output_nodata"])),
                }
        _verify_expected_crop_summary(summary, crop_config, collection_key=collection_key)
        for field in (
            "width",
            "height",
            "crs",
            "transform",
            "bounds",
            "dtype",
            "nodata",
            "area_or_point",
            "tiled",
            "block_shape",
            "compression",
            "predictor",
            "overviews",
            "class_histogram",
            "total_pixel_count",
            "valid_pixel_count",
            "nodata_pixel_count",
            "valid_coverage_fraction",
        ):
            if not _numeric_equal(crop_record["output"][field], summary[field], tolerance=1e-10):
                raise Phase2A5ContextError(
                    f"{collection_key} crop manifest {field} changed"
                )
        if crop_record["source"]["sha256"] != source_record["sha256"]:
            raise Phase2A5ContextError(f"{collection_key} national source binding changed")
        expected_source_bindings = {
            "source_id": source_record["source_id"],
            "path": source_record["local_path"],
            "bytes": source_record["bytes"],
            "sha256": source_record["sha256"],
            "atbd_path": source_record["atbd"]["local_path"],
            "atbd_bytes": source_record["atbd"]["bytes"],
            "atbd_sha256": source_record["atbd"]["sha256"],
            "origin_url": source_record["origin_url"],
            "official_gee_asset": source_record["official_gee_asset"],
            "collection_identity": source_record["collection_identity"],
            "product_year": source_record["product_year"],
            "atbd_origin_url": source_record["atbd"]["origin_url"],
            "atbd_visible_identity": source_record["atbd"]["visible_identity"],
            "atbd_pdf_metadata_title": source_record["atbd"]["pdf_metadata_title"],
            "atbd_identity_conflict": source_record["atbd"]["identity_conflict"],
            "source_header": source_record["header"],
            "nodata_policy": source_record["nodata_policy"],
            "national_inventory": source_record["national_inventory"],
            "provenance_limitations": source_record["provenance_limitations"],
        }
        for field, expected in expected_source_bindings.items():
            if crop_record["source"].get(field) != expected:
                raise Phase2A5ContextError(
                    f"{collection_key} source provenance field {field} changed"
                )
        if verify_sources:
            source_path = repository_root / source_record["local_path"]
            atbd_path = repository_root / source_record["atbd"]["local_path"]
            for label, path, expected_bytes, expected_sha in (
                ("source", source_path, source_record["bytes"], source_record["sha256"]),
                (
                    "ATBD",
                    atbd_path,
                    source_record["atbd"]["bytes"],
                    source_record["atbd"]["sha256"],
                ),
            ):
                if (
                    not path.is_file()
                    or path.stat().st_size != int(expected_bytes)
                    or _sha256_file(path) != expected_sha
                ):
                    raise Phase2A5ContextError(
                        f"{collection_key} {label} integrity changed"
                    )
            source_access = _verify_access_evidence(
                source_path,
                {**source_record["access_evidence"], "origin_url": source_record["origin_url"]},
                source_record=True,
            )
            atbd_access = _verify_access_evidence(
                atbd_path,
                source_record["atbd"],
                source_record=False,
            )
            if crop_record["source"].get("access_evidence") != source_access:
                raise Phase2A5ContextError(
                    f"{collection_key} source access evidence changed"
                )
            if crop_record["source"].get("atbd_access_evidence") != atbd_access:
                raise Phase2A5ContextError(
                    f"{collection_key} ATBD access evidence changed"
                )
            with rasterio.Env(GDAL_PAM_ENABLED="NO"):
                with rasterio.open(source_path) as source:
                    _verify_source_header(
                        source, source_record["header"], collection_key=collection_key
                    )
                    window = _window_from_registry(source, registry, collection_key)
                    source_values = source.read(1, window=window)
            if not np.array_equal(source_values, values):
                raise Phase2A5ContextError(
                    f"{collection_key} crop pixels differ from native source window"
                )
    identity = {
        "pipeline_version": PIPELINE_VERSION,
        "registry_sha256": _sha256_file(registry_path),
        "monitoring_extent": registry["monitoring_extent"],
        "crop_outputs": {
            key: {
                "crop_id": manifest["crops"][key]["crop_id"],
                "sha256": manifest["crops"][key]["output"]["sha256"],
                "transform": manifest["crops"][key]["output"]["transform"],
                "histogram": manifest["crops"][key]["output"]["class_histogram"],
            }
            for key in COLLECTION_KEYS
        },
    }
    expected_id = "p2a5-mapbiomas-context-v1-" + _canonical_sha256(identity)
    if manifest["context_id"] != expected_id:
        raise Phase2A5ContextError("context identity does not bind exact crops and inputs")
    return dict(manifest)


__all__ = [
    "Phase2A5ContextError",
    "aggregate_contextual_signature_candidates",
    "annotate_threshold_candidates_preserving_raw",
    "build_phase2a5_context_artifact",
    "calculate_agreement_disagreement",
    "classify_contextual_signature_pixels",
    "classify_mapbiomas_codes",
    "contextual_signature_proportions",
    "load_context_registry",
    "strong_subset_membership",
    "summarize_polygon_context",
    "validate_phase2a5_context_artifact",
]
