"""Package 2A.6B composition: ``coverage-ranked-first-valid-v1``.

Implements the composition selected by
``config/phase2a_candidate_generation_decisions_v2.json``, scoped strictly to
one physical Sentinel-2 datatake (``datatake-scoped-v2``):

- scenes are ordered by ``valid_pixel_count`` descending, then provider
  native scene ID UTF-8 ascending;
- each pixel takes every band from the first valid scene in that explicit
  order, never mixing bands across scenes;
- a contributor map and per-scene contributor counts are always produced;
- different datatakes are never composed, even on the same UTC date; and
- per-scene and per-composite SCL 7 fractions are recorded as QA only.

Scene validity combines the ``scl-explicit-allowlist-v2`` mask with the
intersection of finite values across every band, so a pixel with any missing
band cannot contribute partial bands from that scene.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import numpy as np

from src.detection.identity import canonical_sha256
from src.detection.identity_v2 import require_nonempty
from src.processing.scl_mask_v2 import (
    REVIEWED_PROCESSING_BASELINES,
    SCL7_QA_POLICY,
    SCL_MASK_METHOD_ID,
    SceneSclMaskV2,
    SclMaskUnavailableError,
    compute_scene_scl_mask,
    enumerate_observed_baselines,
    read_processing_baseline,
    require_datatake_baseline_consistency,
    require_reviewed_processing_baseline,
    reviewed_baseline_registry_dict,
)


COMPOSITION_METHOD_ID = "coverage-ranked-first-valid-v1"
COMPOSITION_SCOPE_VERSION = "datatake-scoped-v2"
COMPOSITION_EVIDENCE_VERSION = "phase2a6b-composition-evidence-v1"
SCENE_ORDER_POLICY = (
    "valid_pixel_count_desc",
    "provider_native_scene_id_utf8_asc",
)
PIXEL_SELECTION_POLICY = "first_valid_scene_in_explicit_order"
NO_CONTRIBUTION_SENTINEL = -1

_PLATFORM_RE = re.compile(r"^(?:s2|sentinel-?2)([a-d])$")
_DATATAKE_PLATFORM_RE = re.compile(r"^GS2([A-D])_")


def normalize_platform(value: str) -> str:
    """Normalize provider platform labels (``sentinel-2b``/``S2B``) to ``S2B``.

    Normalization is mechanical for constellation units A-D.  Whether a
    normalized platform is representable by the closed acquisition-v2
    contract is decided by that contract, not here.
    """

    require_nonempty(value, label="platform")
    match = _PLATFORM_RE.fullmatch(value.lower())
    if match is None:
        raise ValueError(f"platform {value!r} is not a Sentinel-2 unit label")
    return "S2" + match.group(1).upper()


def _require_2d_float_band(name: str, array: Any, *, scene_id: str) -> np.ndarray:
    if isinstance(array, np.ma.MaskedArray):
        raise ValueError(
            f"band {name!r} of scene {scene_id} must not be a masked array; "
            "resolve nodata to NaN explicitly"
        )
    band = np.array(array, copy=True)
    if band.dtype.kind != "f":
        raise ValueError(
            f"band {name!r} of scene {scene_id} must be floating point so "
            "nodata is representable as NaN"
        )
    if band.ndim != 2:
        raise ValueError(
            f"band {name!r} of scene {scene_id} must be a 2-D grid"
        )
    band.setflags(write=False)
    return band


@dataclass(frozen=True)
class SceneInputV2:
    """One provider-native scene: metadata, SCL grid, and aligned bands."""

    scene_id: str
    platform: str
    provider_platform: str
    datatake_id: str
    properties: Mapping[str, Any]
    scl: np.ndarray
    bands: Mapping[str, np.ndarray]


def create_scene_input_v2(
    *,
    scene_id: str,
    platform: str,
    datatake_id: str,
    properties: Mapping[str, Any],
    scl: Any,
    bands: Mapping[str, Any],
) -> SceneInputV2:
    scene_id = require_nonempty(scene_id, label="scene_id")
    normalized_platform = normalize_platform(platform)
    datatake_id = require_nonempty(datatake_id, label="datatake_id")
    datatake_platform = _DATATAKE_PLATFORM_RE.match(datatake_id)
    if datatake_platform is not None:
        embedded = "S2" + datatake_platform.group(1)
        if embedded != normalized_platform:
            raise ValueError(
                f"scene {scene_id} claims platform {normalized_platform} but "
                f"its datatake_id embeds {embedded}"
            )
    if not isinstance(properties, Mapping):
        raise TypeError(f"scene {scene_id} properties must be a mapping")
    if scl is None:
        # Preserve the fail-closed missing-SCL path for the mask evaluator.
        scl_array: Any = None
    elif isinstance(scl, np.ma.MaskedArray):
        raise ValueError(
            f"SCL of scene {scene_id} must not be a masked array; resolve "
            "nodata explicitly before the fail-closed allowlist"
        )
    else:
        scl_array = np.array(scl, copy=True)
        scl_array.setflags(write=False)
    if not isinstance(bands, Mapping) or not bands:
        raise ValueError(f"scene {scene_id} must supply at least one band")
    validated_bands: dict[str, np.ndarray] = {}
    for name in sorted(bands, key=lambda item: item.encode("utf-8")):
        require_nonempty(name, label="band name")
        band = _require_2d_float_band(name, bands[name], scene_id=scene_id)
        if scl_array is not None and band.shape != scl_array.shape:
            raise ValueError(
                f"band {name!r} of scene {scene_id} does not match the SCL "
                "grid shape"
            )
        validated_bands[name] = band
    return SceneInputV2(
        scene_id=scene_id,
        platform=normalized_platform,
        provider_platform=platform,
        datatake_id=datatake_id,
        properties=properties,
        scl=scl_array,
        bands=MappingProxyType(validated_bands),
    )


@dataclass(frozen=True)
class DatatakeGroupV2:
    """All supplied scenes of exactly one physical (platform, datatake)."""

    platform: str
    datatake_id: str
    scenes: tuple[SceneInputV2, ...]

    @property
    def scene_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                (scene.scene_id for scene in self.scenes),
                key=lambda item: item.encode("utf-8"),
            )
        )


def group_scenes_by_datatake(
    scenes: Iterable[SceneInputV2],
) -> tuple[DatatakeGroupV2, ...]:
    """Partition scenes strictly by physical (platform, datatake) key.

    Groups are never merged: two datatakes on the same UTC date remain two
    groups and therefore two independent compositions.
    """

    items = tuple(scenes)
    if not items:
        raise ValueError("at least one scene is required")
    seen_scene_ids: set[str] = set()
    grouped: dict[tuple[str, str], list[SceneInputV2]] = {}
    for scene in items:
        if not isinstance(scene, SceneInputV2):
            raise TypeError("scenes must be SceneInputV2 records")
        if scene.scene_id in seen_scene_ids:
            raise ValueError(f"duplicate scene_id {scene.scene_id!r}")
        seen_scene_ids.add(scene.scene_id)
        grouped.setdefault((scene.platform, scene.datatake_id), []).append(scene)
    return tuple(
        DatatakeGroupV2(
            platform=platform,
            datatake_id=datatake_id,
            scenes=tuple(members),
        )
        for (platform, datatake_id), members in sorted(
            grouped.items(),
            key=lambda item: (
                item[0][0].encode("utf-8"),
                item[0][1].encode("utf-8"),
            ),
        )
    )


def _array_digest(array: np.ndarray) -> dict[str, Any]:
    contiguous = np.ascontiguousarray(array)
    return {
        "dtype": str(contiguous.dtype),
        "shape": list(contiguous.shape),
        "sha256": hashlib.sha256(contiguous.tobytes()).hexdigest(),
    }


@dataclass(frozen=True)
class DatatakeCompositeV2:
    """Deterministic first-valid composite of one physical datatake."""

    platform: str
    datatake_id: str
    band_names: tuple[str, ...]
    composition_order_scene_ids: tuple[str, ...]
    scene_masks: tuple[SceneSclMaskV2, ...]
    scene_valid_pixel_counts: Mapping[str, int]
    scene_accepted_but_nonfinite_counts: Mapping[str, int]
    composed_bands: Mapping[str, np.ndarray]
    contributor_scene_index_map: np.ndarray
    chosen_scl: np.ndarray
    contributor_pixel_counts: Mapping[str, int]
    total_pixel_count: int
    composed_pixel_count: int
    uncomposed_pixel_count: int
    scl7_composed_pixel_count: int
    scl7_fraction_of_composed: float | None
    observed_processing_baselines: tuple[str, ...]
    reviewed_baseline_registry: Mapping[str, Any]
    evidence: Mapping[str, Any]
    composition_evidence_sha256: str


def compose_datatake(
    group: DatatakeGroupV2,
    *,
    reviewed_baselines: Iterable[str] = REVIEWED_PROCESSING_BASELINES,
) -> DatatakeCompositeV2:
    """Compose one datatake with explicit coverage-ranked first-valid order.

    Fails closed (propagating the typed ``scl_mask_v2`` errors) when any
    scene's SCL or processing-baseline metadata is missing, unexpected, or
    unreviewed.  Never accepts scenes from more than one datatake.
    """

    if not isinstance(group, DatatakeGroupV2):
        raise TypeError("compose_datatake requires a DatatakeGroupV2")
    if not group.scenes:
        raise ValueError("datatake group has no scenes")
    for scene in group.scenes:
        if (scene.platform, scene.datatake_id) != (
            group.platform,
            group.datatake_id,
        ):
            raise ValueError(
                "different datatakes are never composed: scene "
                f"{scene.scene_id} belongs to another physical datatake"
            )

    # Every structural and metadata gate below runs in UTF-8 scene-id order
    # so a multi-failure datatake always fails closed with the same first
    # error regardless of the input permutation; an order-dependent reason
    # would break byte-identical terminal-row retries.
    gate_ordered_scenes = tuple(
        sorted(group.scenes, key=lambda item: item.scene_id.encode("utf-8"))
    )
    reference_scene = gate_ordered_scenes[0]
    band_names = tuple(
        sorted(reference_scene.bands, key=lambda item: item.encode("utf-8"))
    )
    shape: tuple[int, ...] | None = None
    band_dtypes = {
        name: reference_scene.bands[name].dtype for name in band_names
    }
    for scene in gate_ordered_scenes:
        scene_bands = tuple(
            sorted(scene.bands, key=lambda item: item.encode("utf-8"))
        )
        if scene_bands != band_names:
            raise ValueError(
                f"scene {scene.scene_id} band set differs from the datatake "
                "band set; all bands must come from one scene per pixel"
            )
        for name in band_names:
            if scene.bands[name].dtype != band_dtypes[name]:
                raise ValueError(
                    f"band {name!r} dtype differs across scenes of datatake "
                    f"{group.datatake_id}; a composite cannot silently mix "
                    "precisions"
                )

    reviewed = tuple(reviewed_baselines)

    # Metadata pre-pass over every scene: read each baseline before raising,
    # so a fail-closed datatake still enumerates every readable observed
    # baseline (not only the first failure's value).
    observed_values: set[str] = set()
    first_gate_error: SclMaskUnavailableError | None = None
    for scene in gate_ordered_scenes:
        try:
            baseline = read_processing_baseline(
                scene.properties, scene_id=scene.scene_id
            )
            observed_values.add(baseline.normalized_value)
            require_datatake_baseline_consistency(
                scene.datatake_id, baseline, scene_id=scene.scene_id
            )
            require_reviewed_processing_baseline(
                baseline, reviewed, scene_id=scene.scene_id
            )
        except SclMaskUnavailableError as exc:
            if exc.observed_baseline is not None:
                observed_values.add(exc.observed_baseline)
            if first_gate_error is None:
                first_gate_error = exc
    if first_gate_error is not None:
        first_gate_error.observed_baselines = tuple(sorted(observed_values))
        raise first_gate_error

    masks: dict[str, SceneSclMaskV2] = {}
    valid_masks: dict[str, np.ndarray] = {}
    valid_counts: dict[str, int] = {}
    nonfinite_counts: dict[str, int] = {}
    for scene in gate_ordered_scenes:
        try:
            mask = compute_scene_scl_mask(
                scene.scl,
                properties=scene.properties,
                scene_id=scene.scene_id,
                datatake_id=scene.datatake_id,
                reviewed_baselines=reviewed,
            )
        except SclMaskUnavailableError as exc:
            exc.observed_baselines = tuple(sorted(observed_values))
            raise
        if shape is None:
            shape = mask.accepted_mask.shape
        if mask.accepted_mask.shape != shape:
            raise ValueError(
                f"scene {scene.scene_id} grid shape differs from the "
                "datatake composition grid"
            )
        finite = np.logical_and.reduce(
            [np.isfinite(scene.bands[name]) for name in band_names]
        )
        valid = mask.accepted_mask & finite
        masks[scene.scene_id] = mask
        valid_masks[scene.scene_id] = valid
        valid_counts[scene.scene_id] = int(valid.sum())
        nonfinite_counts[scene.scene_id] = int(
            (mask.accepted_mask & ~finite).sum()
        )

    order = tuple(
        scene.scene_id
        for scene in sorted(
            group.scenes,
            key=lambda scene: (
                -valid_counts[scene.scene_id],
                scene.scene_id.encode("utf-8"),
            ),
        )
    )
    scenes_by_id = {scene.scene_id: scene for scene in group.scenes}

    assert shape is not None
    contributor = np.full(shape, NO_CONTRIBUTION_SENTINEL, dtype=np.int32)
    chosen_scl = np.full(shape, NO_CONTRIBUTION_SENTINEL, dtype=np.int16)
    composed_bands = {
        name: np.full(shape, np.nan, dtype=band_dtypes[name])
        for name in band_names
    }
    for rank, scene_id in enumerate(order):
        takes = valid_masks[scene_id] & (contributor == NO_CONTRIBUTION_SENTINEL)
        if not takes.any():
            continue
        contributor[takes] = rank
        chosen_scl[takes] = scenes_by_id[scene_id].scl[takes].astype(np.int16)
        for name in band_names:
            composed_bands[name][takes] = scenes_by_id[scene_id].bands[name][
                takes
            ]
    contributor.setflags(write=False)
    chosen_scl.setflags(write=False)
    for name in band_names:
        composed_bands[name].setflags(write=False)

    contributor_pixel_counts = {
        scene_id: int((contributor == rank).sum())
        for rank, scene_id in enumerate(order)
    }
    total_pixel_count = int(contributor.size)
    composed_pixel_count = int((contributor != NO_CONTRIBUTION_SENTINEL).sum())
    uncomposed_pixel_count = total_pixel_count - composed_pixel_count
    scl7_composed = int((chosen_scl == 7).sum())
    scl7_fraction = (
        scl7_composed / composed_pixel_count if composed_pixel_count else None
    )
    observed_baselines = enumerate_observed_baselines(masks.values())
    registry = reviewed_baseline_registry_dict(reviewed)

    ordered_masks = tuple(masks[scene_id] for scene_id in order)
    evidence_body: dict[str, Any] = {
        "composition_evidence_version": COMPOSITION_EVIDENCE_VERSION,
        "composite_method_id": COMPOSITION_METHOD_ID,
        "composition_scope_version": COMPOSITION_SCOPE_VERSION,
        "scl_mask_method_id": SCL_MASK_METHOD_ID,
        "platform": group.platform,
        "datatake_id": group.datatake_id,
        "grid_shape": list(shape),
        "band_names": list(band_names),
        "scene_order_policy": list(SCENE_ORDER_POLICY),
        "pixel_selection": PIXEL_SELECTION_POLICY,
        "all_bands_for_pixel_from_same_scene": True,
        "band_finite_intersection_applied": True,
        "different_datatakes_never_composed": True,
        "composition_order_scene_ids": list(order),
        "scenes": [
            {
                **masks[scene_id].qa_dict(),
                "valid_pixel_count": valid_counts[scene_id],
                "accepted_but_nonfinite_band_pixel_count": nonfinite_counts[
                    scene_id
                ],
            }
            for scene_id in order
        ],
        "contributor_pixel_counts": {
            scene_id: contributor_pixel_counts[scene_id] for scene_id in order
        },
        "total_pixel_count": total_pixel_count,
        "composed_pixel_count": composed_pixel_count,
        "uncomposed_pixel_count": uncomposed_pixel_count,
        "scl7_composite": {
            "composed_scl7_pixel_count": scl7_composed,
            "fraction_of_composed": scl7_fraction,
            **dict(SCL7_QA_POLICY),
        },
        "observed_processing_baselines": list(observed_baselines),
        "reviewed_processing_baseline_registry": registry,
        "arrays": {
            "contributor_scene_index_map": {
                **_array_digest(contributor),
                "no_contribution_sentinel": NO_CONTRIBUTION_SENTINEL,
                "index_space": "composition_order_scene_ids",
            },
            "chosen_scl": _array_digest(chosen_scl),
            "bands": {
                name: _array_digest(composed_bands[name]) for name in band_names
            },
        },
    }
    evidence_sha256 = canonical_sha256(evidence_body)
    evidence = {
        **evidence_body,
        "composition_evidence_sha256": evidence_sha256,
    }

    return DatatakeCompositeV2(
        platform=group.platform,
        datatake_id=group.datatake_id,
        band_names=band_names,
        composition_order_scene_ids=order,
        scene_masks=ordered_masks,
        scene_valid_pixel_counts=MappingProxyType(dict(valid_counts)),
        scene_accepted_but_nonfinite_counts=MappingProxyType(
            dict(nonfinite_counts)
        ),
        composed_bands=MappingProxyType(composed_bands),
        contributor_scene_index_map=contributor,
        chosen_scl=chosen_scl,
        contributor_pixel_counts=MappingProxyType(contributor_pixel_counts),
        total_pixel_count=total_pixel_count,
        composed_pixel_count=composed_pixel_count,
        uncomposed_pixel_count=uncomposed_pixel_count,
        scl7_composed_pixel_count=scl7_composed,
        scl7_fraction_of_composed=scl7_fraction,
        observed_processing_baselines=observed_baselines,
        reviewed_baseline_registry=MappingProxyType(registry),
        evidence=MappingProxyType(evidence),
        composition_evidence_sha256=evidence_sha256,
    )


def compose_grouped_scenes(
    scenes: Iterable[SceneInputV2],
    *,
    reviewed_baselines: Iterable[str] = REVIEWED_PROCESSING_BASELINES,
) -> tuple[DatatakeCompositeV2, ...]:
    """Compose every physical datatake independently, never across groups."""

    return tuple(
        compose_datatake(group, reviewed_baselines=reviewed_baselines)
        for group in group_scenes_by_datatake(scenes)
    )
