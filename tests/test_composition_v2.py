"""Focused Package 2A.6B tests for ``coverage-ranked-first-valid-v1``."""

import itertools
import json
from pathlib import Path

import numpy as np
import pytest

from src.processing.composition_v2 import (
    COMPOSITION_METHOD_ID,
    COMPOSITION_SCOPE_VERSION,
    NO_CONTRIBUTION_SENTINEL,
    PIXEL_SELECTION_POLICY,
    SCENE_ORDER_POLICY,
    compose_datatake,
    compose_grouped_scenes,
    create_scene_input_v2,
    group_scenes_by_datatake,
    normalize_platform,
)
from src.processing.scl_mask_v2 import (
    UnreviewedProcessingBaselineError,
    compute_scene_scl_mask,
)


ROOT = Path(__file__).resolve().parent.parent
DECISIONS = json.loads(
    (ROOT / "config" / "phase2a_candidate_generation_decisions_v2.json")
    .read_text(encoding="utf-8")
)
DATATAKE_B = "GS2B_20260407T132251_041247_N05.12"
DATATAKE_A = "GS2A_20260407T131241_055725_N05.12"


def _scene(
    scene_id,
    scl_rows,
    *,
    value_base,
    platform="sentinel-2b",
    datatake_id=DATATAKE_B,
    baseline="05.12",
    band_overrides=None,
    band_names=("B08", "B12"),
):
    scl = np.asarray(scl_rows, dtype=np.uint8)
    bands = {}
    for offset, name in enumerate(band_names):
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
        platform=platform,
        datatake_id=datatake_id,
        properties={"s2:processing_baseline": baseline},
        scl=scl,
        bands=bands,
    )


def _bruteforce_first_valid(scenes, reviewed=("05.11", "05.12")):
    """Independent per-pixel reference implementation of the decided method."""

    valids = {}
    counts = {}
    for scene in scenes:
        mask = compute_scene_scl_mask(
            scene.scl,
            properties=scene.properties,
            scene_id=scene.scene_id,
            datatake_id=scene.datatake_id,
            reviewed_baselines=reviewed,
        )
        finite = np.ones(scene.scl.shape, dtype=bool)
        for band in scene.bands.values():
            finite &= np.isfinite(band)
        valids[scene.scene_id] = mask.accepted_mask & finite
        counts[scene.scene_id] = int(valids[scene.scene_id].sum())
    order = sorted(
        (scene.scene_id for scene in scenes),
        key=lambda scene_id: (-counts[scene_id], scene_id.encode("utf-8")),
    )
    by_id = {scene.scene_id: scene for scene in scenes}
    shape = scenes[0].scl.shape
    band_names = sorted(scenes[0].bands, key=lambda item: item.encode("utf-8"))
    expected_bands = {
        name: np.full(shape, np.nan, dtype=np.float64) for name in band_names
    }
    expected_rank = np.full(shape, NO_CONTRIBUTION_SENTINEL, dtype=np.int32)
    for row in range(shape[0]):
        for column in range(shape[1]):
            for rank, scene_id in enumerate(order):
                if valids[scene_id][row, column]:
                    expected_rank[row, column] = rank
                    for name in band_names:
                        expected_bands[name][row, column] = by_id[
                            scene_id
                        ].bands[name][row, column]
                    break
    return order, expected_rank, expected_bands, counts


def _three_scene_fixture():
    # 4x4 grids. scene-c has the most valid pixels, then scene-a, then
    # scene-b; overlaps force genuine first-valid decisions.
    scene_a = _scene(
        "S2B_24MVT_20260407_0_A",
        [[4, 4, 8, 8], [5, 5, 8, 8], [6, 6, 9, 9], [0, 0, 0, 0]],
        value_base=100.0,
    )
    scene_b = _scene(
        "S2B_24MVT_20260407_0_B",
        [[8, 8, 8, 4], [8, 8, 8, 4], [9, 9, 9, 4], [3, 3, 3, 4]],
        value_base=200.0,
    )
    scene_c = _scene(
        "S2B_24MVT_20260407_0_C",
        [[7, 7, 4, 4], [4, 4, 4, 4], [8, 8, 4, 4], [9, 9, 4, 4]],
        value_base=300.0,
    )
    return [scene_a, scene_b, scene_c]


class TestDecisionRecordBinding:
    def test_method_tokens_match_the_accepted_decision_record(self):
        decided = DECISIONS["phase2a4"]["composition"]
        assert decided["selected_method"] == COMPOSITION_METHOD_ID
        assert decided["scope_version"] == COMPOSITION_SCOPE_VERSION
        assert decided["scene_order"] == list(SCENE_ORDER_POLICY)
        assert decided["pixel_selection"] == PIXEL_SELECTION_POLICY
        assert decided["all_bands_for_pixel_from_same_scene"] is True
        assert decided["different_datatakes_never_composed"] is True
        assert decided["contributor_map_and_counts_required"] is True


class TestPlatformNormalization:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("sentinel-2a", "S2A"),
            ("Sentinel-2B", "S2B"),
            ("sentinel-2c", "S2C"),
            ("S2A", "S2A"),
            ("s2d", "S2D"),
        ],
    )
    def test_mechanical_normalization(self, value, expected):
        assert normalize_platform(value) == expected

    @pytest.mark.parametrize("value", ["landsat-8", "sentinel-1a", "S2", ""])
    def test_non_sentinel2_labels_fail_closed(self, value):
        with pytest.raises(ValueError):
            normalize_platform(value)

    def test_scene_platform_must_match_datatake_prefix(self):
        with pytest.raises(ValueError, match="embeds"):
            _scene(
                "scene-mismatch",
                [[4]],
                value_base=1.0,
                platform="sentinel-2a",
                datatake_id=DATATAKE_B,
            )


class TestGrouping:
    def test_groups_are_strict_physical_partitions(self):
        scene_b = _scene("scene-b1", [[4]], value_base=1.0)
        scene_a = _scene(
            "scene-a1",
            [[4]],
            value_base=2.0,
            platform="sentinel-2a",
            datatake_id=DATATAKE_A,
        )
        groups = group_scenes_by_datatake([scene_b, scene_a])
        assert [(group.platform, group.datatake_id) for group in groups] == [
            ("S2A", DATATAKE_A),
            ("S2B", DATATAKE_B),
        ]

    def test_duplicate_scene_ids_fail_closed(self):
        scene = _scene("scene-dup", [[4]], value_base=1.0)
        with pytest.raises(ValueError, match="duplicate scene_id"):
            group_scenes_by_datatake([scene, scene])

    def test_mixed_group_is_never_composed(self):
        group = group_scenes_by_datatake(
            [_scene("scene-b1", [[4]], value_base=1.0)]
        )[0]
        foreign = _scene(
            "scene-a1",
            [[4]],
            value_base=2.0,
            platform="sentinel-2a",
            datatake_id=DATATAKE_A,
        )
        tampered = type(group)(
            platform=group.platform,
            datatake_id=group.datatake_id,
            scenes=group.scenes + (foreign,),
        )
        with pytest.raises(ValueError, match="never composed"):
            compose_datatake(tampered)


class TestFirstValidComposition:
    def test_matches_independent_bruteforce_reference(self):
        scenes = _three_scene_fixture()
        composite = compose_datatake(group_scenes_by_datatake(scenes)[0])
        order, expected_rank, expected_bands, counts = _bruteforce_first_valid(
            scenes
        )
        assert list(composite.composition_order_scene_ids) == order
        assert composite.scene_valid_pixel_counts == counts
        np.testing.assert_array_equal(
            composite.contributor_scene_index_map, expected_rank
        )
        for name in composite.band_names:
            np.testing.assert_array_equal(
                composite.composed_bands[name], expected_bands[name]
            )

    def test_order_is_coverage_desc_then_scene_id_utf8_asc(self):
        scenes = _three_scene_fixture()
        composite = compose_datatake(group_scenes_by_datatake(scenes)[0])
        counts = composite.scene_valid_pixel_counts
        ordered = list(composite.composition_order_scene_ids)
        assert ordered == sorted(
            counts, key=lambda sid: (-counts[sid], sid.encode("utf-8"))
        )
        assert counts[ordered[0]] == max(counts.values())

    def test_utf8_tie_break_uses_byte_order(self):
        # Equal valid counts; "S2B_..._Z" (ASCII Z, 0x5a) sorts before
        # "S2B_..._á" (UTF-8 0xc3a1) even though "á" < "Z" in many locales.
        scene_z = _scene("S2B_TIE_Z", [[4, 8]], value_base=10.0)
        scene_accent = _scene("S2B_TIE_á", [[4, 8]], value_base=20.0)
        composite = compose_datatake(
            group_scenes_by_datatake([scene_accent, scene_z])[0]
        )
        assert composite.composition_order_scene_ids == (
            "S2B_TIE_Z",
            "S2B_TIE_á",
        )
        # The tie winner contributes the only valid pixel.
        assert composite.contributor_pixel_counts == {
            "S2B_TIE_Z": 1,
            "S2B_TIE_á": 0,
        }
        assert composite.composed_bands["B08"][0, 0] == 10.0

    def test_all_bands_come_from_the_same_scene_per_pixel(self):
        # scene-best wins everywhere by coverage, but its B12 is nonfinite at
        # (0, 0); the pixel must fall through entirely to scene-other.
        scene_best = _scene(
            "S2B_SAME_A",
            [[4, 4], [4, 4]],
            value_base=100.0,
            band_overrides={("B12", 0, 0): np.nan},
        )
        scene_other = _scene("S2B_SAME_B", [[4, 4], [8, 8]], value_base=200.0)
        composite = compose_datatake(
            group_scenes_by_datatake([scene_best, scene_other])[0]
        )
        assert composite.composition_order_scene_ids[0] == "S2B_SAME_A"
        assert composite.composed_bands["B08"][0, 0] == 200.0
        assert composite.composed_bands["B12"][0, 0] == 1200.0
        assert composite.contributor_scene_index_map[0, 0] == 1
        assert (
            composite.scene_accepted_but_nonfinite_counts["S2B_SAME_A"] == 1
        )
        # Every other pixel of scene-best keeps both bands from scene-best.
        assert composite.composed_bands["B08"][0, 1] == 101.0
        assert composite.composed_bands["B12"][0, 1] == 1101.0

    def test_contributor_map_and_counts_reconcile(self):
        scenes = _three_scene_fixture()
        composite = compose_datatake(group_scenes_by_datatake(scenes)[0])
        contributor = composite.contributor_scene_index_map
        for rank, scene_id in enumerate(composite.composition_order_scene_ids):
            assert composite.contributor_pixel_counts[scene_id] == int(
                (contributor == rank).sum()
            )
        assert (
            sum(composite.contributor_pixel_counts.values())
            == composite.composed_pixel_count
        )
        assert composite.uncomposed_pixel_count == int(
            (contributor == NO_CONTRIBUTION_SENTINEL).sum()
        )
        assert (
            composite.composed_pixel_count + composite.uncomposed_pixel_count
            == composite.total_pixel_count
        )

    def test_zero_valid_composite_is_representable(self):
        scenes = [
            _scene("S2B_CLOUDY_A", [[8, 9], [9, 8]], value_base=1.0),
            _scene("S2B_CLOUDY_B", [[9, 9], [10, 10]], value_base=2.0),
        ]
        composite = compose_datatake(group_scenes_by_datatake(scenes)[0])
        assert composite.composed_pixel_count == 0
        assert composite.scl7_fraction_of_composed is None
        assert np.all(
            composite.contributor_scene_index_map == NO_CONTRIBUTION_SENTINEL
        )
        assert all(
            np.isnan(composite.composed_bands[name]).all()
            for name in composite.band_names
        )

    def test_scl7_composite_fraction_counts_chosen_pixels_only(self):
        # scene-c wins its SCL 7 pixels at (0, 0) and (0, 1).
        scenes = _three_scene_fixture()
        composite = compose_datatake(group_scenes_by_datatake(scenes)[0])
        chosen7 = int((composite.chosen_scl == 7).sum())
        assert composite.scl7_composed_pixel_count == chosen7 == 2
        assert composite.scl7_fraction_of_composed == pytest.approx(
            chosen7 / composite.composed_pixel_count
        )
        evidence = composite.evidence["scl7_composite"]
        assert evidence["scientifically_validated"] is False
        assert evidence["public_quality_claim_permitted"] is False


class TestDeterminism:
    def test_input_permutation_invariance_is_byte_exact(self):
        scenes = _three_scene_fixture()
        reference = compose_datatake(group_scenes_by_datatake(scenes)[0])
        for permutation in itertools.permutations(scenes):
            composite = compose_datatake(
                group_scenes_by_datatake(permutation)[0]
            )
            assert (
                composite.composition_evidence_sha256
                == reference.composition_evidence_sha256
            )
            np.testing.assert_array_equal(
                composite.contributor_scene_index_map,
                reference.contributor_scene_index_map,
            )
            for name in reference.band_names:
                assert (
                    composite.composed_bands[name].tobytes()
                    == reference.composed_bands[name].tobytes()
                )

    def test_repeated_composition_is_byte_exact(self):
        scenes = _three_scene_fixture()
        first = compose_datatake(group_scenes_by_datatake(scenes)[0])
        second = compose_datatake(group_scenes_by_datatake(scenes)[0])
        assert (
            first.composition_evidence_sha256
            == second.composition_evidence_sha256
        )
        assert first.evidence == second.evidence
        assert (
            first.chosen_scl.tobytes() == second.chosen_scl.tobytes()
        )

    def test_composite_arrays_are_readonly(self):
        composite = compose_datatake(
            group_scenes_by_datatake(_three_scene_fixture())[0]
        )
        with pytest.raises(ValueError):
            composite.contributor_scene_index_map[0, 0] = 0
        with pytest.raises(ValueError):
            composite.composed_bands["B08"][0, 0] = 0.0


class TestIndependentDatatakes:
    def test_same_day_datatakes_compose_independently(self):
        scenes_b = _three_scene_fixture()
        scenes_a = [
            _scene(
                "S2A_OTHER_1",
                [[4, 4, 4, 4]] * 4,
                value_base=900.0,
                platform="sentinel-2a",
                datatake_id=DATATAKE_A,
            )
        ]
        alone = compose_datatake(group_scenes_by_datatake(scenes_b)[0])
        together = compose_grouped_scenes(scenes_b + scenes_a)
        assert len(together) == 2
        by_datatake = {
            composite.datatake_id: composite for composite in together
        }
        assert (
            by_datatake[DATATAKE_B].composition_evidence_sha256
            == alone.composition_evidence_sha256
        )
        assert by_datatake[DATATAKE_A].contributor_pixel_counts == {
            "S2A_OTHER_1": 16
        }


class TestFailClosedComposition:
    def test_mask_failure_propagates_with_scene_context(self):
        scenes = [
            _scene("S2B_OK", [[4]], value_base=1.0),
            _scene(
                "S2B_UNREVIEWED",
                [[4]],
                value_base=2.0,
                baseline="05.10",
                datatake_id="GS2B_20260407T132251_041247_N05.10",
            ),
        ]
        # Two datatake ids (the baseline suffix differs) -> two groups; build
        # the unreviewed group and compose it.
        groups = group_scenes_by_datatake(scenes)
        unreviewed = [
            group
            for group in groups
            if group.scenes[0].scene_id == "S2B_UNREVIEWED"
        ][0]
        with pytest.raises(UnreviewedProcessingBaselineError) as excinfo:
            compose_datatake(unreviewed)
        assert excinfo.value.scene_id == "S2B_UNREVIEWED"

    def test_multi_failure_datatake_fails_identically_for_any_input_order(self):
        # Two scenes fail for different reasons; the surfaced fail-closed
        # error (and therefore any terminal reason code derived from it) must
        # not depend on the input permutation.
        datatake_id = "GS2B_20260407T132251_041247_N05.10"
        unreviewed = _scene(
            "S2B_MULTI_A",
            [[4]],
            value_base=1.0,
            baseline="05.10",
            datatake_id=datatake_id,
        )
        missing = create_scene_input_v2(
            scene_id="S2B_MULTI_B",
            platform="sentinel-2b",
            datatake_id=datatake_id,
            properties={},
            scl=np.asarray([[4]], dtype=np.uint8),
            bands={"B08": np.asarray([[1.0]]), "B12": np.asarray([[2.0]])},
        )
        outcomes = []
        for permutation in itertools.permutations([unreviewed, missing]):
            with pytest.raises(Exception) as excinfo:
                compose_datatake(
                    group_scenes_by_datatake(list(permutation))[0]
                )
            outcomes.append(
                (type(excinfo.value), excinfo.value.scene_id)
            )
        assert len(set(outcomes)) == 1
        assert outcomes[0] == (UnreviewedProcessingBaselineError, "S2B_MULTI_A")

    def test_band_set_must_be_uniform(self):
        left = _scene("S2B_BANDS_A", [[4]], value_base=1.0)
        right = _scene(
            "S2B_BANDS_B", [[4]], value_base=2.0, band_names=("B08",)
        )
        with pytest.raises(ValueError, match="band set"):
            compose_datatake(group_scenes_by_datatake([left, right])[0])

    def test_grid_shapes_must_match(self):
        left = _scene("S2B_SHAPE_A", [[4, 4]], value_base=1.0)
        right = _scene("S2B_SHAPE_B", [[4], [4]], value_base=2.0)
        with pytest.raises(ValueError, match="shape"):
            compose_datatake(group_scenes_by_datatake([left, right])[0])

    def test_band_dtype_must_be_uniform(self):
        left = _scene("S2B_DTYPE_A", [[4]], value_base=1.0)
        right_bands = {
            "B08": np.asarray([[2.0]], dtype=np.float32),
            "B12": np.asarray([[2.0]], dtype=np.float32),
        }
        right = create_scene_input_v2(
            scene_id="S2B_DTYPE_B",
            platform="sentinel-2b",
            datatake_id=DATATAKE_B,
            properties={"s2:processing_baseline": "05.12"},
            scl=np.asarray([[4]], dtype=np.uint8),
            bands=right_bands,
        )
        with pytest.raises(ValueError, match="dtype"):
            compose_datatake(group_scenes_by_datatake([left, right])[0])

    def test_masked_arrays_fail_closed_instead_of_dropping_nodata(self):
        # np.asarray would silently strip a MaskedArray's nodata mask and
        # treat fill values as real data; both inputs must fail closed.
        masked_scl = np.ma.masked_array(
            [[8, 4]], mask=[[False, True]], dtype=np.uint8
        )
        with pytest.raises(ValueError, match="masked array"):
            create_scene_input_v2(
                scene_id="S2B_MASKED_SCL",
                platform="sentinel-2b",
                datatake_id=DATATAKE_B,
                properties={"s2:processing_baseline": "05.12"},
                scl=masked_scl,
                bands={"B08": np.asarray([[1.0, 2.0]])},
            )
        with pytest.raises(ValueError, match="masked array"):
            create_scene_input_v2(
                scene_id="S2B_MASKED_BAND",
                platform="sentinel-2b",
                datatake_id=DATATAKE_B,
                properties={"s2:processing_baseline": "05.12"},
                scl=np.asarray([[4, 4]], dtype=np.uint8),
                bands={
                    "B08": np.ma.masked_array(
                        [[1.0, 2.0]], mask=[[False, True]]
                    )
                },
            )

    def test_scene_inputs_do_not_alias_caller_arrays(self):
        scl_source = np.asarray([[4, 8]], dtype=np.uint8)
        band_source = np.asarray([[1.0, 2.0]])
        scene = create_scene_input_v2(
            scene_id="S2B_ALIAS",
            platform="sentinel-2b",
            datatake_id=DATATAKE_B,
            properties={"s2:processing_baseline": "05.12"},
            scl=scl_source,
            bands={"B08": band_source, "B12": band_source.copy()},
        )
        before = compose_datatake(group_scenes_by_datatake([scene])[0])
        scl_source[0, 0] = 9
        band_source[0, 0] = 999.0
        after = compose_datatake(group_scenes_by_datatake([scene])[0])
        assert (
            before.composition_evidence_sha256
            == after.composition_evidence_sha256
        )
        with pytest.raises(ValueError):
            scene.bands["B08"][0, 0] = 5.0
        with pytest.raises(ValueError):
            scene.scl[0, 0] = 5

    def test_failed_datatake_still_enumerates_every_readable_baseline(self):
        # Both scenes carry readable but unreviewed baselines; the surfaced
        # fail-closed error must enumerate both observed values, not only the
        # first failure's.
        scenes = [
            _scene(
                "S2B_ENUM_A",
                [[4]],
                value_base=1.0,
                baseline="05.10",
                datatake_id="dt-enum-multi",
            ),
            _scene(
                "S2B_ENUM_B",
                [[4]],
                value_base=2.0,
                baseline="05.13",
                datatake_id="dt-enum-multi",
            ),
        ]
        with pytest.raises(UnreviewedProcessingBaselineError) as excinfo:
            compose_datatake(group_scenes_by_datatake(scenes)[0])
        assert excinfo.value.scene_id == "S2B_ENUM_A"
        assert excinfo.value.observed_baselines == ("05.10", "05.13")

    def test_integer_bands_fail_closed(self):
        with pytest.raises(ValueError, match="floating point"):
            create_scene_input_v2(
                scene_id="S2B_INT",
                platform="sentinel-2b",
                datatake_id=DATATAKE_B,
                properties={"s2:processing_baseline": "05.12"},
                scl=np.asarray([[4]], dtype=np.uint8),
                bands={"B08": np.asarray([[1]], dtype=np.int32)},
            )


class TestEvidence:
    def test_evidence_binds_methods_arrays_and_baselines(self):
        composite = compose_datatake(
            group_scenes_by_datatake(_three_scene_fixture())[0]
        )
        evidence = composite.evidence
        assert evidence["composite_method_id"] == COMPOSITION_METHOD_ID
        assert (
            evidence["composition_scope_version"] == COMPOSITION_SCOPE_VERSION
        )
        assert evidence["scene_order_policy"] == list(SCENE_ORDER_POLICY)
        assert evidence["pixel_selection"] == PIXEL_SELECTION_POLICY
        assert evidence["all_bands_for_pixel_from_same_scene"] is True
        assert evidence["different_datatakes_never_composed"] is True
        assert evidence["observed_processing_baselines"] == ["05.12"]
        assert (
            evidence["reviewed_processing_baseline_registry"]["registry_id"]
            == "araripe-reviewed-processing-baselines-v1"
        )
        contributor_digest = evidence["arrays"]["contributor_scene_index_map"]
        assert contributor_digest["no_contribution_sentinel"] == (
            NO_CONTRIBUTION_SENTINEL
        )
        import hashlib

        recomputed = hashlib.sha256(
            np.ascontiguousarray(
                composite.contributor_scene_index_map
            ).tobytes()
        ).hexdigest()
        assert contributor_digest["sha256"] == recomputed
        per_scene = {
            entry["scene_id"]: entry for entry in evidence["scenes"]
        }
        assert set(per_scene) == set(composite.composition_order_scene_ids)
        for scene_id, entry in per_scene.items():
            assert (
                entry["valid_pixel_count"]
                == composite.scene_valid_pixel_counts[scene_id]
            )
