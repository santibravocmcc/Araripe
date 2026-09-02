"""Authoritative baseline ``2.0.0`` manifest: build, audit, and validation.

Package 2A.6C rebuilds the 72-object baseline with the identical accepted
candidate science.  This module owns the new manifest's discipline, applying
the Package 2A.2 audit rules (checksums, exact inventory, grid, scale, range,
wider-extent coverage) plus the v2-generation bindings that the 2A.2 audit
found missing from the historical build: per-datatake scene IDs, per-scene
processing baselines, GEE project/task identity, query fingerprint, export
checksums, plan checksums, and statistics evidence.

Validation re-derives — never trusts — the identity-bearing fields: every
``acquisition_id`` is recomputed through the v3 acquisition contract (which
is also what keeps unreviewed platforms fail-closed) and every per-datatake
``gee_plan_sha256`` is recomputed from the entry's own scene counts.

Baseline ``1.0.0`` stays immutable: its manifest bytes are pinned by SHA-256,
its object keys and local directory are never reused, and this module refuses
to write a v2 manifest over the v1 path or any existing file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from config.settings import (
    BASELINE_MANIFEST_PATH,
    BASELINE_MAX_CLOUD_COVER,
    BASELINE_SCL_CLEAR_CLASSES,
    BASELINE_SOURCE_YEARS,
    DATA_DIR,
    GEE_COLLECTION_ID,
    ROOT_DIR,
)
from src.detection.baseline_manifest import (
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_BOUNDS_SHA256,
    MONITORING_EXTENT_GEOMETRY_SHA256,
    MONITORING_EXTENT_ID,
    _range_limits as _v1_range_limits,
    audit_baseline_directory,
    expected_filenames,
    inventory_sha256,
    load_manifest as load_manifest_v1,
    parse_baseline_filename,
)
from src.detection.identity import canonical_sha256
from src.detection.identity_v3 import (
    create_acquisition_v3,
    normalize_utc_timestamp,
)
from src.processing.baseline_rebuild_v2 import (
    AMENDMENT_V3_PATH,
    AMENDMENT_V3_SHA256,
    BASELINE_REBUILD_PLAN_VERSION,
    BASELINE_V1_INVENTORY_SHA256,
    BASELINE_V1_MANIFEST_SHA256,
    BASELINE_V1_VERSION,
    BASELINE_V2_GRID_CONTRACT,
    BASELINE_V2_GRID_ID,
    BASELINE_V2_VERSION,
    COMPOSITE_STACK_ORDER_POLICY,
    DECISIONS_V2_PATH,
    DECISIONS_V2_SHA256,
    MONTHLY_CENTRAL_STATISTIC,
    MONTHLY_DISPERSION_STATISTIC,
    NONFINITE_INDEX_POLICY,
    PLATFORM_POLICY,
    REBUILD_BAND_NAMES,
    REBUILD_COUNT_SOURCES,
    REBUILD_INDEX_FORMULAS,
    REBUILD_INDEX_NAMES,
    REFLECTANCE_SCALE_DIVISOR,
    STATISTICS_COMPUTATION_DTYPE,
    STATISTICS_OUTPUT_DTYPE,
    RebuildDatatakeCompositionV2,
    build_rebuild_gee_plan,
)
from src.processing.composition_v2 import (
    COMPOSITION_METHOD_ID,
    COMPOSITION_SCOPE_VERSION,
    PIXEL_SELECTION_POLICY,
    SCENE_ORDER_POLICY,
)
from src.processing.scl_mask_v2 import (
    CLOUD_SHADOW_DILATION_M,
    DARK_NIR_PROXIMITY_MASK,
    REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
    REVIEWED_PROCESSING_BASELINES,
    SCL_ACCEPTED_CLASSES,
    SCL_MASK_METHOD_ID,
    SCL_REJECTED_CLASSES,
)


BASELINE_V2_SCHEMA_VERSION = "2.0.0"
BASELINE_ID = "araripe-s2-sr-harmonized-monthly"
BASELINE_V2_STATUS = "rebuilt_candidate_generation"
# Completely disjoint from the immutable v1 prefix ``baselines/`` so no v1
# listing, fetch, or object key can ever collide with a v2 object.
BASELINE_V2_KEY_PREFIX = "baselines_v2/2.0.0/"
BASELINE_V1_KEY_PREFIX = "baselines/"
BASELINE_V2_LOCAL_DIR = DATA_DIR / "baselines_v2" / "2.0.0"
BASELINE_V2_MANIFEST_PATH = ROOT_DIR / "config" / "baseline_manifest_v2.json"

EXPECTED_OBJECT_COUNT = 72
MIN_EXTENT_COVERAGE = 0.99

RASTER_CONTRACT_V2: Mapping[str, Any] = MappingProxyType(
    {
        **{key: value for key, value in BASELINE_V2_GRID_CONTRACT.items()},
        "expected_object_count": EXPECTED_OBJECT_COUNT,
        "indices": list(REBUILD_INDEX_NAMES),
        "months": list(range(1, 13)),
        "filename_statistics": {
            "mean": "multi-year monthly median",
            "std": "multi-year monthly population standard deviation",
        },
        "minimum_extent_coverage_fraction": MIN_EXTENT_COVERAGE,
    }
)

REQUIRED_PROVENANCE_RETAINED = (
    "provider-native scene IDs per datatake",
    "source processing-baseline versions per scene",
    "per-scene valid-pixel counts",
    "GEE project and task IDs",
    "GEE query fingerprint",
    "12 month-export checksums",
    "per-datatake GEE plan checksums",
    "monthly statistics evidence checksums",
)

_SHA256_HEX = frozenset("0123456789abcdef")


class BaselineManifestV2Error(ValueError):
    """Raised when a v2 manifest or raster set violates the 2A.6C contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BaselineManifestV2Error(message)


def _require_sha256(value: Any, *, label: str) -> str:
    _require(
        isinstance(value, str)
        and len(value) == 64
        and set(value) <= _SHA256_HEX,
        f"{label} must be a lowercase SHA-256 hex digest",
    )
    return value


def sha256_bytes_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_baseline_v1_untouched(
    manifest_path: Path = BASELINE_MANIFEST_PATH,
) -> str:
    """Prove the accepted baseline ``1.0.0`` manifest is byte-identical.

    Returns the verified checksum.  The v1 manifest must both hash to the
    pinned value and still pass its own authoritative validation, so neither
    the bytes nor the recorded audit decision can drift under a rebuild.
    """

    actual = sha256_bytes_of_file(manifest_path)
    _require(
        actual == BASELINE_V1_MANIFEST_SHA256,
        "baseline 1.0.0 manifest bytes changed; the accepted generation is "
        "immutable and must never be edited by a rebuild",
    )
    manifest = load_manifest_v1(Path(manifest_path))
    _require(
        manifest["aggregate"]["inventory_sha256"]
        == BASELINE_V1_INVENTORY_SHA256,
        "baseline 1.0.0 inventory checksum drifted from the accepted audit",
    )
    return actual


# ─── Raster audit of a rebuilt directory ─────────────────────────────────────


def _grid_fields(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "crs": contract["crs"],
        "width": contract["width"],
        "height": contract["height"],
        "transform": list(contract["transform"]),
        "bounds": list(contract["bounds"]),
        "pixel_size": list(contract["pixel_size"]),
        "dtype": contract["dtype"],
        "band_count": contract["band_count"],
        "nodata": contract["nodata"],
    }


def audit_rebuilt_baseline_directory(
    baselines_dir: Path,
    *,
    raster_contract: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fully read a rebuilt 72-raster directory and return v2 object evidence.

    Consumes the Package 2A.2 audit implementation for the byte-level reads
    and then enforces the pinned v2 grid contract absolutely (not merely
    first-file consistency).  Object keys are the disjoint v2 keys; no v1
    object metadata is produced or touched.
    """

    contract = raster_contract or RASTER_CONTRACT_V2
    expected_grid = _grid_fields(contract)
    audited = audit_baseline_directory(Path(baselines_dir))
    objects: list[dict[str, Any]] = []
    for entry in audited:
        record = dict(entry)
        filename = record["filename"]
        record["key"] = BASELINE_V2_KEY_PREFIX + filename
        # v2 names the dispersion statistic exactly (population form), where
        # the historical v1 label was the bare "standard_deviation".
        if record["filename_statistic"] == "std":
            record["statistic"] = MONTHLY_DISPERSION_STATISTIC
        # Without a remote inventory the v1 auditor records the local MD5 in
        # the ETag slot; v2 objects are local until a later reviewed
        # publication, so keep it under its honest name.
        record["md5"] = record.pop("r2_etag")
        for legacy_field in (
            "r2_last_modified",
            "r2_storage_class",
            "r2_content_type",
        ):
            record.pop(legacy_field, None)
        actual_grid = {
            "crs": record["crs"],
            "width": record["width"],
            "height": record["height"],
            "transform": list(record["transform"]),
            "bounds": list(record["bounds"]),
            "pixel_size": list(record["pixel_size"]),
            "dtype": record["dtype"],
            "band_count": record["band_count"],
            "nodata": record["nodata"],
        }
        _require(
            actual_grid == expected_grid,
            f"{filename} grid violates the pinned baseline 2.0.0 contract",
        )
        _require(
            record["grid_matches_reference"] is True,
            f"{filename} drifts from the directory reference grid",
        )
        objects.append(record)
    return objects


# ─── Manifest entry helpers ──────────────────────────────────────────────────


def manifest_datatake_entry_from_composition(
    record: RebuildDatatakeCompositionV2,
) -> dict[str, Any]:
    """Turn one locally verified rebuild composition into a manifest entry.

    The local path carries the strongest evidence: the byte-identical
    local/GEE parity proof.  A production-scale entry uses the same shape
    with ``valid_pixel_count_source: gee_reduce_region`` and the GEE-side
    reconciliation evidence instead.
    """

    composite = record.composite
    return {
        "acquisition_id": record.acquisition.acquisition_id,
        "platform": record.acquisition.platform,
        "datatake_id": record.acquisition.datatake_id,
        "acquisition_timestamp_utc": (
            record.acquisition.acquisition_timestamp_utc
        ),
        "year": record.datatake.year,
        "scene_count": len(record.acquisition.scene_ids),
        "scenes": [
            {
                "scene_id": mask.scene_id,
                "processing_baseline": (
                    mask.processing_baseline.normalized_value
                ),
            }
            for mask in sorted(
                composite.scene_masks,
                key=lambda mask: str(mask.scene_id).encode("utf-8"),
            )
        ],
        "valid_pixel_counts": {
            scene_id: composite.scene_valid_pixel_counts[scene_id]
            for scene_id in sorted(
                composite.scene_valid_pixel_counts,
                key=lambda item: item.encode("utf-8"),
            )
        },
        "valid_pixel_count_source": "local_reference_composite",
        "gee_plan_sha256": record.gee_plan["gee_plan_sha256"],
        "gee_verification": {
            "counts_reconciled": True,
            "contributor_accounting_reconciled": True,
            "evidence_sha256": record.parity_evidence[
                "parity_evidence_sha256"
            ],
            "kind": "local_byte_identical_parity",
        },
    }


def _validate_registry_block(registry: Mapping[str, Any]) -> tuple[str, ...]:
    _require(
        isinstance(registry, Mapping),
        "reviewed_processing_baseline_registry must be a mapping",
    )
    _require(
        registry.get("registry_id") == REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
        "registry_id must be " + REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
    )
    _require(
        registry.get("base_reviewed_values")
        == list(REVIEWED_PROCESSING_BASELINES),
        "registry base values must equal the closed 2A.6B enumeration",
    )
    added = registry.get("added_reviewed_values")
    _require(isinstance(added, list), "added_reviewed_values must be a list")
    _require(
        registry.get("unreviewed_value_policy") == "unavailable_fail_closed",
        "registry must keep the fail-closed unreviewed-value policy",
    )
    _require(
        registry.get("extension_policy")
        == "recorded_review_only_never_fallback",
        "registry must declare the recorded-review-only extension policy",
    )
    effective = sorted({*REVIEWED_PROCESSING_BASELINES, *added})
    _require(
        registry.get("reviewed_values") == effective,
        "registry reviewed_values must be the sorted base plus added values",
    )
    if added:
        extension = registry.get("recorded_review_extension")
        _require(
            isinstance(extension, Mapping),
            "added reviewed values require a recorded_review_extension",
        )
        for field in ("extension_id", "reviewed_by", "review_date", "review_scope"):
            value = extension.get(field)
            _require(
                isinstance(value, str) and bool(value.strip()),
                f"recorded_review_extension needs a non-empty {field}",
            )
        entries = extension.get("added_values")
        _require(
            isinstance(entries, list)
            and [entry.get("value") for entry in entries] == added,
            "recorded_review_extension must enumerate exactly the added "
            "values in order",
        )
        for entry in entries:
            for field in ("review_basis", "observed_in"):
                text = entry.get(field)
                _require(
                    isinstance(text, str) and bool(text.strip()),
                    f"added value {entry.get('value')} needs a non-empty "
                    f"{field}",
                )
    else:
        _require(
            "recorded_review_extension" not in registry,
            "an extension record without added values is not a review",
        )
    return tuple(effective)


def _expected_mask_identity() -> dict[str, Any]:
    return {
        "scl_mask_method_id": SCL_MASK_METHOD_ID,
        "accepted_scl_classes": list(SCL_ACCEPTED_CLASSES),
        "rejected_scl_classes": list(SCL_REJECTED_CLASSES),
        "dark_nir_proximity_mask": DARK_NIR_PROXIMITY_MASK,
        "cloud_shadow_dilation_m": CLOUD_SHADOW_DILATION_M,
        "unreviewed_scl_or_baseline_policy": "unavailable_fail_closed",
        "identical_to_candidate_generation": True,
        "superseded_v1_scl_clear_classes": list(BASELINE_SCL_CLEAR_CLASSES),
    }


def _expected_composition_block() -> dict[str, Any]:
    return {
        "composite_method_id": COMPOSITION_METHOD_ID,
        "composition_scope_version": COMPOSITION_SCOPE_VERSION,
        "scene_order_policy": list(SCENE_ORDER_POLICY),
        "pixel_selection": PIXEL_SELECTION_POLICY,
        "different_datatakes_never_composed": True,
    }


def _expected_statistics_block() -> dict[str, Any]:
    return {
        "central": MONTHLY_CENTRAL_STATISTIC,
        "dispersion": MONTHLY_DISPERSION_STATISTIC,
        "computation_dtype": STATISTICS_COMPUTATION_DTYPE,
        "output_dtype": STATISTICS_OUTPUT_DTYPE,
        "composite_stack_order_policy": list(COMPOSITE_STACK_ORDER_POLICY),
        "nonfinite_index_policy": NONFINITE_INDEX_POLICY,
        "unit_of_contribution": "one_datatake_composite",
    }


def _validate_datatake_entry(
    entry: Mapping[str, Any],
    *,
    month: int,
    run_manifest_id: str,
    run_manifest_sha256: str,
    image_collection_id: str,
    effective_registry: tuple[str, ...],
    grid_id: str,
) -> dict[str, Any]:
    label = f"month {month:02d} datatake {entry.get('datatake_id')!r}"
    platform = entry.get("platform")
    _require(
        platform in PLATFORM_POLICY["allowed_platforms"],
        f"{label}: platform {platform!r} is outside the v3-representable set",
    )
    year = entry.get("year")
    _require(
        year in BASELINE_SOURCE_YEARS,
        f"{label}: year {year!r} is not an accepted baseline source year",
    )
    _require(
        isinstance(entry.get("acquisition_timestamp_utc"), str),
        f"{label}: acquisition_timestamp_utc must be a string",
    )
    timestamp = normalize_utc_timestamp(
        entry.get("acquisition_timestamp_utc"),
        label=f"{label} acquisition_timestamp_utc",
    )
    _require(
        timestamp == entry.get("acquisition_timestamp_utc"),
        f"{label}: acquisition timestamp must be byte-canonical",
    )
    instant = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    _require(
        instant.year == year and instant.month == month,
        f"{label}: timestamp is outside its declared baseline slot",
    )
    scenes = entry.get("scenes")
    _require(
        isinstance(scenes, list) and bool(scenes),
        f"{label}: needs at least one provider-native scene",
    )
    scene_ids: list[str] = []
    baselines: set[str] = set()
    for scene in scenes:
        scene_id = scene.get("scene_id")
        _require(
            isinstance(scene_id, str) and bool(scene_id),
            f"{label}: scene entries need non-empty scene IDs",
        )
        _require(
            scene_id not in scene_ids,
            f"{label}: duplicate scene {scene_id}",
        )
        baseline = scene.get("processing_baseline")
        _require(
            baseline in effective_registry,
            f"{label}: scene {scene_id} carries processing baseline "
            f"{baseline!r} outside the effective reviewed registry",
        )
        scene_ids.append(scene_id)
        baselines.add(baseline)
    _require(
        entry.get("scene_count") == len(scene_ids),
        f"{label}: scene_count disagrees with the scene list",
    )
    counts = entry.get("valid_pixel_counts")
    _require(
        isinstance(counts, Mapping)
        and sorted(counts) == sorted(scene_ids),
        f"{label}: valid_pixel_counts must cover exactly the scene set",
    )
    count_source = entry.get("valid_pixel_count_source")
    _require(
        count_source in REBUILD_COUNT_SOURCES,
        f"{label}: valid_pixel_count_source must be one of "
        f"{REBUILD_COUNT_SOURCES}",
    )

    # Re-derive the identity-bearing fields instead of trusting them.  The
    # acquisition contract also keeps unreviewed platforms fail-closed here.
    try:
        acquisition = create_acquisition_v3(
            run_manifest_id=run_manifest_id,
            run_manifest_sha256=run_manifest_sha256,
            collection_id=image_collection_id,
            platform=platform,
            datatake_id=entry.get("datatake_id"),
            acquisition_timestamp_utc=timestamp,
            scene_ids=scene_ids,
            monitoring_extent_id=MONITORING_EXTENT_ID,
            composite_method_id=COMPOSITION_METHOD_ID,
            grid_id=grid_id,
        )
    except ValueError as exc:
        raise BaselineManifestV2Error(
            f"{label}: acquisition identity is invalid under the v3 "
            f"contract: {exc}"
        ) from exc
    _require(
        entry.get("acquisition_id") == acquisition.acquisition_id,
        f"{label}: acquisition_id does not rederive from its v3 inputs",
    )
    plan = build_rebuild_gee_plan(
        image_collection_id=image_collection_id,
        platform=platform,
        datatake_id=entry["datatake_id"],
        band_names=REBUILD_BAND_NAMES,
        valid_pixel_counts=dict(counts),
        observed_processing_baselines=sorted(baselines),
        count_source=count_source,
    )
    _require(
        entry.get("gee_plan_sha256") == plan["gee_plan_sha256"],
        f"{label}: gee_plan_sha256 does not rederive from the entry's own "
        "scene counts",
    )
    verification = entry.get("gee_verification")
    _require(
        isinstance(verification, Mapping)
        and verification.get("counts_reconciled") is True
        and verification.get("contributor_accounting_reconciled") is True,
        f"{label}: GEE verification must reconcile counts and contributor "
        "accounting",
    )
    _require_sha256(
        verification.get("evidence_sha256"),
        label=f"{label} gee_verification.evidence_sha256",
    )
    return {
        "platform": platform,
        "datatake_id": entry["datatake_id"],
        "acquisition_id": acquisition.acquisition_id,
        "baselines": baselines,
        "scene_count": len(scene_ids),
    }


# ─── Full manifest validation ────────────────────────────────────────────────


def validate_manifest_v2(
    manifest: Mapping[str, Any],
    *,
    raster_contract: Mapping[str, Any] | None = None,
) -> None:
    """Validate a complete baseline 2.0.0 manifest, failing closed."""

    contract = raster_contract or RASTER_CONTRACT_V2

    _require(
        manifest.get("schema_version") == BASELINE_V2_SCHEMA_VERSION,
        f"schema_version must be {BASELINE_V2_SCHEMA_VERSION}",
    )
    _require(manifest.get("baseline_id") == BASELINE_ID, "unexpected baseline_id")
    _require(
        manifest.get("baseline_version") == BASELINE_V2_VERSION,
        f"baseline_version must be {BASELINE_V2_VERSION}",
    )
    _require(
        manifest.get("status") == BASELINE_V2_STATUS,
        f"status must be {BASELINE_V2_STATUS}",
    )
    _require(
        isinstance(manifest.get("build_date"), str)
        and bool(manifest["build_date"]),
        "build_date is required",
    )

    predecessor = manifest.get("predecessor", {})
    _require(
        predecessor.get("baseline_version") == BASELINE_V1_VERSION
        and predecessor.get("manifest_path")
        == "config/baseline_manifest_v1.json"
        and predecessor.get("manifest_sha256") == BASELINE_V1_MANIFEST_SHA256
        and predecessor.get("inventory_sha256")
        == BASELINE_V1_INVENTORY_SHA256
        and predecessor.get("immutable") is True
        and predecessor.get("deleted_or_overwritten") is False,
        "predecessor block must pin the immutable baseline 1.0.0 identity",
    )

    bindings = manifest.get("decision_bindings", {})
    _require(
        bindings.get("candidate_generation_decisions_v2", {})
        == {"path": DECISIONS_V2_PATH, "sha256": DECISIONS_V2_SHA256},
        "manifest must bind the accepted candidate-generation decision "
        "record by checksum",
    )
    _require(
        bindings.get("sentinel2c_contract_amendment_v3", {})
        == {"path": AMENDMENT_V3_PATH, "sha256": AMENDMENT_V3_SHA256},
        "manifest must bind the Sentinel-2C v3 amendment by checksum",
    )

    _require(
        manifest.get("mask_baseline_identity") == _expected_mask_identity(),
        "mask_baseline_identity must equal the runtime "
        "scl-explicit-allowlist-v2 policy exactly",
    )
    _require(
        manifest.get("composition") == _expected_composition_block(),
        "composition block must equal the runtime "
        "coverage-ranked-first-valid-v1 policy exactly",
    )
    _require(
        manifest.get("statistics") == _expected_statistics_block(),
        "statistics block must equal the fixed rebuild statistics policy",
    )

    extent = manifest.get("monitoring_extent", {})
    _require(
        extent.get("extent_id") == MONITORING_EXTENT_ID
        and tuple(extent.get("bounds", ())) == MONITORING_EXTENT_BOUNDS
        and extent.get("geometry_sha256") == MONITORING_EXTENT_GEOMETRY_SHA256
        and extent.get("bounds_sha256") == MONITORING_EXTENT_BOUNDS_SHA256,
        "monitoring extent must be the accepted wider extent, unchanged",
    )

    source = manifest.get("source", {})
    _require(
        source.get("collection_id") == GEE_COLLECTION_ID,
        "unexpected source collection",
    )
    _require(
        source.get("years") == list(BASELINE_SOURCE_YEARS),
        "baseline source-year set mismatch",
    )
    _require(
        source.get("scene_cloud_filter_percent") == BASELINE_MAX_CLOUD_COVER,
        "scene metadata cloud filter mismatch",
    )
    _require(
        source.get("reflectance_scale_divisor") == REFLECTANCE_SCALE_DIVISOR,
        "reflectance scale divisor mismatch",
    )
    _require(
        source.get("band_names") == list(REBUILD_BAND_NAMES),
        "source band set mismatch",
    )
    _require(
        source.get("indices") == dict(REBUILD_INDEX_FORMULAS),
        "index formula mismatch",
    )
    _require(
        source.get("platform_policy") == dict(PLATFORM_POLICY),
        "platform policy must be the v3 fail-closed policy",
    )
    provenance = source.get("provenance_completeness", {})
    _require(
        provenance.get("status") == "complete",
        "provenance_completeness.status must be complete for a v2 rebuild",
    )
    retained = provenance.get("retained")
    _require(
        isinstance(retained, list)
        and set(REQUIRED_PROVENANCE_RETAINED) <= set(retained),
        "provenance_completeness.retained must include every execution-time "
        "provenance item the 2A.2 audit found missing",
    )
    _require(
        provenance.get("missing") == [],
        "a v2 rebuild may not declare missing provenance",
    )

    effective_registry = _validate_registry_block(
        manifest.get("reviewed_processing_baseline_registry", {})
    )

    execution = manifest.get("rebuild_execution", {})
    plan_sha256 = _require_sha256(
        execution.get("rebuild_plan_sha256"), label="rebuild_plan_sha256"
    )
    _require(
        execution.get("rebuild_plan_version") == BASELINE_REBUILD_PLAN_VERSION,
        "rebuild_plan_version mismatch",
    )
    run_manifest_id = execution.get("run_manifest_id")
    run_manifest_sha256 = execution.get("run_manifest_sha256")
    _require(
        run_manifest_id == "run-v3-" + plan_sha256
        and run_manifest_sha256 == plan_sha256,
        "the v3 run-manifest binding must be derived from the rebuild plan "
        "checksum",
    )
    earth_engine = execution.get("earth_engine", {})
    _require(
        isinstance(earth_engine.get("project_id"), str)
        and bool(earth_engine["project_id"].strip()),
        "earth_engine.project_id is required execution provenance",
    )
    _require(
        earth_engine.get("image_collection_id") == GEE_COLLECTION_ID,
        "earth_engine.image_collection_id mismatch",
    )
    _require_sha256(
        earth_engine.get("query_fingerprint_sha256"),
        label="earth_engine.query_fingerprint_sha256",
    )

    months = execution.get("months")
    _require(
        isinstance(months, list)
        and [entry.get("month") for entry in months] == list(range(1, 13)),
        "rebuild_execution.months must enumerate months 1..12 exactly once, "
        "in order",
    )
    observed_baselines: set[str] = set()
    observed_platforms: set[str] = set()
    physical_keys: set[tuple[str, str]] = set()
    acquisition_ids: set[str] = set()
    export_names: dict[int, str] = {}
    total_datatakes = 0
    total_scenes = 0
    for month_entry in months:
        month = month_entry["month"]
        task_id = month_entry.get("gee_task_id")
        _require(
            isinstance(task_id, str) and bool(task_id.strip()),
            f"month {month:02d}: gee_task_id is required",
        )
        export_file = month_entry.get("export_file", {})
        _require(
            isinstance(export_file.get("name"), str)
            and bool(export_file["name"])
            and isinstance(export_file.get("bytes"), int)
            and export_file["bytes"] > 0,
            f"month {month:02d}: export_file needs a name and byte size",
        )
        _require_sha256(
            export_file.get("sha256"),
            label=f"month {month:02d} export_file.sha256",
        )
        export_names[month] = export_file["name"]
        _require_sha256(
            month_entry.get("month_evidence_sha256"),
            label=f"month {month:02d} month_evidence_sha256",
        )
        datatakes = month_entry.get("datatakes")
        _require(
            isinstance(datatakes, list) and bool(datatakes),
            f"month {month:02d}: a rebuilt month needs at least one "
            "datatake composite",
        )
        for entry in datatakes:
            summary = _validate_datatake_entry(
                entry,
                month=month,
                run_manifest_id=run_manifest_id,
                run_manifest_sha256=run_manifest_sha256,
                image_collection_id=earth_engine["image_collection_id"],
                effective_registry=effective_registry,
                grid_id=contract.get("grid_id", BASELINE_V2_GRID_ID),
            )
            physical = (summary["platform"], summary["datatake_id"])
            _require(
                physical not in physical_keys,
                f"physical datatake {physical} appears in more than one "
                "manifest slot",
            )
            physical_keys.add(physical)
            _require(
                summary["acquisition_id"] not in acquisition_ids,
                f"duplicate acquisition {summary['acquisition_id']}",
            )
            acquisition_ids.add(summary["acquisition_id"])
            observed_baselines.update(summary["baselines"])
            observed_platforms.add(summary["platform"])
            total_datatakes += 1
            total_scenes += summary["scene_count"]

    _require(
        manifest.get("observed_processing_baselines")
        == sorted(observed_baselines),
        "observed_processing_baselines must enumerate exactly the union of "
        "per-scene values",
    )
    _require(
        manifest.get("observed_platforms") == sorted(observed_platforms),
        "observed_platforms must enumerate exactly the union of datatake "
        "platforms",
    )
    totals = execution.get("totals", {})
    _require(
        totals.get("datatake_count") == total_datatakes
        and totals.get("scene_count") == total_scenes,
        "rebuild_execution.totals must reconcile with the month entries",
    )

    _require(
        manifest.get("raster_contract") == dict(contract),
        "raster_contract must equal the pinned baseline 2.0.0 contract",
    )

    objects = manifest.get("objects")
    _require(isinstance(objects, list), "objects must be a list")
    _require(
        len(objects) == EXPECTED_OBJECT_COUNT,
        f"manifest must contain {EXPECTED_OBJECT_COUNT} objects",
    )
    filenames = [obj.get("filename") for obj in objects]
    _require(
        sorted(filenames) == sorted(expected_filenames()),
        "manifest does not contain the exact canonical 72-file inventory",
    )
    expected_grid = _grid_fields(contract)
    keys: set[str] = set()
    for obj in objects:
        parsed = parse_baseline_filename(obj["filename"])
        expected_key = BASELINE_V2_KEY_PREFIX + obj["filename"]
        _require(obj.get("key") == expected_key, f"{obj['filename']} key mismatch")
        _require(
            not str(obj.get("key", "")).startswith(BASELINE_V1_KEY_PREFIX),
            f"{obj['filename']} would collide with the immutable v1 prefix",
        )
        _require(obj["key"] not in keys, f"duplicate object key {obj['key']}")
        keys.add(obj["key"])
        for field in ("index", "month", "filename_statistic"):
            _require(
                obj.get(field) == parsed[field],
                f"{obj['key']} {field} mismatch",
            )
        _require(
            obj.get("statistic")
            == (
                MONTHLY_CENTRAL_STATISTIC
                if parsed["filename_statistic"] == "mean"
                else MONTHLY_DISPERSION_STATISTIC
            ),
            f"{obj['key']} statistic label mismatch",
        )
        _require(
            isinstance(obj.get("bytes"), int) and obj["bytes"] > 0,
            f"{obj['key']} invalid byte size",
        )
        _require_sha256(obj.get("sha256"), label=f"{obj['key']} sha256")
        actual_grid = {
            "crs": obj.get("crs"),
            "width": obj.get("width"),
            "height": obj.get("height"),
            "transform": list(obj.get("transform", [])),
            "bounds": list(obj.get("bounds", [])),
            "pixel_size": list(obj.get("pixel_size", [])),
            "dtype": obj.get("dtype"),
            "band_count": obj.get("band_count"),
            "nodata": obj.get("nodata"),
        }
        _require(
            actual_grid == expected_grid,
            f"{obj['key']} grid violates the pinned contract",
        )
        _require(
            obj.get("grid_matches_reference") is True,
            f"{obj['key']} grid drift",
        )
        lower, upper = _v1_range_limits(
            parsed["index"], parsed["filename_statistic"]
        )
        _require(
            obj.get("accepted_range") == [lower, upper],
            f"{obj['key']} accepted range mismatch",
        )
        _require(
            obj.get("range_violation_pixels") == 0,
            f"{obj['key']} contains out-of-range pixels",
        )
        _require(
            obj.get("extent_coverage_fraction", 0)
            >= contract["minimum_extent_coverage_fraction"],
            f"{obj['key']} has insufficient monitoring-extent coverage",
        )
        if parsed["filename_statistic"] == "std":
            _require(
                obj.get("minimum", -1) >= 0, f"{obj['key']} has negative std"
            )
        _require(
            obj.get("derived_from_month_export")
            == export_names[parsed["month"]],
            f"{obj['key']} is not bound to its month's export file",
        )

    aggregate = manifest.get("aggregate", {})
    _require(
        aggregate.get("object_count") == len(objects),
        "aggregate object count mismatch",
    )
    _require(
        aggregate.get("total_bytes") == sum(obj["bytes"] for obj in objects),
        "aggregate byte count mismatch",
    )
    _require(
        aggregate.get("inventory_sha256") == inventory_sha256(objects),
        "aggregate inventory checksum mismatch",
    )
    _require(
        aggregate.get("minimum_extent_coverage_fraction")
        == min(obj["extent_coverage_fraction"] for obj in objects),
        "aggregate minimum extent coverage mismatch",
    )
    _require(
        aggregate.get("maximum_extent_coverage_fraction")
        == max(obj["extent_coverage_fraction"] for obj in objects),
        "aggregate maximum extent coverage mismatch",
    )
    _require(
        aggregate.get("range_violation_pixels") == 0,
        "aggregate range violations must be zero",
    )


# ─── Manifest assembly and immutable write ───────────────────────────────────


def build_manifest_v2(
    objects: Iterable[Mapping[str, Any]],
    execution: Mapping[str, Any],
    *,
    registry_block: Mapping[str, Any],
    build_date: str,
    raster_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble and fully validate the baseline 2.0.0 manifest."""

    contract = raster_contract or RASTER_CONTRACT_V2
    object_list = [dict(obj) for obj in objects]
    execution_block = json.loads(json.dumps(execution))
    months = execution_block.get("months", [])
    export_names = {
        entry.get("month"): entry.get("export_file", {}).get("name")
        for entry in months
    }
    for obj in object_list:
        obj["derived_from_month_export"] = export_names.get(obj.get("month"))
    observed_baselines = sorted(
        {
            scene.get("processing_baseline")
            for month_entry in months
            for datatake in month_entry.get("datatakes", [])
            for scene in datatake.get("scenes", [])
        }
    )
    observed_platforms = sorted(
        {
            datatake.get("platform")
            for month_entry in months
            for datatake in month_entry.get("datatakes", [])
        }
    )
    manifest: dict[str, Any] = {
        "schema_version": BASELINE_V2_SCHEMA_VERSION,
        "baseline_id": BASELINE_ID,
        "baseline_version": BASELINE_V2_VERSION,
        "status": BASELINE_V2_STATUS,
        "build_date": build_date,
        "predecessor": {
            "baseline_version": BASELINE_V1_VERSION,
            "manifest_path": "config/baseline_manifest_v1.json",
            "manifest_sha256": BASELINE_V1_MANIFEST_SHA256,
            "inventory_sha256": BASELINE_V1_INVENTORY_SHA256,
            "immutable": True,
            "deleted_or_overwritten": False,
        },
        "decision_bindings": {
            "candidate_generation_decisions_v2": {
                "path": DECISIONS_V2_PATH,
                "sha256": DECISIONS_V2_SHA256,
            },
            "sentinel2c_contract_amendment_v3": {
                "path": AMENDMENT_V3_PATH,
                "sha256": AMENDMENT_V3_SHA256,
            },
        },
        "mask_baseline_identity": _expected_mask_identity(),
        "composition": _expected_composition_block(),
        "statistics": _expected_statistics_block(),
        "monitoring_extent": {
            "extent_id": MONITORING_EXTENT_ID,
            "scope": "APA and surroundings",
            "crs": "EPSG:4326",
            "bounds": list(MONITORING_EXTENT_BOUNDS),
            "geometry_sha256": MONITORING_EXTENT_GEOMETRY_SHA256,
            "bounds_sha256": MONITORING_EXTENT_BOUNDS_SHA256,
        },
        "source": {
            "provider": "Google Earth Engine / Copernicus Sentinel-2",
            "collection_id": GEE_COLLECTION_ID,
            "years": list(BASELINE_SOURCE_YEARS),
            "scene_cloud_filter_percent": BASELINE_MAX_CLOUD_COVER,
            "reflectance_scale_divisor": REFLECTANCE_SCALE_DIVISOR,
            "band_names": list(REBUILD_BAND_NAMES),
            "indices": dict(REBUILD_INDEX_FORMULAS),
            "platform_policy": dict(PLATFORM_POLICY),
            "provenance_completeness": {
                "status": "complete",
                "retained": list(REQUIRED_PROVENANCE_RETAINED),
                "missing": [],
            },
        },
        "reviewed_processing_baseline_registry": json.loads(
            json.dumps(registry_block)
        ),
        "observed_processing_baselines": observed_baselines,
        "observed_platforms": observed_platforms,
        "rebuild_execution": execution_block,
        "raster_contract": dict(contract),
        "aggregate": {
            "object_count": len(object_list),
            "total_bytes": sum(obj["bytes"] for obj in object_list),
            "inventory_sha256": inventory_sha256(object_list),
            "minimum_extent_coverage_fraction": min(
                obj["extent_coverage_fraction"] for obj in object_list
            ),
            "maximum_extent_coverage_fraction": max(
                obj["extent_coverage_fraction"] for obj in object_list
            ),
            "range_violation_pixels": sum(
                obj["range_violation_pixels"] for obj in object_list
            ),
        },
        "objects": object_list,
    }
    validate_manifest_v2(manifest, raster_contract=contract)
    return manifest


def write_manifest_v2(
    manifest: Mapping[str, Any],
    path: Path,
    *,
    raster_contract: Mapping[str, Any] | None = None,
) -> Path:
    """Write a validated v2 manifest to a new file, never over v1 or an
    existing manifest.

    Validation always runs against the pinned production contract unless the
    caller explicitly injects one; the manifest's own embedded contract is
    never trusted to validate itself.
    """

    target = Path(path)
    _require(
        target.resolve() != Path(BASELINE_MANIFEST_PATH).resolve(),
        "refusing to write the v2 manifest over the immutable baseline "
        "1.0.0 manifest",
    )
    _require(
        not target.exists(),
        f"refusing to overwrite existing manifest {target}; baseline "
        "manifests are immutable once written",
    )
    validate_manifest_v2(manifest, raster_contract=raster_contract)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(manifest), ensure_ascii=False, indent=2) + "\n"
    target.write_text(payload, encoding="utf-8")
    return target


def load_manifest_v2(
    path: Path,
    *,
    raster_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and fully validate a stored baseline 2.0.0 manifest.

    A stored manifest is validated against the pinned production contract by
    default; its embedded contract cannot vouch for itself.
    """

    try:
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineManifestV2Error(
            f"cannot read baseline v2 manifest {path}: {exc}"
        ) from exc
    validate_manifest_v2(manifest, raster_contract=raster_contract)
    return manifest
