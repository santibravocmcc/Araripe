"""Focused Package 2A.6B tests for the explicit GEE-equivalent path."""

import itertools

import numpy as np
import pytest

from src.detection.identity import canonical_sha256
from src.processing.composition_v2 import (
    compose_datatake,
    create_scene_input_v2,
    group_scenes_by_datatake,
)
from src.processing.gee_composition_v2 import (
    GEE_MOSAIC_SEMANTICS,
    GEE_PLAN_VERSION,
    GeeParityError,
    assert_local_gee_parity,
    build_gee_composition_plan,
    execute_gee_plan_locally,
)


COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"
DATATAKE = "GS2B_20260407T132251_041247_N05.12"


def _scene(scene_id, scl_rows, *, value_base, band_overrides=None):
    scl = np.asarray(scl_rows, dtype=np.uint8)
    bands = {}
    for offset, name in enumerate(("B08", "B12")):
        grid = (
            float(value_base)
            + 1000.0 * offset
            + np.arange(scl.size, dtype=np.float64).reshape(scl.shape)
        )
        bands[name] = grid
    if band_overrides:
        for (name, row, column), value in band_overrides.items():
            bands[name] = bands[name].copy()
            bands[name][row, column] = value
    return create_scene_input_v2(
        scene_id=scene_id,
        platform="sentinel-2b",
        datatake_id=DATATAKE,
        properties={"s2:processing_baseline": "05.12"},
        scl=scl,
        bands=bands,
    )


def _fixture_scenes():
    return [
        _scene(
            "S2B_PAR_A",
            [[4, 4, 8, 8], [5, 5, 8, 8], [6, 6, 9, 9], [0, 0, 0, 0]],
            value_base=100.0,
            band_overrides={("B12", 0, 0): np.nan},
        ),
        _scene(
            "S2B_PAR_B",
            [[8, 8, 8, 4], [8, 8, 8, 4], [9, 9, 9, 4], [3, 3, 3, 4]],
            value_base=200.0,
        ),
        _scene(
            "S2B_PAR_C",
            [[7, 7, 4, 4], [4, 4, 4, 4], [8, 8, 4, 4], [9, 9, 4, 4]],
            value_base=300.0,
        ),
    ]


def _composite(scenes):
    return compose_datatake(group_scenes_by_datatake(scenes)[0])


class TestPlan:
    def test_plan_makes_the_mosaic_order_explicit_and_reversed(self):
        composite = _composite(_fixture_scenes())
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        assert plan["gee_plan_version"] == GEE_PLAN_VERSION
        assert plan["mosaic_semantics"] == GEE_MOSAIC_SEMANTICS
        assert plan["first_valid_order"] == list(
            composite.composition_order_scene_ids
        )
        assert plan["mosaic_input_order"] == list(
            reversed(composite.composition_order_scene_ids)
        )
        assert plan["mask"]["accepted_scl_classes"] == [4, 5, 6, 7]
        assert plan["mask"]["single_shared_mask_per_image"] is True
        assert plan["expected_scene_valid_pixel_counts"] == dict(
            composite.scene_valid_pixel_counts
        )
        assert (
            plan["composition_evidence_sha256"]
            == composite.composition_evidence_sha256
        )

    def test_plan_is_deterministic_and_self_checksummed(self):
        scenes = _fixture_scenes()
        first = build_gee_composition_plan(
            _composite(scenes), image_collection_id=COLLECTION_ID
        )
        second = build_gee_composition_plan(
            _composite(scenes), image_collection_id=COLLECTION_ID
        )
        assert first == second
        body = {
            key: value
            for key, value in first.items()
            if key != "gee_plan_sha256"
        }
        assert first["gee_plan_sha256"] == canonical_sha256(body)


class TestLocalGeeExecution:
    def test_parity_on_the_reference_fixture(self):
        scenes = _fixture_scenes()
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        result = execute_gee_plan_locally(plan, scenes)
        evidence = assert_local_gee_parity(composite, result)
        assert evidence["parity"] is True
        assert evidence["gee_plan_sha256"] == plan["gee_plan_sha256"]
        assert (
            evidence["composition_evidence_sha256"]
            == composite.composition_evidence_sha256
        )

    def test_parity_holds_for_every_input_permutation(self):
        scenes = _fixture_scenes()
        reference_sha = None
        for permutation in itertools.permutations(scenes):
            composite = _composite(list(permutation))
            plan = build_gee_composition_plan(
                composite, image_collection_id=COLLECTION_ID
            )
            result = execute_gee_plan_locally(plan, list(permutation))
            evidence = assert_local_gee_parity(composite, result)
            if reference_sha is None:
                reference_sha = evidence["parity_evidence_sha256"]
            assert evidence["parity_evidence_sha256"] == reference_sha

    def test_parity_holds_for_coverage_ties(self):
        scenes = [
            _scene("S2B_TIE_A", [[4, 8]], value_base=10.0),
            _scene("S2B_TIE_B", [[4, 8]], value_base=20.0),
        ]
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        result = execute_gee_plan_locally(plan, scenes)
        assert assert_local_gee_parity(composite, result)["parity"] is True
        assert composite.composed_bands["B08"][0, 0] == 10.0

    def test_parity_holds_for_zero_valid_composites(self):
        scenes = [
            _scene("S2B_ZERO_A", [[9, 9]], value_base=1.0),
            _scene("S2B_ZERO_B", [[8, 10]], value_base=2.0),
        ]
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        result = execute_gee_plan_locally(plan, scenes)
        assert assert_local_gee_parity(composite, result)["parity"] is True
        assert result.composed_pixel_count == 0

    def test_execution_is_repeatable_byte_exact(self):
        scenes = _fixture_scenes()
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        first = execute_gee_plan_locally(plan, scenes)
        second = execute_gee_plan_locally(plan, scenes)
        assert (
            first.contributor_scene_index_map.tobytes()
            == second.contributor_scene_index_map.tobytes()
        )
        for name in first.band_names:
            assert (
                first.composed_bands[name].tobytes()
                == second.composed_bands[name].tobytes()
            )


class TestFailClosedParity:
    def test_mosaic_order_genuinely_changes_the_output(self):
        # Painting in a non-policy order really produces different bytes, so
        # an implicit GEE collection order is a real seam risk...
        scenes = _fixture_scenes()
        composite = _composite(scenes)
        wrong_order = list(reversed(composite.composition_order_scene_ids))
        by_id = {scene.scene_id: scene for scene in scenes}
        painted = np.full(composite.chosen_scl.shape, np.nan, dtype=np.float64)
        for scene_id in reversed(wrong_order):  # mosaic: last on top
            scene = by_id[scene_id]
            valid = np.isin(scene.scl, (4, 5, 6, 7))
            for band in scene.bands.values():
                valid &= np.isfinite(band)
            painted[valid] = scene.bands["B08"][valid]
        assert not np.array_equal(
            painted, composite.composed_bands["B08"], equal_nan=True
        )

    def test_wrongly_ordered_plan_is_rejected_at_execution(self):
        # ...and a well-formed but wrongly ordered plan must fail closed at
        # execution: first_valid_order must equal the coverage-ranked policy
        # order derived from the recomputed counts.
        scenes = _fixture_scenes()
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        tampered_body = {
            key: value
            for key, value in plan.items()
            if key != "gee_plan_sha256"
        }
        swapped = list(reversed(plan["first_valid_order"]))
        tampered_body["first_valid_order"] = swapped
        tampered_body["mosaic_input_order"] = list(reversed(swapped))
        tampered = {
            **tampered_body,
            "gee_plan_sha256": canonical_sha256(tampered_body),
        }
        with pytest.raises(GeeParityError, match="policy order"):
            execute_gee_plan_locally(tampered, scenes)

    def test_inert_reorder_of_tied_scenes_is_rejected(self):
        # Swapping scenes that contribute nothing is still a policy-order
        # violation; the attested instruction sheet must not drift silently.
        scenes = [
            _scene("S2B_ZERO_A", [[9, 9]], value_base=1.0),
            _scene("S2B_ZERO_B", [[8, 10]], value_base=2.0),
        ]
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        body = {
            key: value
            for key, value in plan.items()
            if key != "gee_plan_sha256"
        }
        body["first_valid_order"] = list(reversed(body["first_valid_order"]))
        body["mosaic_input_order"] = list(
            reversed(body["first_valid_order"])
        )
        tampered = {**body, "gee_plan_sha256": canonical_sha256(body)}
        with pytest.raises(GeeParityError, match="policy order"):
            execute_gee_plan_locally(tampered, scenes)

    def test_mask_block_tamper_is_rejected_even_when_inert(self):
        scenes = _fixture_scenes()
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        body = {
            key: value
            for key, value in plan.items()
            if key != "gee_plan_sha256"
        }
        body["mask"] = {**body["mask"], "accepted_scl_classes": [2, 11]}
        tampered = {**body, "gee_plan_sha256": canonical_sha256(body)}
        with pytest.raises(GeeParityError, match="mask block"):
            execute_gee_plan_locally(tampered, scenes)

    def test_scene_shape_drift_is_rejected_typed(self):
        scenes = [
            _scene("S2B_SHAPE_A", [[4, 8]], value_base=1.0),
            _scene("S2B_SHAPE_B", [[8, 4]], value_base=2.0),
        ]
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        reshaped = create_scene_input_v2(
            scene_id="S2B_SHAPE_B",
            platform="sentinel-2b",
            datatake_id=DATATAKE,
            properties={"s2:processing_baseline": "05.12"},
            scl=np.asarray([[8], [4]], dtype=np.uint8),
            bands={
                "B08": np.asarray([[2.0], [3.0]]),
                "B12": np.asarray([[1002.0], [1003.0]]),
            },
        )
        with pytest.raises(GeeParityError, match="grid shape"):
            execute_gee_plan_locally(plan, [scenes[0], reshaped])

    def test_plan_checksum_tamper_is_rejected(self):
        scenes = _fixture_scenes()
        composite = _composite(scenes)
        plan = dict(
            build_gee_composition_plan(
                composite, image_collection_id=COLLECTION_ID
            )
        )
        plan["image_collection_id"] = "SOMETHING/ELSE"
        with pytest.raises(GeeParityError, match="checksum"):
            execute_gee_plan_locally(plan, scenes)

    def test_non_reversed_mosaic_order_is_rejected(self):
        scenes = _fixture_scenes()
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        body = {
            key: value
            for key, value in plan.items()
            if key != "gee_plan_sha256"
        }
        body["mosaic_input_order"] = list(body["first_valid_order"])
        tampered = {**body, "gee_plan_sha256": canonical_sha256(body)}
        with pytest.raises(GeeParityError, match="reverse"):
            execute_gee_plan_locally(tampered, scenes)

    def test_scene_set_mismatch_is_rejected(self):
        scenes = _fixture_scenes()
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        with pytest.raises(GeeParityError, match="scene set"):
            execute_gee_plan_locally(plan, scenes[:2])

    def test_expected_count_drift_is_rejected(self):
        scenes = _fixture_scenes()
        composite = _composite(scenes)
        plan = build_gee_composition_plan(
            composite, image_collection_id=COLLECTION_ID
        )
        body = {
            key: value
            for key, value in plan.items()
            if key != "gee_plan_sha256"
        }
        counts = dict(body["expected_scene_valid_pixel_counts"])
        first_scene = body["first_valid_order"][0]
        counts[first_scene] = counts[first_scene] + 1
        body["expected_scene_valid_pixel_counts"] = counts
        tampered = {**body, "gee_plan_sha256": canonical_sha256(body)}
        with pytest.raises(GeeParityError, match="valid_pixel_count"):
            execute_gee_plan_locally(tampered, scenes)
