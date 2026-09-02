"""Package 2A.6C baseline-rebuild machinery regressions.

Covers the required 2A.6C gates on the rebuild side: fail-closed behavior for
unreviewed GEE processing baselines and platforms, the recorded-review-only
registry extension, local/GEE parity of the counts-derived composition plan
used by the rebuild, deterministic monthly statistics, and the deterministic
rebuild plan that binds the v3 run-manifest identity.
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import pytest

from src.detection.identity_v3 import create_acquisition_v3
from src.processing.baseline_rebuild_v2 import (
    BASELINE_REBUILD_PLAN_VERSION,
    BASELINE_V2_GRID_ID,
    REBUILD_BAND_NAMES,
    REBUILD_INDEX_NAMES,
    V3_REPRESENTABLE_PLATFORMS,
    BaselineRebuildError,
    base_rebuild_registry,
    build_baseline_rebuild_plan,
    build_rebuild_gee_plan,
    compose_rebuild_datatake,
    compute_index_grids,
    compute_monthly_baseline_statistics,
    declare_baseline_source_datatake,
    derive_first_valid_order,
    load_baseline_rebuild_registry,
    run_manifest_binding_from_plan,
)
from src.processing.composition_v2 import (
    compose_datatake,
    create_scene_input_v2,
    group_scenes_by_datatake,
)
from src.processing.gee_composition_v2 import (
    GeeParityError,
    assert_local_gee_parity,
    execute_gee_plan_locally,
)
from src.processing.scl_mask_v2 import (
    MissingProcessingBaselineError,
    REVIEWED_PROCESSING_BASELINES,
    UnreviewedProcessingBaselineError,
)


RUN_ID = "run-v3-" + "a" * 64
RUN_SHA = "b" * 64


def _scene(
    scene_id,
    scl_rows,
    *,
    platform="sentinel-2a",
    datatake_id,
    baseline="05.11",
    properties=None,
    band_offset=0.0,
):
    scl = np.asarray(scl_rows, dtype=np.uint8)
    shape = scl.shape
    ramp = np.linspace(0.0, 0.05, scl.size, dtype=np.float64).reshape(shape)
    bands = {
        "B4": 0.10 + band_offset + ramp,
        "B8": 0.40 + band_offset + ramp,
        "B8A": 0.42 + band_offset + ramp,
        "B11": 0.25 + band_offset + ramp,
        "B12": 0.15 + band_offset + ramp,
    }
    if properties is None:
        properties = {"s2:processing_baseline": baseline}
    return create_scene_input_v2(
        scene_id=scene_id,
        platform=platform,
        datatake_id=datatake_id,
        properties=properties,
        scl=scl,
        bands=bands,
    )


def _datatake(
    *,
    year=2017,
    month=1,
    platform="sentinel-2a",
    unit="A",
    baseline="05.11",
    day=15,
    scl_rows=None,
    n_scenes=2,
):
    stamp = f"{year}{month:02d}{day:02d}T131241"
    datatake_id = f"GS2{unit}_{stamp}_000123_N{baseline}"
    rows = scl_rows if scl_rows is not None else [[4, 5], [6, 7]]
    scenes = tuple(
        _scene(
            f"S2{unit}_SCENE_{month:02d}_{i}",
            rows,
            platform=platform,
            datatake_id=datatake_id,
            baseline=baseline,
            band_offset=0.01 * i,
        )
        for i in range(n_scenes)
    )
    return declare_baseline_source_datatake(
        year=year,
        month=month,
        platform=platform,
        datatake_id=datatake_id,
        acquisition_timestamp_utc=(
            f"{year}-{month:02d}-{day:02d}T13:12:41Z"
        ),
        scenes=scenes,
    )


# ─── Reviewed registry: recorded review only, never a fallback ───────────────


def _extension_payload():
    return {
        "schema_version": "1.0.0",
        "extension_id": "araripe-baseline-rebuild-pb-review-2026-09",
        "base_registry_id": "araripe-reviewed-processing-baselines-v1",
        "base_reviewed_values": ["05.11", "05.12"],
        "reviewed_by": "project owner",
        "review_date": "2026-09-01",
        "review_scope": "baseline 2.0.0 source years",
        "added_values": [
            {
                "value": "05.10",
                "review_basis": "provider release notes reviewed",
                "observed_in": "baseline source year query",
            }
        ],
    }


def test_base_registry_is_the_closed_2a6b_enumeration():
    registry = base_rebuild_registry()
    assert registry.effective_values == REVIEWED_PROCESSING_BASELINES
    payload = registry.registry_dict()
    assert payload["reviewed_values"] == ["05.11", "05.12"]
    assert payload["unreviewed_value_policy"] == "unavailable_fail_closed"
    assert payload["extension_policy"] == "recorded_review_only_never_fallback"
    assert "recorded_review_extension" not in payload


def test_registry_extension_requires_a_complete_recorded_review(tmp_path):
    valid = _extension_payload()
    path = tmp_path / "extension.json"
    path.write_text(json.dumps(valid), encoding="utf-8")
    registry = load_baseline_rebuild_registry(path)
    assert registry.effective_values == ("05.10", "05.11", "05.12")
    recorded = registry.registry_dict()["recorded_review_extension"]
    assert recorded["reviewed_by"] == "project owner"
    assert recorded["added_values"][0]["value"] == "05.10"

    for mutate in (
        lambda doc: doc.pop("reviewed_by"),
        lambda doc: doc.update(reviewed_by="   "),
        lambda doc: doc.update(review_date="01/09/2026"),
        lambda doc: doc.update(base_reviewed_values=["05.12"]),
        lambda doc: doc.update(added_values=[]),
        lambda doc: doc["added_values"][0].pop("review_basis"),
        lambda doc: doc["added_values"][0].update(value="5.10"),
        lambda doc: doc["added_values"][0].update(value="05.11"),
        lambda doc: doc.update(
            added_values=valid["added_values"] * 2
        ),
    ):
        broken = json.loads(json.dumps(_extension_payload()))
        mutate(broken)
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(BaselineRebuildError):
            load_baseline_rebuild_registry(path)


def test_registry_extension_is_never_a_fallback():
    assert load_baseline_rebuild_registry(None).effective_values == (
        REVIEWED_PROCESSING_BASELINES
    )


# ─── Platform gate is the v3 contract, not a local policy ────────────────────


def test_representable_platforms_constant_is_proven_by_the_v3_contract():
    for platform in V3_REPRESENTABLE_PLATFORMS:
        acquisition = create_acquisition_v3(
            run_manifest_id=RUN_ID,
            run_manifest_sha256=RUN_SHA,
            collection_id="COPERNICUS/S2_SR_HARMONIZED",
            platform=platform,
            datatake_id="GS2A_20170115T131241_000123_N05.11",
            acquisition_timestamp_utc="2017-01-15T13:12:41Z",
            scene_ids=("SCENE",),
            monitoring_extent_id="araripe-implementation-rectangle-v1",
            composite_method_id="coverage-ranked-first-valid-v1",
            grid_id=BASELINE_V2_GRID_ID,
        )
        assert acquisition.platform == platform
    with pytest.raises(ValueError, match="S2A, S2B or S2C"):
        create_acquisition_v3(
            run_manifest_id=RUN_ID,
            run_manifest_sha256=RUN_SHA,
            collection_id="COPERNICUS/S2_SR_HARMONIZED",
            platform="S2D",
            datatake_id="GS2D_20170115T131241_000123_N05.11",
            acquisition_timestamp_utc="2017-01-15T13:12:41Z",
            scene_ids=("SCENE",),
            monitoring_extent_id="araripe-implementation-rectangle-v1",
            composite_method_id="coverage-ranked-first-valid-v1",
            grid_id=BASELINE_V2_GRID_ID,
        )


def test_sentinel2c_composes_and_sentinel2d_fails_closed():
    registry = base_rebuild_registry()
    s2c = _datatake(platform="sentinel-2c", unit="C")
    record = compose_rebuild_datatake(
        s2c,
        registry=registry,
        run_manifest_id=RUN_ID,
        run_manifest_sha256=RUN_SHA,
    )
    assert record.acquisition.platform == "S2C"
    assert record.parity_evidence["parity"] is True

    s2d = _datatake(platform="sentinel-2d", unit="D")
    with pytest.raises(ValueError, match="S2A, S2B or S2C"):
        compose_rebuild_datatake(
            s2d,
            registry=registry,
            run_manifest_id=RUN_ID,
            run_manifest_sha256=RUN_SHA,
        )


# ─── Declared source datatakes ───────────────────────────────────────────────


def test_declared_datatake_rejects_contract_violations():
    with pytest.raises(BaselineRebuildError, match="source years"):
        _datatake(year=2023)
    with pytest.raises(BaselineRebuildError, match="baseline slot"):
        declare_baseline_source_datatake(
            year=2017,
            month=2,
            platform="sentinel-2a",
            datatake_id="GS2A_20170115T131241_000123_N05.11",
            acquisition_timestamp_utc="2017-01-15T13:12:41Z",
            scenes=(
                _scene(
                    "S2A_X",
                    [[4]],
                    datatake_id="GS2A_20170115T131241_000123_N05.11",
                ),
            ),
        )
    with pytest.raises(BaselineRebuildError, match="sensing instant"):
        declare_baseline_source_datatake(
            year=2017,
            month=1,
            platform="sentinel-2a",
            datatake_id="GS2A_20170115T131241_000123_N05.11",
            acquisition_timestamp_utc="2017-01-15T13:12:42Z",
            scenes=(
                _scene(
                    "S2A_X",
                    [[4]],
                    datatake_id="GS2A_20170115T131241_000123_N05.11",
                ),
            ),
        )


def test_declared_datatake_requires_the_exact_rebuild_band_set():
    datatake_id = "GS2A_20170115T131241_000123_N05.11"
    scl = np.asarray([[4]], dtype=np.uint8)
    scene = create_scene_input_v2(
        scene_id="S2A_MISSING_BAND",
        platform="sentinel-2a",
        datatake_id=datatake_id,
        properties={"s2:processing_baseline": "05.11"},
        scl=scl,
        bands={"B4": np.asarray([[0.1]], dtype=np.float64)},
    )
    with pytest.raises(BaselineRebuildError, match="band contract"):
        declare_baseline_source_datatake(
            year=2017,
            month=1,
            platform="sentinel-2a",
            datatake_id=datatake_id,
            acquisition_timestamp_utc="2017-01-15T13:12:41Z",
            scenes=(scene,),
        )


# ─── Fail-closed processing baselines through the rebuild path ───────────────


def test_unreviewed_processing_baseline_fails_closed_until_recorded_review(
    tmp_path,
):
    unreviewed = _datatake(baseline="05.10")
    with pytest.raises(UnreviewedProcessingBaselineError):
        compose_rebuild_datatake(
            unreviewed,
            registry=base_rebuild_registry(),
            run_manifest_id=RUN_ID,
            run_manifest_sha256=RUN_SHA,
        )

    path = tmp_path / "extension.json"
    path.write_text(json.dumps(_extension_payload()), encoding="utf-8")
    extended = load_baseline_rebuild_registry(path)
    record = compose_rebuild_datatake(
        unreviewed,
        registry=extended,
        run_manifest_id=RUN_ID,
        run_manifest_sha256=RUN_SHA,
    )
    assert record.composite.observed_processing_baselines == ("05.10",)


def test_missing_processing_baseline_metadata_fails_closed():
    datatake_id = "GS2A_20170115T131241_000123_N05.11"
    scene = _scene(
        "S2A_NO_META",
        [[4]],
        datatake_id=datatake_id,
        properties={},
    )
    datatake = declare_baseline_source_datatake(
        year=2017,
        month=1,
        platform="sentinel-2a",
        datatake_id=datatake_id,
        acquisition_timestamp_utc="2017-01-15T13:12:41Z",
        scenes=(scene,),
    )
    with pytest.raises(MissingProcessingBaselineError):
        compose_rebuild_datatake(
            datatake,
            registry=base_rebuild_registry(),
            run_manifest_id=RUN_ID,
            run_manifest_sha256=RUN_SHA,
        )


# ─── Counts-derived plan: local/GEE parity of the rebuild composition ────────


def test_counts_derived_plan_reproduces_the_local_composite_bytes():
    datatake = _datatake(
        scl_rows=[[4, 8], [9, 5]],
        n_scenes=3,
    )
    registry = base_rebuild_registry()
    record = compose_rebuild_datatake(
        datatake,
        registry=registry,
        run_manifest_id=RUN_ID,
        run_manifest_sha256=RUN_SHA,
    )
    composite = record.composite
    plan = record.gee_plan
    assert plan["valid_pixel_count_source"] == "local_reference_composite"
    assert tuple(plan["first_valid_order"]) == (
        composite.composition_order_scene_ids
    )
    # Re-execute the counts-derived plan independently: byte parity again.
    execution = execute_gee_plan_locally(
        plan, datatake.scenes, reviewed_baselines=registry.effective_values
    )
    evidence = assert_local_gee_parity(composite, execution)
    assert evidence["parity"] is True
    assert (
        record.parity_evidence["gee_plan_sha256"] == plan["gee_plan_sha256"]
    )


def test_gee_reduce_region_count_source_yields_the_same_scientific_plan():
    datatake = _datatake(n_scenes=2)
    registry = base_rebuild_registry()
    composite = compose_datatake(
        group_scenes_by_datatake(datatake.scenes)[0],
        reviewed_baselines=registry.effective_values,
    )
    # The production executor derives the plan from GEE reduceRegion counts;
    # given equal counts it must produce the same order and pass the same
    # local execution and parity gates.
    plan = build_rebuild_gee_plan(
        image_collection_id="COPERNICUS/S2_SR_HARMONIZED",
        platform=composite.platform,
        datatake_id=composite.datatake_id,
        band_names=composite.band_names,
        valid_pixel_counts=composite.scene_valid_pixel_counts,
        observed_processing_baselines=(
            composite.observed_processing_baselines
        ),
        count_source="gee_reduce_region",
    )
    assert tuple(plan["first_valid_order"]) == (
        composite.composition_order_scene_ids
    )
    execution = execute_gee_plan_locally(
        plan, datatake.scenes, reviewed_baselines=registry.effective_values
    )
    evidence = assert_local_gee_parity(composite, execution)
    assert evidence["parity"] is True


def test_tampered_plan_or_wrong_counts_fail_the_parity_gate():
    datatake = _datatake(n_scenes=2)
    registry = base_rebuild_registry()
    record = compose_rebuild_datatake(
        datatake,
        registry=registry,
        run_manifest_id=RUN_ID,
        run_manifest_sha256=RUN_SHA,
    )
    tampered = dict(record.gee_plan)
    tampered["first_valid_order"] = list(
        reversed(tampered["first_valid_order"])
    )
    tampered["mosaic_input_order"] = list(
        reversed(tampered["mosaic_input_order"])
    )
    with pytest.raises(GeeParityError):
        execute_gee_plan_locally(
            tampered,
            datatake.scenes,
            reviewed_baselines=registry.effective_values,
        )

    wrong_counts = {
        scene_id: count + 1
        for scene_id, count in record.composite.scene_valid_pixel_counts.items()
    }
    wrong_plan = build_rebuild_gee_plan(
        image_collection_id="COPERNICUS/S2_SR_HARMONIZED",
        platform=record.composite.platform,
        datatake_id=record.composite.datatake_id,
        band_names=record.composite.band_names,
        valid_pixel_counts=wrong_counts,
        observed_processing_baselines=(
            record.composite.observed_processing_baselines
        ),
        count_source="gee_reduce_region",
    )
    with pytest.raises(GeeParityError, match="valid_pixel_count"):
        execute_gee_plan_locally(
            wrong_plan,
            datatake.scenes,
            reviewed_baselines=registry.effective_values,
        )


def test_derive_first_valid_order_breaks_ties_by_utf8_scene_id():
    order = derive_first_valid_order({"b": 5, "a": 5, "c": 9})
    assert order == ("c", "a", "b")
    with pytest.raises(BaselineRebuildError):
        derive_first_valid_order({"a": -1})
    with pytest.raises(BaselineRebuildError):
        build_rebuild_gee_plan(
            image_collection_id="COPERNICUS/S2_SR_HARMONIZED",
            platform="S2A",
            datatake_id="GS2A_20170115T131241_000123_N05.11",
            band_names=REBUILD_BAND_NAMES,
            valid_pixel_counts={"a": 1},
            observed_processing_baselines=("05.11",),
            count_source="not-a-source",
        )


# ─── Index computation ───────────────────────────────────────────────────────


def test_index_formulas_and_nonfinite_policy():
    shape = (1, 3)
    bands = {
        "B4": np.asarray([[0.1, 0.0, np.nan]], dtype=np.float64),
        "B8": np.asarray([[0.4, 0.0, np.nan]], dtype=np.float64),
        "B8A": np.asarray([[0.42, 0.0, np.nan]], dtype=np.float64),
        "B11": np.asarray([[0.25, 0.0, np.nan]], dtype=np.float64),
        "B12": np.asarray([[0.15, 0.0, np.nan]], dtype=np.float64),
    }
    grids, nonfinite = compute_index_grids(bands)
    assert set(grids) == set(REBUILD_INDEX_NAMES)
    assert grids["ndmi"].shape == shape
    assert grids["ndmi"][0, 0] == pytest.approx((0.42 - 0.25) / (0.42 + 0.25))
    assert grids["nbr"][0, 0] == pytest.approx((0.42 - 0.15) / (0.42 + 0.15))
    assert grids["evi2"][0, 0] == pytest.approx(
        2.5 * (0.4 - 0.1) / (0.4 + 2.4 * 0.1 + 1.0)
    )
    # Composed pixel with zero denominators: ndmi/nbr become missing and are
    # counted; evi2 has denominator 1.0 there and stays finite.
    assert np.isnan(grids["ndmi"][0, 1]) and np.isnan(grids["nbr"][0, 1])
    assert grids["evi2"][0, 1] == 0.0
    assert nonfinite == {"ndmi": 1, "nbr": 1, "evi2": 0}
    # Uncomposed pixel stays missing without being counted as nonfinite.
    assert np.isnan(grids["ndmi"][0, 2])


# ─── Monthly statistics across datatake composites ───────────────────────────


def _month_records(month=1, specs=((2017, "A", 15), (2019, "A", 16), (2021, "B", 17))):
    registry = base_rebuild_registry()
    records = []
    for year, unit, day in specs:
        platform = f"sentinel-2{unit.lower()}"
        datatake = _datatake(
            year=year,
            month=month,
            platform=platform,
            unit=unit,
            day=day,
            scl_rows=[[4, 8], [5, 6]],
            n_scenes=1,
        )
        records.append(
            compose_rebuild_datatake(
                datatake,
                registry=registry,
                run_manifest_id=RUN_ID,
                run_manifest_sha256=RUN_SHA,
            )
        )
    return registry, records


def test_monthly_statistics_are_median_population_std_and_counts():
    registry, records = _month_records()
    stats = compute_monthly_baseline_statistics(
        1, records, registry=registry
    )
    stacked = np.stack(
        [
            np.asarray(record.index_grids["ndmi"], dtype=np.float64)
            for record in sorted(
                records,
                key=lambda item: item.acquisition.acquisition_timestamp_utc,
            )
        ]
    )
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        # The expected values hit the same defined all-NaN pixel state the
        # module handles; the reference computation is equally quiet.
        warnings.simplefilter("ignore", RuntimeWarning)
        expected_median = np.nanmedian(stacked, axis=0).astype(np.float32)
        expected_std = np.nanstd(stacked, axis=0, ddof=0).astype(np.float32)
    finite = np.isfinite(stacked)
    # Pixel (0, 1) is SCL 8 in every composite: no contribution anywhere.
    assert stats.contribution_count["ndmi"][0, 1] == 0
    assert np.isnan(stats.median["ndmi"][0, 1])
    assert np.isnan(stats.std["ndmi"][0, 1])
    composed = stats.contribution_count["ndmi"] > 0
    assert np.array_equal(
        stats.contribution_count["ndmi"], finite.sum(axis=0).astype(np.int32)
    )
    assert np.array_equal(
        stats.median["ndmi"][composed], expected_median[composed]
    )
    assert np.array_equal(stats.std["ndmi"][composed], expected_std[composed])
    assert stats.median["ndmi"].dtype == np.float32
    assert stats.std["ndmi"].dtype == np.float32


def test_monthly_statistics_are_permutation_invariant_and_traceable():
    registry, records = _month_records()
    forward = compute_monthly_baseline_statistics(
        1, records, registry=registry
    )
    backward = compute_monthly_baseline_statistics(
        1, list(reversed(records)), registry=registry
    )
    assert forward.month_evidence_sha256 == backward.month_evidence_sha256
    for index in REBUILD_INDEX_NAMES:
        assert (
            forward.median[index].tobytes()
            == backward.median[index].tobytes()
        )
        assert forward.std[index].tobytes() == backward.std[index].tobytes()
    entries = forward.evidence["datatakes"]
    assert [entry["acquisition_id"] for entry in entries] == list(
        forward.acquisition_ids
    )
    assert all(entry["parity"]["verified"] for entry in entries)
    assert forward.evidence["observed_platforms"] == ["S2A", "S2B"]


def test_monthly_statistics_reject_wrong_month_and_duplicates():
    registry, records = _month_records()
    with pytest.raises(BaselineRebuildError, match="belongs to month"):
        compute_monthly_baseline_statistics(2, records, registry=registry)
    with pytest.raises(BaselineRebuildError, match="duplicate"):
        compute_monthly_baseline_statistics(
            1, [records[0], records[0]], registry=registry
        )


def test_single_composite_month_yields_zero_population_std():
    registry, records = _month_records(specs=((2017, "A", 15),))
    stats = compute_monthly_baseline_statistics(
        1, records, registry=registry
    )
    composed = stats.contribution_count["nbr"] > 0
    assert np.all(stats.std["nbr"][composed] == 0.0)


# ─── The deterministic rebuild plan ──────────────────────────────────────────


def test_rebuild_plan_is_deterministic_and_binds_the_run_manifest():
    registry = base_rebuild_registry()
    plan_a = build_baseline_rebuild_plan(registry=registry)
    plan_b = build_baseline_rebuild_plan(registry=registry)
    assert plan_a == plan_b
    assert plan_a["rebuild_plan_version"] == BASELINE_REBUILD_PLAN_VERSION
    assert plan_a["baseline_version"] == "2.0.0"
    assert plan_a["predecessor"]["baseline_version"] == "1.0.0"
    assert plan_a["predecessor"]["immutable"] is True
    assert plan_a["mask"]["accepted_scl_classes"] == [4, 5, 6, 7]
    assert plan_a["mask"]["identical_to_candidate_generation"] is True
    run_id, run_sha = run_manifest_binding_from_plan(plan_a)
    assert run_id == "run-v3-" + plan_a["rebuild_plan_sha256"]
    assert run_sha == plan_a["rebuild_plan_sha256"]

    tampered = dict(plan_a)
    tampered["source"] = dict(tampered["source"], years=[2017])
    with pytest.raises(BaselineRebuildError, match="checksum"):
        run_manifest_binding_from_plan(tampered)


def test_rebuild_plan_registry_extension_changes_bindings_not_science():
    base_plan = build_baseline_rebuild_plan(registry=base_rebuild_registry())
    extension = _extension_payload()
    extended_registry = load_baseline_rebuild_registry_from_dict(extension)
    extended_plan = build_baseline_rebuild_plan(registry=extended_registry)
    assert (
        base_plan["rebuild_plan_sha256"]
        != extended_plan["rebuild_plan_sha256"]
    )
    assert base_plan["mask"] == extended_plan["mask"]
    assert base_plan["composition"] == extended_plan["composition"]
    assert base_plan["statistics"] == extended_plan["statistics"]


def load_baseline_rebuild_registry_from_dict(extension):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "extension.json"
        path.write_text(json.dumps(extension), encoding="utf-8")
        return load_baseline_rebuild_registry(path)
