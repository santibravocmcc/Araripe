"""Package 2A.6C baseline-rebuild machinery for baseline version ``2.0.0``.

Rebuilds the 72-object monthly baseline with the identical accepted candidate
science, consuming — never redefining — the closed Package 2A.6B/2A.6B.1
modules:

- ``scl-explicit-allowlist-v2`` and its fail-closed metadata gates from
  :mod:`src.processing.scl_mask_v2`;
- ``coverage-ranked-first-valid-v1`` datatake-scoped composition from
  :mod:`src.processing.composition_v2`;
- the explicit GEE plan/parity path from
  :mod:`src.processing.gee_composition_v2`; and
- v3 acquisition identities from :mod:`src.detection.identity_v3`, so the
  platform enum (S2A/S2B/S2C; anything later fails closed) is enforced by the
  contract itself.

The v2 contract family remains audit-only: nothing here serializes into a v2
(or v1) identity, and the accepted baseline ``1.0.0`` manifest and objects are
never modified, deleted, or overwritten.

The reviewed processing-baseline registry
``araripe-reviewed-processing-baselines-v1`` (= {05.11, 05.12}) is consumed as
the base enumeration.  Historical baseline-source years are expected to carry
other provider baselines; those values become usable only through an explicit
recorded review extension loaded by :func:`load_baseline_rebuild_registry`,
never through a fallback, and every observed value must be enumerated in the
rebuild evidence and the new baseline manifest.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import numpy as np

from config.settings import (
    BASELINE_MAX_CLOUD_COVER,
    BASELINE_SOURCE_YEARS,
    GEE_COLLECTION_ID,
)
from src.detection.baseline_manifest import (
    MONITORING_EXTENT_BOUNDS,
    MONITORING_EXTENT_BOUNDS_SHA256,
    MONITORING_EXTENT_GEOMETRY_SHA256,
    MONITORING_EXTENT_ID,
)
from src.detection.identity import canonical_sha256
from src.detection.identity_v3 import (
    AcquisitionV3,
    acquisition_order_key,
    create_acquisition_v3,
    normalize_utc_timestamp,
    require_nonempty,
)
from src.processing.composition_v2 import (
    COMPOSITION_METHOD_ID,
    COMPOSITION_SCOPE_VERSION,
    PIXEL_SELECTION_POLICY,
    SCENE_ORDER_POLICY,
    DatatakeCompositeV2,
    SceneInputV2,
    compose_datatake,
    group_scenes_by_datatake,
    normalize_platform,
)
from src.processing.gee_composition_v2 import (
    GEE_MOSAIC_SEMANTICS,
    GEE_PLAN_VERSION,
    assert_local_gee_parity,
    execute_gee_plan_locally,
)
from src.processing.scl_mask_v2 import (
    CLOUD_SHADOW_DILATION_M,
    DARK_NIR_PROXIMITY_MASK,
    REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
    REVIEWED_PROCESSING_BASELINES,
    SCL_ACCEPTED_CLASSES,
    SCL_MASK_METHOD_ID,
    SCL_REJECTED_CLASSES,
    normalize_processing_baseline_value,
)


BASELINE_REBUILD_PLAN_VERSION = "phase2a6c-baseline-rebuild-plan-v1"
BASELINE_REBUILD_MONTH_EVIDENCE_VERSION = "phase2a6c-baseline-month-evidence-v1"
BASELINE_V2_VERSION = "2.0.0"
BASELINE_V1_VERSION = "1.0.0"
# Exact bytes of the accepted, immutable baseline 1.0.0 identity.
BASELINE_V1_MANIFEST_SHA256 = (
    "15a1ed3cea7c804d18d2c82c86a7b9a030687fedb01b315d543965b1f26f0a82"
)
BASELINE_V1_INVENTORY_SHA256 = (
    "c0ede11bb02cdcfbf67653dfee521f0e922955179c8da5b69c07ea5069cc1054"
)
# Checksum bindings of the accepted decision and amendment records.
DECISIONS_V2_PATH = "config/phase2a_candidate_generation_decisions_v2.json"
DECISIONS_V2_SHA256 = (
    "ac61fd1e6da376a147013a610652e38a6d3d119dcb8479b01001e156625cf69e"
)
AMENDMENT_V3_PATH = "config/phase2a_sentinel2c_contract_amendment_v3.json"
AMENDMENT_V3_SHA256 = (
    "0bb853259f5902ea93b34ed689662b46b66f5f696a9282482820f36f101414da"
)

BASELINE_V2_GRID_ID = "araripe-baseline-epsg32724-20m-grid-v1"
# The audited baseline 1.0.0 grid is retained unchanged so a rebuilt object is
# pixel-compatible with the detection reader and the accepted wider extent.
BASELINE_V2_GRID_CONTRACT = MappingProxyType(
    {
        "grid_id": BASELINE_V2_GRID_ID,
        "crs": "EPSG:32724",
        "width": 10773,
        "height": 4999,
        "transform": [20.0, 0.0, 290080.0, 0.0, -20.0, 9231780.0],
        "bounds": [290080.0, 9131800.0, 505540.0, 9231780.0],
        "pixel_size": [20.0, 20.0],
        "dtype": "float32",
        "band_count": 1,
        "nodata": "NaN",
        "scale_m": 20,
    }
)

# GEE provider band names; composition sorts band names by UTF-8 bytes.
REBUILD_BAND_NAMES = ("B11", "B12", "B4", "B8", "B8A")
REFLECTANCE_SCALE_DIVISOR = 10000
REBUILD_INDEX_NAMES = ("evi2", "nbr", "ndmi")
REBUILD_INDEX_FORMULAS = MappingProxyType(
    {
        "ndmi": "(B8A-B11)/(B8A+B11)",
        "nbr": "(B8A-B12)/(B8A+B12)",
        "evi2": "2.5*(B8-B4)/(B8+2.4*B4+1)",
    }
)

# ─── Export identity (deliberately disjoint from the v1 generation) ──────────
# Nothing about a v2 export may be confusable with a v1 one: different Drive
# folder, different file prefix, different local directories.  A v1 artifact
# can therefore never be split into the v2 inventory by accident.
BASELINE_V2_DRIVE_FOLDER = "araripe_baselines_v2"
BASELINE_V2_EXPORT_PREFIX = "araripe_baseline_v2_month"
BASELINE_V2_EXPORT_SUFFIX = ".tif"

# Nine bands per monthly export: the six baseline statistics plus the
# per-index contribution depth.  The v1 generation could not express how many
# observations backed a pixel, so a pixel whose statistics rest on a single
# composite was indistinguishable from a well-observed one.  Detection divides
# by this baseline's dispersion, so that depth is recorded, not inferred.
REBUILD_EXPORT_BAND_NAMES = (
    "ndmi_median",
    "nbr_median",
    "evi2_median",
    "ndmi_std",
    "nbr_std",
    "evi2_std",
    "ndmi_count",
    "nbr_count",
    "evi2_count",
)
# Earth Engine writes masked pixels as 0 in a GeoTIFF, which is a valid index
# value, so statistics are unmasked to a sentinel far outside every accepted
# range and restored to NaN locally.  A contribution count needs no sentinel:
# zero contributions is the honest value for a masked pixel.
STATISTIC_EXPORT_SENTINEL = -9999.0
COUNT_EXPORT_FILL = 0
CONTRIBUTION_COUNT_STATISTIC = "count"
CONTRIBUTION_COUNT_DTYPE = "int16"

MONTHLY_CENTRAL_STATISTIC = "median"
MONTHLY_DISPERSION_STATISTIC = "population_standard_deviation"
STATISTICS_COMPUTATION_DTYPE = "float64"
STATISTICS_OUTPUT_DTYPE = "float32"
NONFINITE_INDEX_POLICY = "nonfinite_index_values_become_missing_and_are_counted"
COMPOSITE_STACK_ORDER_POLICY = (
    "acquisition_timestamp_utc_then_acquisition_id",
)

# Proven against the acquisition-v3 contract by the Package 2A.6C tests; the
# contract, not this tuple, is the platform authority.
V3_REPRESENTABLE_PLATFORMS = ("S2A", "S2B", "S2C")
PLATFORM_POLICY = MappingProxyType(
    {
        "identity_contract": "acquisition-v3",
        "allowed_platforms": list(V3_REPRESENTABLE_PLATFORMS),
        "unlisted_platform_policy": "unavailable_fail_closed",
    }
)

REBUILD_COUNT_SOURCES = ("local_reference_composite", "gee_reduce_region")

_DATATAKE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S"


class BaselineRebuildError(ValueError):
    """Raised when a rebuild input violates the Package 2A.6C contract."""


# ─── Reviewed processing-baseline registry with recorded-review extension ────


@dataclass(frozen=True)
class BaselineRebuildRegistryV2:
    """The effective reviewed registry for the baseline rebuild.

    ``base_values`` is always the closed 2A.6B registry; ``added_values`` come
    only from an explicit recorded review.  There is no fallback path: a
    provider baseline outside ``effective_values`` keeps failing closed inside
    the consumed mask/composition modules.
    """

    registry_id: str
    base_values: tuple[str, ...]
    added_values: tuple[str, ...]
    extension: Mapping[str, Any] | None

    @property
    def effective_values(self) -> tuple[str, ...]:
        return tuple(sorted({*self.base_values, *self.added_values}))

    def registry_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "registry_id": self.registry_id,
            "base_reviewed_values": list(self.base_values),
            "added_reviewed_values": list(self.added_values),
            "reviewed_values": list(self.effective_values),
            "unreviewed_value_policy": "unavailable_fail_closed",
            "extension_policy": "recorded_review_only_never_fallback",
        }
        if self.extension is not None:
            payload["recorded_review_extension"] = {
                key: self.extension[key]
                for key in (
                    "extension_id",
                    "reviewed_by",
                    "review_date",
                    "review_scope",
                    "added_values",
                )
            }
        return payload


def base_rebuild_registry() -> BaselineRebuildRegistryV2:
    """Return the unextended registry (exactly the closed 2A.6B enumeration)."""

    return BaselineRebuildRegistryV2(
        registry_id=REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
        base_values=tuple(REVIEWED_PROCESSING_BASELINES),
        added_values=(),
        extension=None,
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BaselineRebuildError(message)


def _require_iso_date(value: Any, *, label: str) -> str:
    _require(isinstance(value, str), f"{label} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BaselineRebuildError(f"{label} must be an ISO calendar date") from exc
    _require(parsed.isoformat() == value, f"{label} must use YYYY-MM-DD form")
    return value


def validate_registry_extension(extension: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one recorded-review registry extension document."""

    _require(isinstance(extension, Mapping), "registry extension must be a mapping")
    _require(
        extension.get("schema_version") == "1.0.0",
        "registry extension schema_version must be 1.0.0",
    )
    extension_id = extension.get("extension_id")
    _require(
        isinstance(extension_id, str) and bool(extension_id),
        "registry extension needs a non-empty extension_id",
    )
    _require(
        extension.get("base_registry_id")
        == REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
        "registry extension must extend "
        + REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
    )
    _require(
        extension.get("base_reviewed_values")
        == list(REVIEWED_PROCESSING_BASELINES),
        "registry extension must restate the exact closed base registry values",
    )
    for field in ("reviewed_by", "review_scope"):
        value = extension.get(field)
        _require(
            isinstance(value, str) and bool(value.strip()),
            f"registry extension needs a non-empty {field}",
        )
    _require_iso_date(extension.get("review_date"), label="review_date")

    added = extension.get("added_values")
    _require(
        isinstance(added, list) and bool(added),
        "registry extension must add at least one reviewed value",
    )
    normalized_added: list[str] = []
    for entry in added:
        _require(
            isinstance(entry, Mapping),
            "each added registry value must be a review record",
        )
        value = entry.get("value")
        _require(isinstance(value, str), "added value must be a string")
        normalized = normalize_processing_baseline_value(
            value, source_field="registry extension added value"
        )
        _require(
            normalized == value,
            f"added value {value!r} must already use normalized NN.NN form",
        )
        _require(
            value not in REVIEWED_PROCESSING_BASELINES,
            f"added value {value} is already in the closed base registry",
        )
        _require(
            value not in normalized_added,
            f"added value {value} is duplicated in the extension",
        )
        for field in ("review_basis", "observed_in"):
            text = entry.get(field)
            _require(
                isinstance(text, str) and bool(text.strip()),
                f"added value {value} needs a non-empty {field}",
            )
        normalized_added.append(value)
    return {
        "schema_version": "1.0.0",
        "extension_id": extension_id,
        "base_registry_id": REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
        "base_reviewed_values": list(REVIEWED_PROCESSING_BASELINES),
        "reviewed_by": extension["reviewed_by"],
        "review_date": extension["review_date"],
        "review_scope": extension["review_scope"],
        "added_values": [
            {
                "value": entry["value"],
                "review_basis": entry["review_basis"],
                "observed_in": entry["observed_in"],
            }
            for entry in added
        ],
    }


def load_baseline_rebuild_registry(
    extension_path: Path | None,
) -> BaselineRebuildRegistryV2:
    """Load the effective registry, optionally extended by a recorded review."""

    if extension_path is None:
        return base_rebuild_registry()
    path = Path(extension_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineRebuildError(
            f"cannot read registry extension {path}: {exc}"
        ) from exc
    extension = validate_registry_extension(raw)
    return BaselineRebuildRegistryV2(
        registry_id=REVIEWED_PROCESSING_BASELINE_REGISTRY_ID,
        base_values=tuple(REVIEWED_PROCESSING_BASELINES),
        added_values=tuple(
            entry["value"] for entry in extension["added_values"]
        ),
        extension=MappingProxyType(extension),
    )


# ─── Declared baseline source datatakes ──────────────────────────────────────


@dataclass(frozen=True)
class BaselineSourceDatatakeV2:
    """One declared physical source datatake of the baseline rebuild."""

    year: int
    month: int
    platform: str
    datatake_id: str
    acquisition_timestamp_utc: str
    scenes: tuple[SceneInputV2, ...]


def declare_baseline_source_datatake(
    *,
    year: int,
    month: int,
    platform: str,
    datatake_id: str,
    acquisition_timestamp_utc: str | datetime,
    scenes: Iterable[SceneInputV2],
) -> BaselineSourceDatatakeV2:
    """Validate one declared source datatake against the rebuild contract."""

    _require(
        year in BASELINE_SOURCE_YEARS,
        f"year {year} is not in the accepted baseline source years "
        f"{BASELINE_SOURCE_YEARS}",
    )
    _require(month in range(1, 13), f"month {month} must be 1..12")
    normalized_platform = normalize_platform(platform)
    datatake_id = require_nonempty(datatake_id, label="datatake_id")
    timestamp = normalize_utc_timestamp(
        acquisition_timestamp_utc, label="acquisition_timestamp_utc"
    )
    instant = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    _require(
        instant.year == year and instant.month == month,
        f"acquisition timestamp {timestamp} is outside the declared "
        f"baseline slot {year}-{month:02d}",
    )
    if datatake_id.startswith("GS2"):
        parts = datatake_id.split("_")
        _require(
            len(parts) >= 2,
            f"provider datatake_id {datatake_id!r} embeds no sensing instant",
        )
        _require(
            instant.strftime(_DATATAKE_TIMESTAMP_FORMAT) == parts[1],
            f"declared acquisition timestamp {timestamp} disagrees with the "
            f"sensing instant embedded in datatake {datatake_id}",
        )
    scene_records = tuple(scenes)
    _require(
        bool(scene_records),
        f"datatake {datatake_id} declares no provider-native scenes",
    )
    groups = group_scenes_by_datatake(scene_records)
    if len(groups) != 1 or (groups[0].platform, groups[0].datatake_id) != (
        normalized_platform,
        datatake_id,
    ):
        raise BaselineRebuildError(
            f"scenes supplied for datatake {datatake_id} do not form exactly "
            "that one physical datatake; different datatakes are never "
            "composed"
        )
    for scene in scene_records:
        scene_bands = tuple(
            sorted(scene.bands, key=lambda item: item.encode("utf-8"))
        )
        _require(
            scene_bands == REBUILD_BAND_NAMES,
            f"scene {scene.scene_id} band set {scene_bands} differs from the "
            f"rebuild band contract {REBUILD_BAND_NAMES}",
        )
    return BaselineSourceDatatakeV2(
        year=year,
        month=month,
        platform=normalized_platform,
        datatake_id=datatake_id,
        acquisition_timestamp_utc=timestamp,
        scenes=scene_records,
    )


def rebuild_acquisition_v3(
    datatake: BaselineSourceDatatakeV2,
    *,
    run_manifest_id: str,
    run_manifest_sha256: str,
) -> AcquisitionV3:
    """Bind one source datatake to a v3 acquisition identity.

    The acquisition-v3 contract — not this module — decides platform
    representability, so Sentinel-2C is accepted and any unreviewed later
    unit (for example Sentinel-2D) fails closed here.
    """

    return create_acquisition_v3(
        run_manifest_id=run_manifest_id,
        run_manifest_sha256=run_manifest_sha256,
        collection_id=GEE_COLLECTION_ID,
        platform=datatake.platform,
        datatake_id=datatake.datatake_id,
        acquisition_timestamp_utc=datatake.acquisition_timestamp_utc,
        scene_ids=tuple(scene.scene_id for scene in datatake.scenes),
        monitoring_extent_id=MONITORING_EXTENT_ID,
        composite_method_id=COMPOSITION_METHOD_ID,
        grid_id=BASELINE_V2_GRID_ID,
    )


# ─── Counts-derived GEE plan (shared with the production-scale executor) ─────


def derive_first_valid_order(
    valid_pixel_counts: Mapping[str, int],
) -> tuple[str, ...]:
    """Derive the explicit coverage-ranked first-valid order from counts."""

    _require(
        isinstance(valid_pixel_counts, Mapping) and bool(valid_pixel_counts),
        "valid_pixel_counts must be a non-empty mapping",
    )
    for scene_id, count in valid_pixel_counts.items():
        require_nonempty(scene_id, label="scene_id")
        _require(
            isinstance(count, int) and not isinstance(count, bool) and count >= 0,
            f"valid pixel count for scene {scene_id} must be a non-negative "
            "integer",
        )
    return tuple(
        sorted(
            valid_pixel_counts,
            key=lambda scene_id: (
                -valid_pixel_counts[scene_id],
                scene_id.encode("utf-8"),
            ),
        )
    )


def build_rebuild_gee_plan(
    *,
    image_collection_id: str,
    platform: str,
    datatake_id: str,
    band_names: Iterable[str],
    valid_pixel_counts: Mapping[str, int],
    observed_processing_baselines: Iterable[str],
    count_source: str,
) -> dict[str, Any]:
    """Build the explicit GEE plan for one rebuild datatake from counts.

    This is the same ``gee-coverage-ranked-first-valid-plan-v1`` structure the
    2A.6B executor validates: :func:`execute_gee_plan_locally` accepts it and
    re-derives every gate.  Unlike ``build_gee_composition_plan`` it needs no
    local composite, so the production-scale executor can derive the identical
    plan from GEE ``reduceRegion`` counts before any mosaic is built; the
    fixture-scale parity tests prove both derivations agree byte for byte in
    ``first_valid_order`` and execution output.
    """

    require_nonempty(image_collection_id, label="image_collection_id")
    normalized_platform = normalize_platform(platform)
    datatake_id = require_nonempty(datatake_id, label="datatake_id")
    _require(
        count_source in REBUILD_COUNT_SOURCES,
        f"count_source must be one of {REBUILD_COUNT_SOURCES}",
    )
    names = tuple(band_names)
    _require(
        names == tuple(sorted(names, key=lambda item: item.encode("utf-8")))
        and bool(names),
        "band_names must be UTF-8 sorted and non-empty",
    )
    first_valid_order = list(derive_first_valid_order(valid_pixel_counts))
    mosaic_input_order = list(reversed(first_valid_order))
    body: dict[str, Any] = {
        "gee_plan_version": GEE_PLAN_VERSION,
        "composite_method_id": COMPOSITION_METHOD_ID,
        "composition_scope_version": COMPOSITION_SCOPE_VERSION,
        "scl_mask_method_id": SCL_MASK_METHOD_ID,
        "image_collection_id": image_collection_id,
        "platform": normalized_platform,
        "datatake_id": datatake_id,
        "band_names": list(names),
        "mask": {
            "scl_band": "SCL",
            "accepted_scl_classes": list(SCL_ACCEPTED_CLASSES),
            "band_mask_intersection_required": True,
            "single_shared_mask_per_image": True,
            "note": (
                "updateMask() every band with ONE combined mask "
                "(SCL allowlist AND the intersection of all band masks) so "
                "mosaic() cannot mix bands of one pixel across scenes"
            ),
        },
        "mosaic_semantics": GEE_MOSAIC_SEMANTICS,
        "first_valid_order": first_valid_order,
        "mosaic_input_order": mosaic_input_order,
        "order_note": (
            "ee.ImageCollection.fromImages(mosaic_input_order).mosaic() keeps "
            "the LAST valid image per pixel, so the most-preferred scene of "
            "first_valid_order must be LAST in mosaic_input_order"
        ),
        "expected_scene_valid_pixel_counts": {
            scene_id: valid_pixel_counts[scene_id]
            for scene_id in first_valid_order
        },
        "contributor_accounting": {
            "per_image_constant_band": "contributor_rank",
            "rank_source": "index_into_first_valid_order",
            "no_contribution_sentinel": -1,
        },
        "observed_processing_baselines": sorted(
            set(observed_processing_baselines)
        ),
        "valid_pixel_count_source": count_source,
    }
    return {**body, "gee_plan_sha256": canonical_sha256(body)}


# ─── Index computation on composed reflectance bands ─────────────────────────


def compute_index_grids(
    composed_bands: Mapping[str, np.ndarray],
) -> tuple[dict[str, np.ndarray], dict[str, int]]:
    """Compute the three baseline indices from composed reflectance bands.

    Bands are surface reflectance (DN / 10000) composed so every band of a
    pixel comes from one scene.  A pixel whose index value is non-finite after
    computation (for example a zero denominator) becomes missing (NaN) and is
    counted per index; it can then never contribute to a monthly statistic.
    """

    for name in REBUILD_BAND_NAMES:
        _require(
            name in composed_bands,
            f"composed bands are missing required band {name}",
        )
    b4 = np.asarray(composed_bands["B4"], dtype=np.float64)
    b8 = np.asarray(composed_bands["B8"], dtype=np.float64)
    b8a = np.asarray(composed_bands["B8A"], dtype=np.float64)
    b11 = np.asarray(composed_bands["B11"], dtype=np.float64)
    b12 = np.asarray(composed_bands["B12"], dtype=np.float64)
    composed = np.isfinite(b4) & np.isfinite(b8) & np.isfinite(b8a)
    composed &= np.isfinite(b11) & np.isfinite(b12)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = {
            "ndmi": (b8a - b11) / (b8a + b11),
            "nbr": (b8a - b12) / (b8a + b12),
            "evi2": 2.5 * (b8 - b4) / (b8 + 2.4 * b4 + 1.0),
        }
    grids: dict[str, np.ndarray] = {}
    nonfinite_counts: dict[str, int] = {}
    for index in REBUILD_INDEX_NAMES:
        values = raw[index]
        nonfinite_on_composed = composed & ~np.isfinite(values)
        nonfinite_counts[index] = int(nonfinite_on_composed.sum())
        cleaned = np.where(np.isfinite(values), values, np.nan)
        cleaned.setflags(write=False)
        grids[index] = cleaned
    return grids, nonfinite_counts


# ─── Rebuild composition of one datatake (local reference + parity) ──────────


@dataclass(frozen=True)
class RebuildDatatakeCompositionV2:
    """One composed rebuild datatake with plan, parity, and index evidence."""

    datatake: BaselineSourceDatatakeV2
    acquisition: AcquisitionV3
    composite: DatatakeCompositeV2
    gee_plan: Mapping[str, Any]
    parity_evidence: Mapping[str, Any]
    index_grids: Mapping[str, np.ndarray]
    nonfinite_index_counts: Mapping[str, int]

    def evidence_entry(self) -> dict[str, Any]:
        return {
            "acquisition_id": self.acquisition.acquisition_id,
            "platform": self.acquisition.platform,
            "datatake_id": self.acquisition.datatake_id,
            "acquisition_timestamp_utc": (
                self.acquisition.acquisition_timestamp_utc
            ),
            "year": self.datatake.year,
            "month": self.datatake.month,
            "scene_ids": list(self.acquisition.scene_ids),
            "scene_processing_baselines": {
                mask.scene_id: mask.processing_baseline.normalized_value
                for mask in self.composite.scene_masks
            },
            "observed_processing_baselines": list(
                self.composite.observed_processing_baselines
            ),
            "composed_pixel_count": self.composite.composed_pixel_count,
            "composition_evidence_sha256": (
                self.composite.composition_evidence_sha256
            ),
            "gee_plan_sha256": self.gee_plan["gee_plan_sha256"],
            "parity": {
                "verified": True,
                "parity_evidence_sha256": self.parity_evidence[
                    "parity_evidence_sha256"
                ],
            },
            "nonfinite_index_counts": dict(self.nonfinite_index_counts),
        }


def compose_rebuild_datatake(
    datatake: BaselineSourceDatatakeV2,
    *,
    registry: BaselineRebuildRegistryV2,
    run_manifest_id: str,
    run_manifest_sha256: str,
    image_collection_id: str = GEE_COLLECTION_ID,
) -> RebuildDatatakeCompositionV2:
    """Compose one source datatake exactly as the rebuild contract requires.

    Fails closed (propagating the typed 2A.6B errors) on missing, unexpected,
    or unreviewed SCL/processing-baseline metadata; a platform outside the v3
    contract fails closed before any pixel is read.
    """

    _require(
        isinstance(datatake, BaselineSourceDatatakeV2),
        "compose_rebuild_datatake requires a BaselineSourceDatatakeV2",
    )
    _require(
        isinstance(registry, BaselineRebuildRegistryV2),
        "registry must be a BaselineRebuildRegistryV2",
    )
    acquisition = rebuild_acquisition_v3(
        datatake,
        run_manifest_id=run_manifest_id,
        run_manifest_sha256=run_manifest_sha256,
    )
    group = group_scenes_by_datatake(datatake.scenes)[0]
    composite = compose_datatake(
        group, reviewed_baselines=registry.effective_values
    )
    plan = build_rebuild_gee_plan(
        image_collection_id=image_collection_id,
        platform=composite.platform,
        datatake_id=composite.datatake_id,
        band_names=composite.band_names,
        valid_pixel_counts=composite.scene_valid_pixel_counts,
        observed_processing_baselines=composite.observed_processing_baselines,
        count_source="local_reference_composite",
    )
    _require(
        tuple(plan["first_valid_order"])
        == composite.composition_order_scene_ids,
        "counts-derived plan order disagrees with the composed first-valid "
        "order",
    )
    execution = execute_gee_plan_locally(
        plan,
        datatake.scenes,
        reviewed_baselines=registry.effective_values,
    )
    parity_evidence = assert_local_gee_parity(composite, execution)
    index_grids, nonfinite_counts = compute_index_grids(
        composite.composed_bands
    )
    return RebuildDatatakeCompositionV2(
        datatake=datatake,
        acquisition=acquisition,
        composite=composite,
        gee_plan=MappingProxyType(dict(plan)),
        parity_evidence=MappingProxyType(dict(parity_evidence)),
        index_grids=MappingProxyType(index_grids),
        nonfinite_index_counts=MappingProxyType(nonfinite_counts),
    )


# ─── Monthly statistics across datatake composites ───────────────────────────


def _array_digest(array: np.ndarray) -> dict[str, Any]:
    contiguous = np.ascontiguousarray(array)
    return {
        "dtype": str(contiguous.dtype),
        "shape": list(contiguous.shape),
        "sha256": hashlib.sha256(contiguous.tobytes()).hexdigest(),
    }


@dataclass(frozen=True)
class MonthlyBaselineStatisticsV2:
    """Median/std/count statistics of one calendar month across datatakes."""

    month: int
    acquisition_ids: tuple[str, ...]
    median: Mapping[str, np.ndarray]
    std: Mapping[str, np.ndarray]
    contribution_count: Mapping[str, np.ndarray]
    evidence: Mapping[str, Any]
    month_evidence_sha256: str


def compute_monthly_baseline_statistics(
    month: int,
    compositions: Iterable[RebuildDatatakeCompositionV2],
    *,
    registry: BaselineRebuildRegistryV2,
) -> MonthlyBaselineStatisticsV2:
    """Reduce one month's datatake composites to the baseline statistics.

    Every retained datatake composite of the month contributes exactly once.
    The stack order is canonical (acquisition timestamp, then acquisition ID)
    so repeated runs and permuted inputs produce byte-identical statistics.
    Pixels with no contributing composite are NaN in both statistics and zero
    in the contribution count.
    """

    _require(month in range(1, 13), f"month {month} must be 1..12")
    records = tuple(compositions)
    _require(bool(records), f"month {month} has no datatake composites")
    for record in records:
        _require(
            isinstance(record, RebuildDatatakeCompositionV2),
            "compositions must be RebuildDatatakeCompositionV2 records",
        )
        _require(
            record.datatake.month == month,
            f"acquisition {record.acquisition.acquisition_id} belongs to "
            f"month {record.datatake.month}, not {month}",
        )
    ordered = tuple(
        sorted(records, key=lambda record: acquisition_order_key(record.acquisition))
    )
    acquisition_ids = tuple(
        record.acquisition.acquisition_id for record in ordered
    )
    _require(
        len(set(acquisition_ids)) == len(acquisition_ids),
        f"month {month} contains a duplicate acquisition",
    )
    shape = ordered[0].index_grids[REBUILD_INDEX_NAMES[0]].shape
    for record in ordered:
        for index in REBUILD_INDEX_NAMES:
            _require(
                record.index_grids[index].shape == shape,
                "all datatake composites of a month must share the rebuild "
                "grid",
            )

    median: dict[str, np.ndarray] = {}
    std: dict[str, np.ndarray] = {}
    counts: dict[str, np.ndarray] = {}
    for index in REBUILD_INDEX_NAMES:
        stack = np.stack(
            [
                np.asarray(record.index_grids[index], dtype=np.float64)
                for record in ordered
            ],
            axis=0,
        )
        finite = np.isfinite(stack)
        count = finite.sum(axis=0).astype(np.int32)
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            # An all-NaN pixel column is a defined state (no contribution),
            # not a numerical accident worth a RuntimeWarning per pixel.
            warnings.simplefilter("ignore", RuntimeWarning)
            median_values = np.nanmedian(stack, axis=0)
            std_values = np.nanstd(stack, axis=0, ddof=0)
        empty = count == 0
        median_values[empty] = np.nan
        std_values[empty] = np.nan
        median_out = median_values.astype(np.float32)
        std_out = std_values.astype(np.float32)
        median_out.setflags(write=False)
        std_out.setflags(write=False)
        count.setflags(write=False)
        median[index] = median_out
        std[index] = std_out
        counts[index] = count

    observed_baselines = sorted(
        {
            value
            for record in ordered
            for value in record.composite.observed_processing_baselines
        }
    )
    observed_platforms = sorted(
        {record.acquisition.platform for record in ordered}
    )
    _require(
        all(value in registry.effective_values for value in observed_baselines),
        "a composed datatake carries a processing baseline outside the "
        "effective reviewed registry",
    )
    evidence_body: dict[str, Any] = {
        "month_evidence_version": BASELINE_REBUILD_MONTH_EVIDENCE_VERSION,
        "baseline_version": BASELINE_V2_VERSION,
        "month": month,
        "composite_stack_order_policy": list(COMPOSITE_STACK_ORDER_POLICY),
        "statistics": {
            "central": MONTHLY_CENTRAL_STATISTIC,
            "dispersion": MONTHLY_DISPERSION_STATISTIC,
            "computation_dtype": STATISTICS_COMPUTATION_DTYPE,
            "output_dtype": STATISTICS_OUTPUT_DTYPE,
            "nonfinite_index_policy": NONFINITE_INDEX_POLICY,
            "empty_stack_pixel_policy": "nan_statistics_zero_count",
        },
        "datatakes": [record.evidence_entry() for record in ordered],
        "observed_processing_baselines": observed_baselines,
        "observed_platforms": observed_platforms,
        "reviewed_processing_baseline_registry": registry.registry_dict(),
        "arrays": {
            index: {
                "median": _array_digest(median[index]),
                "std": _array_digest(std[index]),
                "contribution_count": _array_digest(counts[index]),
            }
            for index in REBUILD_INDEX_NAMES
        },
    }
    evidence_sha256 = canonical_sha256(evidence_body)
    evidence = {**evidence_body, "month_evidence_sha256": evidence_sha256}
    return MonthlyBaselineStatisticsV2(
        month=month,
        acquisition_ids=acquisition_ids,
        median=MappingProxyType(median),
        std=MappingProxyType(std),
        contribution_count=MappingProxyType(counts),
        evidence=MappingProxyType(evidence),
        month_evidence_sha256=evidence_sha256,
    )


# ─── The deterministic rebuild plan (run-manifest binding for v3 IDs) ────────


def build_baseline_rebuild_plan(
    *,
    registry: BaselineRebuildRegistryV2,
) -> dict[str, Any]:
    """Build the deterministic Package 2A.6C rebuild plan document.

    The plan is the executable instruction sheet for the Earth Engine rebuild.
    Its canonical checksum is the v3 run-manifest binding for every rebuild
    acquisition, so identical plans always bind identical identities.
    """

    _require(
        isinstance(registry, BaselineRebuildRegistryV2),
        "registry must be a BaselineRebuildRegistryV2",
    )
    body: dict[str, Any] = {
        "rebuild_plan_version": BASELINE_REBUILD_PLAN_VERSION,
        "baseline_id": "araripe-s2-sr-harmonized-monthly",
        "baseline_version": BASELINE_V2_VERSION,
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
        "source": {
            "collection_id": GEE_COLLECTION_ID,
            "years": list(BASELINE_SOURCE_YEARS),
            "months": list(range(1, 13)),
            "scene_cloud_filter_percent": BASELINE_MAX_CLOUD_COVER,
            "scene_admission_note": (
                "scene metadata filter carried unchanged from the accepted "
                "baseline 1.0.0 configuration; the per-pixel mask is the "
                "selected v2 allowlist"
            ),
            "reflectance_scale_divisor": REFLECTANCE_SCALE_DIVISOR,
            "band_names": list(REBUILD_BAND_NAMES),
            "index_formulas": dict(REBUILD_INDEX_FORMULAS),
        },
        "monitoring_extent": {
            "extent_id": MONITORING_EXTENT_ID,
            "scope": "APA and surroundings",
            "crs": "EPSG:4326",
            "bounds": list(MONITORING_EXTENT_BOUNDS),
            "geometry_sha256": MONITORING_EXTENT_GEOMETRY_SHA256,
            "bounds_sha256": MONITORING_EXTENT_BOUNDS_SHA256,
        },
        "grid": dict(BASELINE_V2_GRID_CONTRACT),
        "scene_grid_placement": (
            "each provider scene is evaluated on the common baseline grid; "
            "pixels outside the scene footprint carry SCL 0 (no-data) and "
            "NaN bands, so they can never contribute"
        ),
        "mask": {
            "scl_mask_method_id": SCL_MASK_METHOD_ID,
            "accepted_scl_classes": list(SCL_ACCEPTED_CLASSES),
            "rejected_scl_classes": list(SCL_REJECTED_CLASSES),
            "dark_nir_proximity_mask": DARK_NIR_PROXIMITY_MASK,
            "cloud_shadow_dilation_m": CLOUD_SHADOW_DILATION_M,
            "unreviewed_scl_or_baseline_policy": "unavailable_fail_closed",
            "identical_to_candidate_generation": True,
        },
        "reviewed_processing_baseline_registry": registry.registry_dict(),
        "composition": {
            "composite_method_id": COMPOSITION_METHOD_ID,
            "composition_scope_version": COMPOSITION_SCOPE_VERSION,
            "scene_order_policy": list(SCENE_ORDER_POLICY),
            "pixel_selection": PIXEL_SELECTION_POLICY,
            "different_datatakes_never_composed": True,
        },
        "gee_execution": {
            "gee_plan_version": GEE_PLAN_VERSION,
            "mosaic_semantics": GEE_MOSAIC_SEMANTICS,
            "two_phase_execution": [
                "phase 1: enumerate scenes/datatakes, read every "
                "SCL/processing-baseline metadata value, and compute "
                "per-scene valid-pixel counts",
                "phase 2: derive the per-datatake plan from those counts and "
                "mosaic strictly in the plan's reversed order",
            ],
            "valid_pixel_count_sources": list(REBUILD_COUNT_SOURCES),
            "count_reconciliation": (
                "recomputed counts must equal the plan's expected counts "
                "before any composite is trusted"
            ),
            "export": {
                "destination": "google_drive",
                "drive_folder": BASELINE_V2_DRIVE_FOLDER,
                "file_name_prefix": BASELINE_V2_EXPORT_PREFIX,
                "one_export_per_month": True,
                "band_names": list(REBUILD_EXPORT_BAND_NAMES),
                "statistic_export_sentinel": STATISTIC_EXPORT_SENTINEL,
                "count_export_fill": COUNT_EXPORT_FILL,
                "v1_artifacts_never_reused": True,
            },
        },
        "platform_policy": dict(PLATFORM_POLICY),
        "statistics": {
            "central": MONTHLY_CENTRAL_STATISTIC,
            "dispersion": MONTHLY_DISPERSION_STATISTIC,
            "computation_dtype": STATISTICS_COMPUTATION_DTYPE,
            "output_dtype": STATISTICS_OUTPUT_DTYPE,
            "composite_stack_order_policy": list(COMPOSITE_STACK_ORDER_POLICY),
            "nonfinite_index_policy": NONFINITE_INDEX_POLICY,
            "unit_of_contribution": "one_datatake_composite",
            "contribution_count_recorded": True,
            "contribution_count_policy": (
                "per index and month the number of contributing datatake "
                "composites is exported, split, checksummed, and summarised; "
                "a minimum-depth rejection threshold is deliberately NOT "
                "applied here and remains an owner/Phase 5 decision"
            ),
        },
        "output_contract": {
            "expected_object_count": 72,
            "indices": list(REBUILD_INDEX_NAMES),
            "filename_statistics": {
                "mean": "multi-year monthly median",
                "std": "multi-year monthly population standard deviation",
            },
            "dtype": STATISTICS_OUTPUT_DTYPE,
            "nodata": "NaN",
            "minimum_extent_coverage_fraction": 0.99,
        },
    }
    plan_sha256 = canonical_sha256(body)
    return {**body, "rebuild_plan_sha256": plan_sha256}


def run_manifest_binding_from_plan(
    plan: Mapping[str, Any],
) -> tuple[str, str]:
    """Derive the v3 run-manifest binding from a rebuild plan document."""

    _require(
        isinstance(plan, Mapping)
        and plan.get("rebuild_plan_version") == BASELINE_REBUILD_PLAN_VERSION,
        "plan is not a Package 2A.6C baseline rebuild plan",
    )
    body = {
        key: value
        for key, value in plan.items()
        if key != "rebuild_plan_sha256"
    }
    plan_sha256 = canonical_sha256(body)
    _require(
        plan.get("rebuild_plan_sha256") == plan_sha256,
        "rebuild plan checksum does not match its contents",
    )
    return "run-v3-" + plan_sha256, plan_sha256


# ─── Export naming, query fingerprint, and contribution-depth evidence ───────


def month_export_filename(month: int) -> str:
    """Return the canonical v2 monthly export filename for one month."""

    _require(month in range(1, 13), f"month {month} must be 1..12")
    return f"{BASELINE_V2_EXPORT_PREFIX}{month:02d}{BASELINE_V2_EXPORT_SUFFIX}"


def contribution_count_filename(index: str, month: int) -> str:
    """Return the canonical contribution-count filename for one index/month.

    The ``_count`` statistic is deliberately outside the audited 72-name
    inventory (which carries only ``_mean`` and ``_std``), so a count raster
    can never be mistaken for a baseline object.
    """

    _require(
        index in REBUILD_INDEX_NAMES,
        f"index {index!r} is not one of {REBUILD_INDEX_NAMES}",
    )
    _require(month in range(1, 13), f"month {month} must be 1..12")
    return f"{index}_month{month:02d}_{CONTRIBUTION_COUNT_STATISTIC}.tif"


def baseline_query_fingerprint() -> str:
    """Return the deterministic fingerprint of the baseline source query.

    The 2A.2 audit could not reconstruct the historical query; recording a
    canonical fingerprint of the exact source selection makes a future
    generation comparable to this one instead of merely similar.
    """

    return canonical_sha256(
        {
            "query_fingerprint_version": "phase2a6c-baseline-query-v1",
            "collection_id": GEE_COLLECTION_ID,
            "years": list(BASELINE_SOURCE_YEARS),
            "months": list(range(1, 13)),
            "scene_cloud_filter_percent": BASELINE_MAX_CLOUD_COVER,
            "monitoring_extent_id": MONITORING_EXTENT_ID,
            "monitoring_extent_bounds": list(MONITORING_EXTENT_BOUNDS),
            "grid": dict(BASELINE_V2_GRID_CONTRACT),
            "band_names": list(REBUILD_BAND_NAMES),
            "reflectance_scale_divisor": REFLECTANCE_SCALE_DIVISOR,
        }
    )


def contribution_count_summary(counts: Any) -> dict[str, Any]:
    """Summarise one index/month contribution-depth grid.

    Detection divides an observation's departure by this baseline's monthly
    dispersion.  A pixel backed by a single datatake composite has a
    population standard deviation of exactly zero, and two composites give a
    dispersion that is arithmetically defined but statistically meaningless,
    so the shallow tail is measured explicitly rather than left implicit.

    No rejection threshold is applied: choosing a minimum depth is an owner
    and Phase 5 scientific decision, not a build-time one.
    """

    array = np.asarray(counts)
    _require(array.ndim == 2 and array.size > 0, "counts must be a 2-D grid")
    _require(
        array.dtype.kind in "iu",
        f"contribution counts must be integer-typed, got {array.dtype}",
    )
    _require(int(array.min()) >= 0, "contribution counts cannot be negative")
    flat = array.reshape(-1)
    return {
        "total_pixels": int(array.size),
        "minimum": int(flat.min()),
        "maximum": int(flat.max()),
        "median": float(np.median(flat)),
        "pixels_with_zero_contributions": int((flat == 0).sum()),
        "pixels_below_three_contributions": int((flat < 3).sum()),
    }
