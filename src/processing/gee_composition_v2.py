"""Explicit GEE-equivalent path for ``coverage-ranked-first-valid-v1``.

Earth Engine's ``ImageCollection.mosaic()`` keeps the LAST image whose mask is
valid at a pixel, so an implicit collection order silently changes the
composite.  This module makes the order explicit and provable without a live
Earth Engine connection:

- :func:`build_gee_composition_plan` derives, from a local reference
  composite, the deterministic plan a GEE run must follow: the scientific
  first-valid preference order, the reversed ``mosaic_input_order`` (worst to
  best, so the most-preferred scene paints last), the single shared per-image
  mask rule that keeps every band of a pixel from one scene, and the expected
  per-scene valid-pixel counts;
- :func:`execute_gee_plan_locally` emulates the plan with mosaic paint-over
  semantics (last valid wins), recomputing masks from the raw scenes — a
  deliberately different algorithm from the local first-take reference; and
- :func:`assert_local_gee_parity` proves byte-identical bands, contributor
  accounting, and counts between the two paths.

A live GEE run must reproduce ``gee_plan_sha256`` and the expected counts
before its output may be compared; that live execution belongs to a later
package, not 2A.6B.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

import numpy as np

from src.detection.identity import canonical_sha256
from src.detection.identity_v2 import require_nonempty
from src.processing.composition_v2 import (
    COMPOSITION_METHOD_ID,
    COMPOSITION_SCOPE_VERSION,
    NO_CONTRIBUTION_SENTINEL,
    DatatakeCompositeV2,
    SceneInputV2,
)
from src.processing.scl_mask_v2 import (
    REVIEWED_PROCESSING_BASELINES,
    SCL_ACCEPTED_CLASSES,
    SCL_MASK_METHOD_ID,
    compute_scene_scl_mask,
)


GEE_PLAN_VERSION = "gee-coverage-ranked-first-valid-plan-v1"
GEE_MOSAIC_SEMANTICS = "last_valid_image_on_top"


class GeeParityError(RuntimeError):
    """The GEE-equivalent execution does not reproduce the local composite."""


def build_gee_composition_plan(
    composite: DatatakeCompositeV2, *, image_collection_id: str
) -> dict[str, Any]:
    """Derive the explicit, self-checking GEE execution plan."""

    require_nonempty(image_collection_id, label="image_collection_id")
    first_valid_order = list(composite.composition_order_scene_ids)
    mosaic_input_order = list(reversed(first_valid_order))
    body: dict[str, Any] = {
        "gee_plan_version": GEE_PLAN_VERSION,
        "composite_method_id": COMPOSITION_METHOD_ID,
        "composition_scope_version": COMPOSITION_SCOPE_VERSION,
        "scl_mask_method_id": SCL_MASK_METHOD_ID,
        "image_collection_id": image_collection_id,
        "platform": composite.platform,
        "datatake_id": composite.datatake_id,
        "band_names": list(composite.band_names),
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
            scene_id: composite.scene_valid_pixel_counts[scene_id]
            for scene_id in first_valid_order
        },
        "contributor_accounting": {
            "per_image_constant_band": "contributor_rank",
            "rank_source": "index_into_first_valid_order",
            "no_contribution_sentinel": NO_CONTRIBUTION_SENTINEL,
        },
        "observed_processing_baselines": list(
            composite.observed_processing_baselines
        ),
        "composition_evidence_sha256": composite.composition_evidence_sha256,
    }
    return {**body, "gee_plan_sha256": canonical_sha256(body)}


@dataclass(frozen=True)
class GeeLocalMosaicResult:
    """Mosaic-semantics execution of a plan against the raw scenes."""

    gee_plan_sha256: str
    band_names: tuple[str, ...]
    composed_bands: Mapping[str, np.ndarray]
    contributor_scene_index_map: np.ndarray
    chosen_scl: np.ndarray
    contributor_pixel_counts: Mapping[str, int]
    composed_pixel_count: int
    scl7_composed_pixel_count: int


def execute_gee_plan_locally(
    plan: Mapping[str, Any],
    scenes: Iterable[SceneInputV2],
    *,
    reviewed_baselines: Iterable[str] = REVIEWED_PROCESSING_BASELINES,
) -> GeeLocalMosaicResult:
    """Execute the plan with paint-over (last valid wins) mosaic semantics.

    Masks and valid-pixel counts are recomputed from the raw scenes; a count
    that disagrees with the plan's expectation fails closed, exactly as a
    live GEE run must before its mosaic may be trusted.
    """

    if plan.get("gee_plan_version") != GEE_PLAN_VERSION:
        raise GeeParityError("plan version is not the supported v1 plan")
    expected_body = {
        key: value for key, value in plan.items() if key != "gee_plan_sha256"
    }
    if plan.get("gee_plan_sha256") != canonical_sha256(expected_body):
        raise GeeParityError("plan checksum does not match its contents")
    # The declarative fields are the instruction sheet a future live GEE run
    # follows; a plan that names another mask or method must not pass simply
    # because the local executor recomputes with the fixed policy.
    if (
        plan.get("composite_method_id") != COMPOSITION_METHOD_ID
        or plan.get("composition_scope_version") != COMPOSITION_SCOPE_VERSION
        or plan.get("scl_mask_method_id") != SCL_MASK_METHOD_ID
        or plan.get("mosaic_semantics") != GEE_MOSAIC_SEMANTICS
    ):
        raise GeeParityError("plan declares a different method or semantics")
    mask_block = plan.get("mask") or {}
    if (
        mask_block.get("scl_band") != "SCL"
        or mask_block.get("accepted_scl_classes") != list(SCL_ACCEPTED_CLASSES)
        or mask_block.get("band_mask_intersection_required") is not True
        or mask_block.get("single_shared_mask_per_image") is not True
    ):
        raise GeeParityError(
            "plan mask block differs from scl-explicit-allowlist-v2"
        )

    scenes_by_id = {scene.scene_id: scene for scene in scenes}
    plan_scene_ids = list(plan["mosaic_input_order"])
    if sorted(plan_scene_ids) != sorted(plan["first_valid_order"]):
        raise GeeParityError(
            "mosaic_input_order and first_valid_order name different scenes"
        )
    if list(reversed(plan_scene_ids)) != list(plan["first_valid_order"]):
        raise GeeParityError(
            "mosaic_input_order must be the exact reverse of first_valid_order"
        )
    if sorted(scenes_by_id) != sorted(plan_scene_ids):
        raise GeeParityError(
            "supplied scenes do not match the plan's scene set"
        )

    band_names = tuple(plan["band_names"])
    first_valid_rank = {
        scene_id: rank for rank, scene_id in enumerate(plan["first_valid_order"])
    }
    reviewed = tuple(reviewed_baselines)

    # First pass: recompute every mask and valid count from the raw scenes,
    # exactly as a live GEE run must reconcile before its mosaic is trusted.
    shape: tuple[int, ...] | None = None
    valid_by_scene: dict[str, np.ndarray] = {}
    recomputed_counts: dict[str, int] = {}
    for scene_id in plan_scene_ids:
        scene = scenes_by_id[scene_id]
        mask = compute_scene_scl_mask(
            scene.scl,
            properties=scene.properties,
            scene_id=scene.scene_id,
            datatake_id=scene.datatake_id,
            reviewed_baselines=reviewed,
        )
        finite = np.logical_and.reduce(
            [np.isfinite(scene.bands[name]) for name in band_names]
        )
        valid = mask.accepted_mask & finite
        if shape is None:
            shape = valid.shape
        elif valid.shape != shape:
            raise GeeParityError(
                f"scene {scene_id} grid shape differs from the plan's grid"
            )
        recomputed_count = int(valid.sum())
        expected_count = plan["expected_scene_valid_pixel_counts"][scene_id]
        if recomputed_count != expected_count:
            raise GeeParityError(
                f"scene {scene_id} recomputed valid_pixel_count "
                f"{recomputed_count} differs from the plan's {expected_count}"
            )
        valid_by_scene[scene_id] = valid
        recomputed_counts[scene_id] = recomputed_count
    policy_order = sorted(
        plan_scene_ids,
        key=lambda scene_id: (
            -recomputed_counts[scene_id],
            scene_id.encode("utf-8"),
        ),
    )
    if list(plan["first_valid_order"]) != policy_order:
        raise GeeParityError(
            "plan first_valid_order is not the coverage-ranked policy order "
            "derived from the recomputed valid counts"
        )

    assert shape is not None
    contributor = np.full(shape, NO_CONTRIBUTION_SENTINEL, dtype=np.int32)
    chosen_scl = np.full(shape, NO_CONTRIBUTION_SENTINEL, dtype=np.int16)
    composed = {
        name: np.full(
            shape, np.nan, dtype=scenes_by_id[plan_scene_ids[0]].bands[name].dtype
        )
        for name in band_names
    }
    for scene_id in plan_scene_ids:
        scene = scenes_by_id[scene_id]
        valid = valid_by_scene[scene_id]
        # Paint-over: a later (more preferred) valid scene overwrites earlier
        # values, emulating mosaic()'s last-on-top rule.
        contributor[valid] = first_valid_rank[scene_id]
        chosen_scl[valid] = scene.scl[valid].astype(np.int16)
        for name in band_names:
            composed[name][valid] = scene.bands[name][valid]

    contributor.setflags(write=False)
    chosen_scl.setflags(write=False)
    for name in band_names:
        composed[name].setflags(write=False)
    contributor_pixel_counts = {
        scene_id: int((contributor == first_valid_rank[scene_id]).sum())
        for scene_id in plan["first_valid_order"]
    }
    return GeeLocalMosaicResult(
        gee_plan_sha256=plan["gee_plan_sha256"],
        band_names=band_names,
        composed_bands=MappingProxyType(composed),
        contributor_scene_index_map=contributor,
        chosen_scl=chosen_scl,
        contributor_pixel_counts=MappingProxyType(contributor_pixel_counts),
        composed_pixel_count=int(
            (contributor != NO_CONTRIBUTION_SENTINEL).sum()
        ),
        scl7_composed_pixel_count=int((chosen_scl == 7).sum()),
    )


def _bytes_identical(left: np.ndarray, right: np.ndarray) -> bool:
    return (
        left.dtype == right.dtype
        and left.shape == right.shape
        and np.ascontiguousarray(left).tobytes()
        == np.ascontiguousarray(right).tobytes()
    )


def assert_local_gee_parity(
    composite: DatatakeCompositeV2, result: GeeLocalMosaicResult
) -> dict[str, Any]:
    """Prove the two paths byte-identical and return the parity evidence."""

    if tuple(result.band_names) != composite.band_names:
        raise GeeParityError("band sets differ between the two paths")
    if not _bytes_identical(
        composite.contributor_scene_index_map,
        result.contributor_scene_index_map,
    ):
        raise GeeParityError("contributor maps differ between the two paths")
    if not _bytes_identical(composite.chosen_scl, result.chosen_scl):
        raise GeeParityError("chosen SCL grids differ between the two paths")
    for name in composite.band_names:
        if not _bytes_identical(
            composite.composed_bands[name], result.composed_bands[name]
        ):
            raise GeeParityError(
                f"band {name!r} differs between the two paths"
            )
    if dict(result.contributor_pixel_counts) != dict(
        composite.contributor_pixel_counts
    ):
        raise GeeParityError("contributor counts differ between the two paths")
    if result.composed_pixel_count != composite.composed_pixel_count:
        raise GeeParityError("composed pixel counts differ between the paths")
    if result.scl7_composed_pixel_count != composite.scl7_composed_pixel_count:
        raise GeeParityError("SCL 7 accounting differs between the two paths")
    body = {
        "parity_check_version": "phase2a6b-local-gee-parity-v1",
        "parity": True,
        "gee_plan_sha256": result.gee_plan_sha256,
        "composition_evidence_sha256": composite.composition_evidence_sha256,
        "compared": {
            "bands": list(composite.band_names),
            "contributor_scene_index_map": True,
            "chosen_scl": True,
            "contributor_pixel_counts": True,
            "composed_pixel_count": composite.composed_pixel_count,
            "scl7_composed_pixel_count": composite.scl7_composed_pixel_count,
            "comparison": "byte_identical_arrays",
        },
    }
    return {**body, "parity_evidence_sha256": canonical_sha256(body)}
