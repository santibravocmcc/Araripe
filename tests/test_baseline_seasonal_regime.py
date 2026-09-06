"""Seasonal source-regime regressions (Package 2A.6C.1).

The 2A.6C rebuild could not write its manifest: months 01-04 fell below the
accepted extent-coverage floor and no single source policy fixes them. The
accepted answer is a *regime* -- a disjoint set of calendar months with its own
reviewed-baseline registry, scene cloud filter and declared provenance state.

These tests hold the construct to the property that makes it safe: a calendar
month has exactly one source policy, and a scene is admitted only by the
registry of the month it belongs to. A gap, an overlap, or a value borrowed
across regimes must fail closed.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from config import settings
from src.detection.baseline_manifest_v2 import (
    _validate_source_regimes_block,
    BaselineManifestV2Error,
)
from src.processing.baseline_rebuild_v2 import (
    AMENDMENT_REGIME_V1_PATH,
    AMENDMENT_REGIME_V1_SHA256,
    DEFAULT_SOURCE_REGIME_ID,
    SOURCE_REGIME_CONTRACT_ID,
    BaselineRebuildError,
    base_rebuild_registry,
    baseline_query_fingerprint,
    build_baseline_rebuild_plan,
    build_source_regime,
    default_source_regimes,
    load_baseline_rebuild_registry,
    load_source_regimes,
    regime_for_month,
    run_manifest_binding_from_plan,
    union_registry,
    validate_source_regimes,
)

WET_REVIEW = Path("config/phase2a6c1_wet_season_processing_baseline_review_v1.json")
DRY_REVIEW = Path("config/phase2a6c_baseline_processing_baseline_review_v1.json")


def _regime(regime_id, months, registry, *, cloud=40, state="collection1_lineage_stable"):
    return build_source_regime(
        regime_id=regime_id,
        months=months,
        registry=registry,
        scene_cloud_filter_percent=cloud,
        provenance_state=state,
    )


# ─── the accepted amendment ──────────────────────────────────────────────────


def test_accepted_amendment_matches_its_pinned_checksum():
    digest = hashlib.sha256(Path(AMENDMENT_REGIME_V1_PATH).read_bytes()).hexdigest()
    assert digest == AMENDMENT_REGIME_V1_SHA256


def test_accepted_amendment_declares_two_partitioning_regimes():
    regimes = load_source_regimes()
    assert [r.regime_id for r in regimes] == [
        "wet-season-mixed-lineage-v1",
        "dry-season-collection1-v1",
    ]
    assert sorted(m for r in regimes for m in r.months) == list(range(1, 13))


def test_wet_regime_admits_the_reviewed_values_and_dry_regime_does_not():
    wet, dry = None, None
    for regime in load_source_regimes():
        if regime.months[0] == 1:
            wet = regime
        else:
            dry = regime
    wet_only = {"02.11", "02.14", "03.00", "03.01", "04.00"}
    assert wet_only <= set(wet.registry.effective_values)
    # The whole point: the same values stay fail-closed in the dry season.
    assert not (wet_only & set(dry.registry.effective_values))
    assert dry.scene_cloud_filter_percent == settings.BASELINE_MAX_CLOUD_COVER
    assert wet.scene_cloud_filter_percent == 60
    assert wet.provenance_state == "mixed_lineage_pending_esa_reprocessing"
    assert dry.provenance_state == "collection1_lineage_stable"


def test_month_resolution_follows_the_declared_months():
    regimes = load_source_regimes()
    for month in (1, 2, 3, 4):
        assert regime_for_month(regimes, month).regime_id == "wet-season-mixed-lineage-v1"
    for month in (5, 8, 12):
        assert regime_for_month(regimes, month).regime_id == "dry-season-collection1-v1"
    with pytest.raises(BaselineRebuildError):
        regime_for_month(regimes, 13)


# ─── the partition property ──────────────────────────────────────────────────


def test_regimes_must_cover_every_month():
    registry = base_rebuild_registry()
    with pytest.raises(BaselineRebuildError, match="have no source regime"):
        validate_source_regimes([_regime("partial", range(1, 12), registry)])


def test_regimes_may_not_overlap():
    registry = base_rebuild_registry()
    with pytest.raises(BaselineRebuildError, match="claimed by both"):
        validate_source_regimes(
            [
                _regime("a", range(1, 7), registry),
                _regime("b", range(6, 13), registry),
            ]
        )


def test_duplicate_regime_id_is_refused():
    registry = base_rebuild_registry()
    with pytest.raises(BaselineRebuildError, match="duplicate source regime"):
        validate_source_regimes(
            [
                _regime("same", range(1, 7), registry),
                _regime("same", range(7, 13), registry),
            ]
        )


@pytest.mark.parametrize("months", [(0, 1), (12, 13), (1, 1), (4, 2)])
def test_bad_month_sets_are_refused(months):
    with pytest.raises(BaselineRebuildError):
        _regime("bad", months, base_rebuild_registry())


@pytest.mark.parametrize("cloud", [0, -1, 101, 40.0, True])
def test_bad_cloud_filters_are_refused(cloud):
    with pytest.raises(BaselineRebuildError, match="cloud filter"):
        _regime("bad", range(1, 13), base_rebuild_registry(), cloud=cloud)


def test_unknown_provenance_state_is_refused():
    with pytest.raises(BaselineRebuildError, match="provenance_state"):
        _regime("bad", range(1, 13), base_rebuild_registry(), state="probably_fine")


# ─── composing several recorded reviews ──────────────────────────────────────


def test_two_recorded_reviews_compose():
    registry = load_baseline_rebuild_registry([DRY_REVIEW, WET_REVIEW])
    assert set(registry.effective_values) == {
        "02.11", "02.14", "03.00", "03.01", "04.00",
        "05.00", "05.09", "05.10", "05.11", "05.12",
    }


def test_a_value_admitted_twice_fails_closed(tmp_path):
    duplicate = json.loads(WET_REVIEW.read_text(encoding="utf-8"))
    duplicate["extension_id"] = "duplicate-review"
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(BaselineRebuildError, match="more than one"):
        load_baseline_rebuild_registry([WET_REVIEW, path])


def test_union_registry_states_everything_admitted_anywhere():
    regimes = load_source_regimes()
    union = union_registry(regimes)
    for regime in regimes:
        assert set(regime.registry.effective_values) <= set(union.effective_values)


# ─── plan and query fingerprint ──────────────────────────────────────────────


def test_seasonal_plan_differs_from_the_single_policy_plan():
    seasonal = build_baseline_rebuild_plan(regimes=load_source_regimes())
    single = build_baseline_rebuild_plan(registry=base_rebuild_registry())
    assert seasonal["rebuild_plan_sha256"] != single["rebuild_plan_sha256"]
    assert [r["regime_id"] for r in single["source_regimes"]] == [
        DEFAULT_SOURCE_REGIME_ID
    ]
    assert single["source_regime_contract"]["contract_id"] == SOURCE_REGIME_CONTRACT_ID


def test_identical_regimes_reproduce_identical_bindings():
    a = build_baseline_rebuild_plan(regimes=load_source_regimes())
    b = build_baseline_rebuild_plan(regimes=load_source_regimes())
    assert a["rebuild_plan_sha256"] == b["rebuild_plan_sha256"]
    assert run_manifest_binding_from_plan(a) == run_manifest_binding_from_plan(b)


def test_plan_requires_exactly_one_of_registry_or_regimes():
    with pytest.raises(BaselineRebuildError, match="exactly one"):
        build_baseline_rebuild_plan()
    with pytest.raises(BaselineRebuildError, match="exactly one"):
        build_baseline_rebuild_plan(
            registry=base_rebuild_registry(), regimes=load_source_regimes()
        )


def test_query_fingerprint_separates_materially_different_rebuilds():
    regimes = load_source_regimes()
    unscoped = baseline_query_fingerprint()
    seasonal = baseline_query_fingerprint(regimes)
    assert unscoped != seasonal
    # A different wet-season cloud filter is a different source selection and
    # must not share a fingerprint with this one.
    altered = [
        build_source_regime(
            regime_id=r.regime_id,
            months=r.months,
            registry=r.registry,
            scene_cloud_filter_percent=(
                80 if r.regime_id.startswith("wet") else r.scene_cloud_filter_percent
            ),
            provenance_state=r.provenance_state,
        )
        for r in regimes
    ]
    assert baseline_query_fingerprint(altered) != seasonal


def test_single_policy_plan_still_carries_the_accepted_default_filter():
    plan = build_baseline_rebuild_plan(registry=base_rebuild_registry())
    assert plan["source"]["scene_cloud_filter_percent"] == (
        settings.BASELINE_MAX_CLOUD_COVER
    )
    assert plan["source"]["scene_cloud_filter_is_regime_scoped"] is True


# ─── the manifest-side regime block ──────────────────────────────────────────


def _manifest_regime_block():
    regimes = load_source_regimes()
    return {
        "source_regime_contract": {
            "contract_id": SOURCE_REGIME_CONTRACT_ID,
            "regimes_partition_calendar_months": True,
            "gap_or_overlap_policy": "unavailable_fail_closed",
            "registry_scope": "per_regime_never_global",
        },
        "source_regimes": [r.regime_dict() for r in regimes],
    }


def test_manifest_regime_block_resolves_each_month():
    owner, registries = _validate_source_regimes_block(_manifest_regime_block())
    assert owner[1] == "wet-season-mixed-lineage-v1"
    assert owner[8] == "dry-season-collection1-v1"
    assert "04.00" in registries[1]
    # The dry season must not inherit a wet-season admission.
    assert "04.00" not in registries[8]


def test_manifest_regime_gap_is_refused():
    block = _manifest_regime_block()
    block["source_regimes"][0]["months"] = [1, 2, 3]
    with pytest.raises(BaselineManifestV2Error, match="have no source regime"):
        _validate_source_regimes_block(block)


def test_manifest_regime_overlap_is_refused():
    block = _manifest_regime_block()
    block["source_regimes"][1]["months"] = [4, 5, 6, 7, 8, 9, 10, 11, 12]
    with pytest.raises(BaselineManifestV2Error, match="claimed by both"):
        _validate_source_regimes_block(block)


def test_manifest_regime_needs_the_fail_closed_contract():
    for field, value in (
        ("contract_id", "something-else"),
        ("regimes_partition_calendar_months", False),
        ("gap_or_overlap_policy", "best_effort"),
        ("registry_scope", "global"),
    ):
        block = _manifest_regime_block()
        block["source_regime_contract"][field] = value
        with pytest.raises(BaselineManifestV2Error):
            _validate_source_regimes_block(block)


def test_manifest_regime_registry_must_be_a_recorded_review():
    block = _manifest_regime_block()
    wet = block["source_regimes"][0]["reviewed_processing_baseline_registry"]
    # Widening a regime by editing the manifest, with no recorded review
    # behind it, is exactly what the section 5 gate exists to stop.
    wet["added_reviewed_values"].append("02.13")
    wet["reviewed_values"].append("02.13")
    with pytest.raises(BaselineManifestV2Error):
        _validate_source_regimes_block(block)


@pytest.mark.parametrize("state", ["", "fine", None])
def test_manifest_regime_provenance_state_is_closed(state):
    block = _manifest_regime_block()
    block["source_regimes"][0]["provenance_state"] = state
    with pytest.raises(BaselineManifestV2Error, match="provenance_state"):
        _validate_source_regimes_block(block)


# ─── end-to-end: a seasonal manifest, and the cross-regime rejection ─────────

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

from src.detection.baseline_manifest import expected_filenames  # noqa: E402
from src.detection.baseline_manifest_v2 import (  # noqa: E402
    RASTER_CONTRACT_V2,
    audit_rebuilt_baseline_directory,
    build_manifest_v2,
    manifest_datatake_entry_from_composition,
    validate_manifest_v2,
)
from src.processing.baseline_rebuild_v2 import (  # noqa: E402
    BASELINE_REBUILD_PLAN_VERSION,
    BASELINE_V2_DRIVE_FOLDER,
    BASELINE_V2_EXPORT_PREFIX,
    REBUILD_INDEX_NAMES,
    compose_rebuild_datatake,
    compute_monthly_baseline_statistics,
    contribution_count_filename,
    declare_baseline_source_datatake,
    month_export_filename,
)
from src.processing.composition_v2 import create_scene_input_v2  # noqa: E402

pytestmark = pytest.mark.filterwarnings(
    "ignore:is_tiled will be removed:PendingDeprecationWarning"
)

SEASONAL_CONTRACT = {
    **{key: value for key, value in RASTER_CONTRACT_V2.items()},
    "width": 4,
    "height": 4,
    "transform": [20.0, 0.0, 300000.0, 0.0, -20.0, 9200000.0],
    "bounds": [300000.0, 9199920.0, 300080.0, 9200000.0],
}


def _raster(path, value):
    with rasterio.open(
        path, "w", driver="GTiff", width=4, height=4, count=1, dtype="float32",
        crs="EPSG:32724", transform=from_origin(300000, 9200000, 20, 20),
        nodata=np.nan, tiled=True, blockxsize=16, blockysize=16, compress="deflate",
    ) as dst:
        dst.write(np.full((4, 4), value, dtype="float32"), 1)


def _seasonal_scene(scene_id, *, platform, datatake_id, baseline, offset=0.0):
    ramp = np.linspace(0.0, 0.05, 4, dtype=np.float64).reshape((2, 2))
    return create_scene_input_v2(
        scene_id=scene_id, platform=platform, datatake_id=datatake_id,
        properties={"s2:processing_baseline": baseline},
        scl=np.asarray([[4, 5], [6, 7]], dtype=np.uint8),
        bands={
            "B4": 0.10 + offset + ramp, "B8": 0.40 + offset + ramp,
            "B8A": 0.42 + offset + ramp, "B11": 0.25 + offset + ramp,
            "B12": 0.15 + offset + ramp,
        },
    )


def _seasonal_manifest(tmp_path, *, wet_baseline="04.00", dry_baseline="05.11"):
    """A twelve-month manifest whose wet and dry months use different regimes."""
    raster_dir = tmp_path / "rasters"
    raster_dir.mkdir()
    for filename in expected_filenames():
        _raster(raster_dir / filename, 0.05 if filename.endswith("_std.tif") else 0.1)
    objects = audit_rebuilt_baseline_directory(
        raster_dir, raster_contract=SEASONAL_CONTRACT
    )
    regimes = load_source_regimes()
    plan = build_baseline_rebuild_plan(regimes=regimes)
    run_id, run_sha = run_manifest_binding_from_plan(plan)
    grid_pixels = SEASONAL_CONTRACT["width"] * SEASONAL_CONTRACT["height"]

    months, total_scenes = [], 0
    for month in range(1, 13):
        regime = regime_for_month(regimes, month)
        wet = month in (1, 2, 3, 4)
        baseline = wet_baseline if wet else dry_baseline
        year = 2022 if wet else 2025
        unit = "A" if month % 2 else "B"
        platform = f"sentinel-2{unit.lower()}"
        stamp = f"{year}{month:02d}15T131241"
        datatake_id = f"GS2{unit}_{stamp}_000123_N{baseline}"
        datatake = declare_baseline_source_datatake(
            year=year, month=month, platform=platform, datatake_id=datatake_id,
            acquisition_timestamp_utc=f"{year}-{month:02d}-15T13:12:41Z",
            scenes=tuple(
                _seasonal_scene(
                    f"S2{unit}_M{month:02d}_{i}", platform=platform,
                    datatake_id=datatake_id, baseline=baseline, offset=0.01 * i,
                )
                for i in range(2)
            ),
        )
        record = compose_rebuild_datatake(
            datatake, registry=regime.registry,
            run_manifest_id=run_id, run_manifest_sha256=run_sha,
        )
        stats = compute_monthly_baseline_statistics(
            month, [record], registry=regime.registry
        )
        entry = manifest_datatake_entry_from_composition(record)
        total_scenes += entry["scene_count"]
        months.append({
            "month": month,
            "source_regime": regime.regime_id,
            "gee_task_id": f"SEASONAL_TASK_{month:02d}",
            "export_file": {
                "name": month_export_filename(month), "bytes": 1000 + month,
                "sha256": hashlib.sha256(f"e{month}".encode()).hexdigest(),
            },
            "month_evidence_sha256": stats.month_evidence_sha256,
            "contribution_counts": {
                index: {
                    "file": contribution_count_filename(index, month),
                    "bytes": 500 + month,
                    "sha256": hashlib.sha256(f"c{index}{month}".encode()).hexdigest(),
                    "total_pixels": grid_pixels, "minimum": 1, "maximum": 4,
                    "median": 3.0, "pixels_with_zero_contributions": 0,
                    "pixels_below_three_contributions": 2,
                }
                for index in REBUILD_INDEX_NAMES
            },
            "datatakes": [entry],
        })

    execution = {
        "rebuild_plan_version": BASELINE_REBUILD_PLAN_VERSION,
        "rebuild_plan_sha256": plan["rebuild_plan_sha256"],
        "run_manifest_id": run_id, "run_manifest_sha256": run_sha,
        "earth_engine": {
            "project_id": "ee-seasonal-fixture",
            "image_collection_id": settings.GEE_COLLECTION_ID,
            "query_fingerprint_sha256": baseline_query_fingerprint(regimes),
            "drive_folder": BASELINE_V2_DRIVE_FOLDER,
            "file_name_prefix": BASELINE_V2_EXPORT_PREFIX,
        },
        "months": months,
        "totals": {"datatake_count": 12, "scene_count": total_scenes},
    }
    return build_manifest_v2(
        objects, execution,
        registry_block=union_registry(regimes).registry_dict(),
        build_date="2026-09-05", raster_contract=SEASONAL_CONTRACT,
        source_regimes=[r.regime_dict() for r in regimes],
    )


def test_seasonal_manifest_validates_end_to_end(tmp_path):
    manifest = _seasonal_manifest(tmp_path)
    validate_manifest_v2(manifest, raster_contract=SEASONAL_CONTRACT)
    by_month = {m["month"]: m["source_regime"] for m in manifest["rebuild_execution"]["months"]}
    assert by_month[1] == "wet-season-mixed-lineage-v1"
    assert by_month[8] == "dry-season-collection1-v1"
    assert "04.00" in manifest["observed_processing_baselines"]


def test_wet_season_baseline_cannot_even_be_composed_in_a_dry_month(tmp_path):
    """The gate this whole package exists for, at its earliest point.

    04.00 is admitted in the wet regime. Used in a dry-season month the
    consumed mask refuses it before a single pixel is composed -- the regime
    scoping reaches all the way down into the closed 2A.6B science without
    that science needing to know regimes exist.
    """
    from src.processing.scl_mask_v2 import UnreviewedProcessingBaselineError

    with pytest.raises(UnreviewedProcessingBaselineError, match="04.00"):
        _seasonal_manifest(tmp_path, dry_baseline="04.00")


def test_manifest_independently_refuses_a_cross_regime_baseline(tmp_path):
    """And again at the manifest, for a document that never met the composer.

    A manifest is validated on its own bytes, so the same rejection must hold
    when the entry is fabricated rather than composed.
    """
    manifest = _seasonal_manifest(tmp_path)
    tampered = copy.deepcopy(manifest)
    dry_month = next(
        m for m in tampered["rebuild_execution"]["months"] if m["month"] == 8
    )
    dry_month["datatakes"][0]["scenes"][0]["processing_baseline"] = "04.00"
    with pytest.raises(BaselineManifestV2Error, match="outside the effective"):
        validate_manifest_v2(tampered, raster_contract=SEASONAL_CONTRACT)


def test_wet_season_baseline_is_accepted_in_its_own_regime(tmp_path):
    """The mirror of the rejection: the same value is fine where reviewed."""
    manifest = _seasonal_manifest(tmp_path, wet_baseline="04.00")
    validate_manifest_v2(manifest, raster_contract=SEASONAL_CONTRACT)


def test_a_month_may_not_claim_the_wrong_regime(tmp_path):
    manifest = _seasonal_manifest(tmp_path)
    tampered = copy.deepcopy(manifest)
    tampered["rebuild_execution"]["months"][0]["source_regime"] = (
        "dry-season-collection1-v1"
    )
    with pytest.raises(BaselineManifestV2Error, match="source_regime must be"):
        validate_manifest_v2(tampered, raster_contract=SEASONAL_CONTRACT)


def test_manifest_must_bind_the_seasonal_amendment(tmp_path):
    manifest = _seasonal_manifest(tmp_path)
    tampered = copy.deepcopy(manifest)
    del tampered["decision_bindings"]["seasonal_source_regime_amendment_v1"]
    with pytest.raises(BaselineManifestV2Error, match="seasonal source-regime"):
        validate_manifest_v2(tampered, raster_contract=SEASONAL_CONTRACT)


def test_manifest_declares_the_per_month_regime_provenance(tmp_path):
    manifest = _seasonal_manifest(tmp_path)
    retained = manifest["source"]["provenance_completeness"]["retained"]
    assert "per-month source regime and its declared provenance state" in retained
    states = {r["regime_id"]: r["provenance_state"] for r in manifest["source_regimes"]}
    assert states["wet-season-mixed-lineage-v1"] == "mixed_lineage_pending_esa_reprocessing"
