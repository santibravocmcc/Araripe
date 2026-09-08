"""Baseline 2.0.0 manifest regressions (Package 2A.6C).

Covers the four manifest-side 2A.6C gates: the mask-baseline identity in the
new manifest, complete manifest validation with fail-closed rejections,
baseline 1.0.0 immutability, and fail-closed handling of unreviewed GEE
processing baselines and platforms — plus the manifest CLI's refusal paths.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from click.testing import CliRunner
from rasterio.transform import from_origin

from config import settings
from src.detection.baseline_manifest import (
    expected_filenames,
    load_manifest as load_manifest_v1,
)
from src.detection.baseline_manifest_v2 import (
    BASELINE_V1_KEY_PREFIX,
    BASELINE_V2_KEY_PREFIX,
    BASELINE_V2_LOCAL_DIR,
    BASELINE_V2_MANIFEST_PATH,
    RASTER_CONTRACT_V2,
    BaselineManifestV2Error,
    audit_rebuilt_baseline_directory,
    build_manifest_v2,
    load_manifest_v2,
    manifest_datatake_entry_from_composition,
    require_baseline_v1_untouched,
    validate_manifest_v2,
    write_manifest_v2,
)
from src.processing.baseline_rebuild_v2 import (
    BASELINE_REBUILD_PLAN_VERSION,
    BASELINE_V1_MANIFEST_SHA256,
    BASELINE_V2_DRIVE_FOLDER,
    BASELINE_V2_EXPORT_PREFIX,
    REBUILD_INDEX_NAMES,
    base_rebuild_registry,
    baseline_query_fingerprint,
    contribution_count_filename,
    contribution_count_summary,
    month_export_filename,
    build_baseline_rebuild_plan,
    compose_rebuild_datatake,
    compute_monthly_baseline_statistics,
    declare_baseline_source_datatake,
    run_manifest_binding_from_plan,
)
from src.processing.composition_v2 import create_scene_input_v2
from src.processing.scl_mask_v2 import (
    SCL_ACCEPTED_CLASSES,
    SCL_MASK_METHOD_ID,
    SCL_REJECTED_CLASSES,
)


# The consumed (immutable) Package 2A.2 auditor reads rasterio's deprecated
# ``is_tiled`` property; that pre-existing warning belongs to the v1 module,
# not to this package's code.
pytestmark = pytest.mark.filterwarnings(
    "ignore:is_tiled will be removed:PendingDeprecationWarning"
)


FIXTURE_CONTRACT = {
    **{key: value for key, value in RASTER_CONTRACT_V2.items()},
    "width": 4,
    "height": 4,
    "transform": [20.0, 0.0, 300000.0, 0.0, -20.0, 9200000.0],
    "bounds": [300000.0, 9199920.0, 300080.0, 9200000.0],
}


def _write_raster(path: Path, value: float) -> None:
    data = np.full((4, 4), value, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:32724",
        transform=from_origin(300000, 9200000, 20, 20),
        nodata=np.nan,
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="deflate",
    ) as dst:
        dst.write(data, 1)


def _scene(scene_id, *, platform, datatake_id, baseline, offset=0.0):
    scl = np.asarray([[4, 5], [6, 7]], dtype=np.uint8)
    ramp = np.linspace(0.0, 0.05, 4, dtype=np.float64).reshape((2, 2))
    bands = {
        "B4": 0.10 + offset + ramp,
        "B8": 0.40 + offset + ramp,
        "B8A": 0.42 + offset + ramp,
        "B11": 0.25 + offset + ramp,
        "B12": 0.15 + offset + ramp,
    }
    return create_scene_input_v2(
        scene_id=scene_id,
        platform=platform,
        datatake_id=datatake_id,
        properties={"s2:processing_baseline": baseline},
        scl=scl,
        bands=bands,
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("baseline_v2_fixture")
    raster_dir = root / "rasters"
    raster_dir.mkdir()
    for filename in expected_filenames():
        _write_raster(
            raster_dir / filename,
            0.05 if filename.endswith("_std.tif") else 0.1,
        )
    objects = audit_rebuilt_baseline_directory(
        raster_dir, raster_contract=FIXTURE_CONTRACT
    )

    registry = base_rebuild_registry()
    plan = build_baseline_rebuild_plan(registry=registry)
    run_id, run_sha = run_manifest_binding_from_plan(plan)

    months = []
    total_scenes = 0
    years = list(settings.BASELINE_SOURCE_YEARS)
    for month in range(1, 13):
        # Month 3 is deliberately Sentinel-2C in source year 2025 (the only
        # baseline year in which S2C flew): the v3 amendment makes it a
        # first-class rebuild platform.
        year = 2025 if month == 3 else years[(month - 1) % len(years)]
        unit = "C" if month == 3 else ("B" if month % 2 == 0 else "A")
        baseline = "05.12" if month % 3 == 0 else "05.11"
        platform = f"sentinel-2{unit.lower()}"
        stamp = f"{year}{month:02d}15T131241"
        datatake_id = f"GS2{unit}_{stamp}_000123_N{baseline}"
        datatake = declare_baseline_source_datatake(
            year=year,
            month=month,
            platform=platform,
            datatake_id=datatake_id,
            acquisition_timestamp_utc=f"{year}-{month:02d}-15T13:12:41Z",
            scenes=tuple(
                _scene(
                    f"S2{unit}_M{month:02d}_{i}",
                    platform=platform,
                    datatake_id=datatake_id,
                    baseline=baseline,
                    offset=0.01 * i,
                )
                for i in range(2)
            ),
        )
        record = compose_rebuild_datatake(
            datatake,
            registry=registry,
            run_manifest_id=run_id,
            run_manifest_sha256=run_sha,
        )
        stats = compute_monthly_baseline_statistics(
            month, [record], registry=registry
        )
        entry = manifest_datatake_entry_from_composition(record)
        total_scenes += entry["scene_count"]
        # The fixture rasters are fully finite, so every pixel must show at
        # least one contribution and no zero tail.
        grid_pixels = FIXTURE_CONTRACT["width"] * FIXTURE_CONTRACT["height"]
        months.append(
            {
                "month": month,
                "gee_task_id": f"FIXTURE_TASK_{month:02d}",
                "export_file": {
                    "name": month_export_filename(month),
                    "bytes": 1000 + month,
                    "sha256": _sha(f"export-{month}"),
                },
                "month_evidence_sha256": stats.month_evidence_sha256,
                "contribution_counts": {
                    index: {
                        "file": contribution_count_filename(index, month),
                        "bytes": 500 + month,
                        "sha256": _sha(f"count-{index}-{month}"),
                        "total_pixels": grid_pixels,
                        "minimum": 1,
                        "maximum": 4,
                        "median": 3.0,
                        "pixels_with_zero_contributions": 0,
                        "pixels_below_three_contributions": 2,
                    }
                    for index in REBUILD_INDEX_NAMES
                },
                "datatakes": [entry],
            }
        )

    execution = {
        "rebuild_plan_version": BASELINE_REBUILD_PLAN_VERSION,
        "rebuild_plan_sha256": plan["rebuild_plan_sha256"],
        "run_manifest_id": run_id,
        "run_manifest_sha256": run_sha,
        "earth_engine": {
            "project_id": "ee-fixture-project",
            "image_collection_id": settings.GEE_COLLECTION_ID,
            "query_fingerprint_sha256": baseline_query_fingerprint(),
            "drive_folder": BASELINE_V2_DRIVE_FOLDER,
            "file_name_prefix": BASELINE_V2_EXPORT_PREFIX,
        },
        "months": months,
        "totals": {"datatake_count": 12, "scene_count": total_scenes},
    }
    manifest = build_manifest_v2(
        objects,
        execution,
        registry_block=registry.registry_dict(),
        build_date="2026-09-01",
        raster_contract=FIXTURE_CONTRACT,
    )
    return SimpleNamespace(
        manifest=manifest,
        objects=objects,
        execution=execution,
        registry=registry,
        raster_dir=raster_dir,
    )


def _reject(world, mutate, match=None):
    manifest = copy.deepcopy(world.manifest)
    mutate(manifest)
    with pytest.raises(BaselineManifestV2Error, match=match):
        validate_manifest_v2(manifest, raster_contract=FIXTURE_CONTRACT)


# ─── Baseline 1.0.0 immutability ─────────────────────────────────────────────


def test_baseline_v1_manifest_is_pinned_and_untouched(tmp_path):
    verified = require_baseline_v1_untouched()
    assert verified == BASELINE_V1_MANIFEST_SHA256
    # The accepted v1 manifest still passes its own authoritative validator.
    manifest_v1 = load_manifest_v1(settings.BASELINE_MANIFEST_PATH)
    assert manifest_v1["baseline_version"] == "1.0.0"

    drifted = tmp_path / "baseline_manifest_v1.json"
    payload = json.loads(
        settings.BASELINE_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    payload["decision"]["rebuild_required"] = True
    drifted.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineManifestV2Error, match="immutable"):
        require_baseline_v1_untouched(drifted)


def test_v2_storage_identity_is_disjoint_from_v1():
    assert not BASELINE_V2_KEY_PREFIX.startswith(BASELINE_V1_KEY_PREFIX)
    assert BASELINE_V2_LOCAL_DIR != settings.BASELINES_DIR
    assert (
        Path(BASELINE_V2_MANIFEST_PATH).resolve()
        != Path(settings.BASELINE_MANIFEST_PATH).resolve()
    )


def test_write_manifest_refuses_v1_path_and_existing_files(world, tmp_path):
    with pytest.raises(BaselineManifestV2Error, match="immutable baseline"):
        write_manifest_v2(
            world.manifest,
            settings.BASELINE_MANIFEST_PATH,
            raster_contract=FIXTURE_CONTRACT,
        )
    target = tmp_path / "baseline_manifest_v2.json"
    written = write_manifest_v2(
        world.manifest, target, raster_contract=FIXTURE_CONTRACT
    )
    reloaded = load_manifest_v2(written, raster_contract=FIXTURE_CONTRACT)
    assert reloaded == world.manifest
    with pytest.raises(BaselineManifestV2Error, match="refusing to overwrite"):
        write_manifest_v2(
            world.manifest, target, raster_contract=FIXTURE_CONTRACT
        )


def test_stored_manifest_cannot_vouch_for_its_own_contract(world, tmp_path):
    target = tmp_path / "manifest.json"
    write_manifest_v2(world.manifest, target, raster_contract=FIXTURE_CONTRACT)
    # Loading with the production default must reject the fixture grid: an
    # embedded raster_contract is never trusted to validate itself.
    with pytest.raises(BaselineManifestV2Error, match="raster_contract"):
        load_manifest_v2(target)


# ─── Mask-baseline identity in the new manifest ──────────────────────────────


def test_manifest_mask_identity_equals_the_runtime_v2_mask(world):
    block = world.manifest["mask_baseline_identity"]
    assert block["scl_mask_method_id"] == SCL_MASK_METHOD_ID
    assert block["accepted_scl_classes"] == list(SCL_ACCEPTED_CLASSES) == [
        4,
        5,
        6,
        7,
    ]
    assert block["rejected_scl_classes"] == list(SCL_REJECTED_CLASSES)
    assert block["identical_to_candidate_generation"] is True
    assert block["superseded_v1_scl_clear_classes"] == [2, 4, 5, 6, 7, 11]
    assert block["dark_nir_proximity_mask"] is False
    assert block["cloud_shadow_dilation_m"] == 0


def test_manifest_rejects_the_v1_mask_and_any_mask_drift(world):
    def use_v1_mask(manifest):
        manifest["mask_baseline_identity"]["accepted_scl_classes"] = [
            2,
            4,
            5,
            6,
            7,
            11,
        ]
        manifest["mask_baseline_identity"]["rejected_scl_classes"] = [
            0,
            1,
            3,
            8,
            9,
            10,
        ]

    _reject(world, use_v1_mask, match="mask_baseline_identity")
    _reject(
        world,
        lambda m: m["mask_baseline_identity"].update(
            scl_mask_method_id="scl-legacy-v1"
        ),
        match="mask_baseline_identity",
    )
    _reject(
        world,
        lambda m: m["mask_baseline_identity"].update(
            identical_to_candidate_generation=False
        ),
        match="mask_baseline_identity",
    )


# ─── Complete manifest validation: fail-closed battery ───────────────────────


def test_manifest_happy_path_enumerates_platforms_and_baselines(world):
    assert world.manifest["observed_platforms"] == ["S2A", "S2B", "S2C"]
    assert world.manifest["observed_processing_baselines"] == [
        "05.11",
        "05.12",
    ]
    validate_manifest_v2(world.manifest, raster_contract=FIXTURE_CONTRACT)


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda m: m.update(schema_version="1.0.0"), "schema_version"),
        (lambda m: m.update(baseline_version="1.0.0"), "baseline_version"),
        (lambda m: m.update(status="accepted_audit_generation"), "status"),
        (
            lambda m: m["predecessor"].update(manifest_sha256="0" * 64),
            "predecessor",
        ),
        (
            lambda m: m["predecessor"].update(deleted_or_overwritten=True),
            "predecessor",
        ),
        (
            lambda m: m["decision_bindings"][
                "candidate_generation_decisions_v2"
            ].update(sha256="0" * 64),
            "decision",
        ),
        (
            lambda m: m["composition"].update(
                composite_method_id="daily_mosaic-v1"
            ),
            "composition",
        ),
        (
            lambda m: m["statistics"].update(dispersion="sample_std"),
            "statistics",
        ),
        (
            lambda m: m["monitoring_extent"].update(bounds=[0, 0, 1, 1]),
            "monitoring extent",
        ),
        (lambda m: m["source"].update(years=[2017]), "source-year"),
        (
            lambda m: m["source"]["provenance_completeness"].update(
                status="partial"
            ),
            "provenance",
        ),
        (
            lambda m: m["source"]["provenance_completeness"].update(
                missing=["GEE task IDs"]
            ),
            "missing provenance",
        ),
        (
            lambda m: m["source"]["provenance_completeness"]["retained"].remove(
                "GEE query fingerprint"
            ),
            "provenance",
        ),
        (
            lambda m: m["reviewed_processing_baseline_registry"].update(
                reviewed_values=["05.11", "05.12", "05.10"]
            ),
            "sorted base plus added",
        ),
        (
            lambda m: m["reviewed_processing_baseline_registry"].update(
                added_reviewed_values=["05.10"],
                reviewed_values=["05.10", "05.11", "05.12"],
            ),
            "recorded_review_extension",
        ),
        (
            lambda m: m.update(
                observed_processing_baselines=["05.10", "05.11", "05.12"]
            ),
            "observed_processing_baselines",
        ),
        (
            lambda m: m.update(observed_platforms=["S2A"]),
            "observed_platforms",
        ),
        (
            lambda m: m["rebuild_execution"].update(run_manifest_id=(
                "run-v3-" + "f" * 64
            )),
            "run-manifest",
        ),
        (
            lambda m: m["rebuild_execution"]["earth_engine"].update(
                project_id="  "
            ),
            "project_id",
        ),
        (
            lambda m: m["rebuild_execution"]["months"].pop(),
            "months",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0].update(
                datatakes=[]
            ),
            "at least one",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0].update(
                gee_task_id=""
            ),
            "gee_task_id",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0]["export_file"].update(
                sha256="zz"
            ),
            "sha256",
        ),
        (
            lambda m: m["rebuild_execution"]["totals"].update(
                scene_count=999
            ),
            "totals",
        ),
        (
            lambda m: m["raster_contract"].update(width=8),
            "raster_contract",
        ),
        (
            lambda m: m["objects"][0].update(key="baselines/evi2_month01_mean.tif"),
            "key mismatch",
        ),
        (
            lambda m: m["objects"][0].update(width=8),
            "grid violates",
        ),
        (
            lambda m: m["objects"][0].update(extent_coverage_fraction=0.5),
            "coverage",
        ),
        (
            lambda m: m["objects"][0].update(range_violation_pixels=3),
            "out-of-range",
        ),
        (
            lambda m: m["objects"][1].update(minimum=-0.2),
            "negative std",
        ),
        (
            lambda m: m["objects"][0].update(
                derived_from_month_export="wrong.tif"
            ),
            "month's export",
        ),
        (
            lambda m: m["objects"][0].update(sha256="1" * 64),
            "inventory checksum",
        ),
        (
            lambda m: m["aggregate"].update(total_bytes=1),
            "byte count",
        ),
    ],
)
def test_manifest_rejects_every_tampered_block(world, mutate, match):
    _reject(world, mutate, match=match)


def test_manifest_rederives_acquisition_and_plan_identities(world):
    def swap_acquisition(manifest):
        entry = manifest["rebuild_execution"]["months"][0]["datatakes"][0]
        entry["acquisition_id"] = "acq-v3-" + "0" * 64

    _reject(world, swap_acquisition, match="rederive")

    def swap_plan(manifest):
        entry = manifest["rebuild_execution"]["months"][0]["datatakes"][0]
        entry["gee_plan_sha256"] = "0" * 64

    _reject(world, swap_plan, match="rederive")

    def swap_counts(manifest):
        entry = manifest["rebuild_execution"]["months"][0]["datatakes"][0]
        first = sorted(entry["valid_pixel_counts"])[0]
        entry["valid_pixel_counts"][first] += 1

    _reject(world, swap_counts, match="rederive")

    def flip_verification(manifest):
        entry = manifest["rebuild_execution"]["months"][0]["datatakes"][0]
        entry["gee_verification"]["counts_reconciled"] = False

    _reject(world, flip_verification, match="reconcile")


# ─── Fail-closed platforms and processing baselines in the manifest ──────────


def test_manifest_rejects_unreviewed_platform_and_baseline(world):
    def sentinel_2d(manifest):
        entry = manifest["rebuild_execution"]["months"][0]["datatakes"][0]
        entry["platform"] = "S2D"

    _reject(world, sentinel_2d, match="v3-representable")

    def unreviewed_scene_baseline(manifest):
        entry = manifest["rebuild_execution"]["months"][0]["datatakes"][0]
        entry["scenes"][0]["processing_baseline"] = "99.99"

    _reject(world, unreviewed_scene_baseline, match="reviewed registry")

    def duplicate_physical_datatake(manifest):
        month = manifest["rebuild_execution"]["months"][0]
        month["datatakes"].append(copy.deepcopy(month["datatakes"][0]))

    _reject(world, duplicate_physical_datatake, match="more than one")


def test_manifest_accepts_sentinel2c_datatakes(world):
    march = world.manifest["rebuild_execution"]["months"][2]
    assert march["month"] == 3
    assert march["datatakes"][0]["platform"] == "S2C"
    assert "S2C" in world.manifest["observed_platforms"]


# ─── Raster audit wrapper ────────────────────────────────────────────────────


def test_audit_wrapper_produces_v2_objects(world):
    first = world.objects[0]
    assert first["key"].startswith(BASELINE_V2_KEY_PREFIX)
    assert "md5" in first and "r2_etag" not in first
    assert "r2_last_modified" not in first
    std_objects = [
        obj for obj in world.objects if obj["filename_statistic"] == "std"
    ]
    assert all(
        obj["statistic"] == "population_standard_deviation"
        for obj in std_objects
    )


def test_audit_wrapper_fails_closed_on_grid_contract_drift(tmp_path):
    raster_dir = tmp_path / "drifted"
    raster_dir.mkdir()
    for filename in expected_filenames():
        data = np.full((4, 4), 0.1, dtype="float32")
        with rasterio.open(
            raster_dir / filename,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=1,
            dtype="float32",
            crs="EPSG:32724",
            transform=from_origin(310000, 9210000, 20, 20),
            nodata=np.nan,
        ) as dst:
            dst.write(data, 1)
    with pytest.raises(BaselineManifestV2Error, match="pinned baseline"):
        audit_rebuilt_baseline_directory(
            raster_dir, raster_contract=FIXTURE_CONTRACT
        )


# ─── Manifest CLI refusal paths ──────────────────────────────────────────────


def _load_cli():
    path = (
        Path(__file__).resolve().parent.parent
        / "scripts"
        / "rebuild_baseline_v2_manifest.py"
    )
    spec = importlib.util.spec_from_file_location(
        "rebuild_baseline_v2_manifest", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _evidence_file(world, tmp_path: Path) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(
            {
                "reviewed_processing_baseline_registry": (
                    world.registry.registry_dict()
                ),
                "rebuild_execution": world.execution,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_cli_refuses_existing_output_and_v1_target(world, tmp_path):
    module = _load_cli()
    runner = CliRunner()
    evidence = _evidence_file(world, tmp_path)

    existing = tmp_path / "already_there.json"
    existing.write_text("{}", encoding="utf-8")
    result = runner.invoke(
        module.main,
        [
            "--baselines-dir",
            str(world.raster_dir),
            "--execution-evidence",
            str(evidence),
            "--build-date",
            "2026-09-01",
            "--output",
            str(existing),
        ],
    )
    assert result.exit_code != 0
    assert "refusing to overwrite" in result.output

    result = runner.invoke(
        module.main,
        [
            "--baselines-dir",
            str(world.raster_dir),
            "--execution-evidence",
            str(evidence),
            "--build-date",
            "2026-09-01",
            "--output",
            str(settings.BASELINE_MANIFEST_PATH),
        ],
    )
    assert result.exit_code != 0
    assert "immutable baseline 1.0.0" in result.output


def test_cli_enforces_the_production_grid_contract(world, tmp_path):
    module = _load_cli()
    runner = CliRunner()
    evidence = _evidence_file(world, tmp_path)
    output = tmp_path / "fresh_manifest.json"
    result = runner.invoke(
        module.main,
        [
            "--baselines-dir",
            str(world.raster_dir),
            "--execution-evidence",
            str(evidence),
            "--build-date",
            "2026-09-01",
            "--output",
            str(output),
        ],
    )
    # Fixture-scale rasters must fail the pinned production grid: the CLI has
    # no fixture bypass.
    assert result.exit_code != 0
    assert "pinned baseline 2.0.0 contract" in result.output
    assert not output.exists()


# ─── Contribution-depth evidence ─────────────────────────────────────────────


def test_manifest_requires_contribution_depth_for_every_index(world):
    for month_entry in world.manifest["rebuild_execution"]["months"]:
        assert sorted(month_entry["contribution_counts"]) == sorted(
            REBUILD_INDEX_NAMES
        )
    assert (
        "per-index monthly contribution depth"
        in world.manifest["source"]["provenance_completeness"]["retained"]
    )
    assert (
        world.manifest["statistics"]["contribution_count_recorded"] is True
    )


@pytest.mark.parametrize(
    "mutate, match",
    [
        (
            lambda m: m["rebuild_execution"]["months"][0].pop(
                "contribution_counts"
            ),
            "contribution_counts",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0][
                "contribution_counts"
            ].pop("nbr"),
            "contribution_counts",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0]["contribution_counts"][
                "nbr"
            ].update(file="nbr_month01_mean.tif"),
            "file must be",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0]["contribution_counts"][
                "nbr"
            ].update(sha256="nope"),
            "sha256",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0]["contribution_counts"][
                "nbr"
            ].update(minimum=5, maximum=4),
            "below minimum",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0]["contribution_counts"][
                "nbr"
            ].update(maximum=0, minimum=0, pixels_with_zero_contributions=16),
            "at least one contribution",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0]["contribution_counts"][
                "nbr"
            ].update(pixels_below_three_contributions=0,
                     pixels_with_zero_contributions=1, minimum=0),
            "below-three tail",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0]["contribution_counts"][
                "nbr"
            ].update(pixels_with_zero_contributions=1),
            "minimum and the zero tail disagree",
        ),
        (
            lambda m: m["rebuild_execution"]["months"][0]["contribution_counts"][
                "nbr"
            ].update(pixels_below_three_contributions=10**9),
            "exceeds the grid pixel count",
        ),
    ],
)
def test_manifest_rejects_tampered_contribution_depth(world, mutate, match):
    _reject(world, mutate, match=match)


def test_contribution_depth_and_finite_pixels_must_reconcile(world):
    # Claiming a zero tail while the audited raster is fully finite is the
    # exact fabrication this identity exists to catch.
    def fake_zero_tail(manifest):
        block = manifest["rebuild_execution"]["months"][0][
            "contribution_counts"
        ]["evi2"]
        block["minimum"] = 0
        block["pixels_with_zero_contributions"] = 4
        block["pixels_below_three_contributions"] = 6

    _reject(world, fake_zero_tail, match="contribution-depth evidence implies")


def test_contribution_count_summary_measures_the_shallow_tail():
    counts = np.asarray([[0, 1], [2, 7]], dtype=np.int32)
    summary = contribution_count_summary(counts)
    assert summary["total_pixels"] == 4
    assert summary["minimum"] == 0 and summary["maximum"] == 7
    assert summary["pixels_with_zero_contributions"] == 1
    assert summary["pixels_below_three_contributions"] == 3
    assert summary["median"] == 1.5
    with pytest.raises(Exception):
        contribution_count_summary(np.asarray([[-1]], dtype=np.int32))
    with pytest.raises(Exception):
        contribution_count_summary(np.asarray([[1.5]], dtype=np.float64))


# ─── Export identity isolation ───────────────────────────────────────────────


def test_export_naming_is_disjoint_from_the_v1_generation():
    assert month_export_filename(3) == "araripe_baseline_v2_month03.tif"
    # The v1 export prefix must not be a prefix of the v2 one, so a v1 file
    # can never satisfy the v2 canonical-name gate.
    assert not month_export_filename(3).startswith("araripe_baseline_month")
    assert BASELINE_V2_DRIVE_FOLDER != "araripe_baselines"
    counts_name = contribution_count_filename("ndmi", 7)
    assert counts_name == "ndmi_month07_count.tif"
    assert counts_name not in expected_filenames()


def test_manifest_rejects_v1_export_names_and_foreign_destinations(world):
    _reject(
        world,
        lambda m: m["rebuild_execution"]["months"][0]["export_file"].update(
            name="araripe_baseline_month01.tif"
        ),
        match="canonical v2 export",
    )
    _reject(
        world,
        lambda m: m["rebuild_execution"]["earth_engine"].update(
            drive_folder="araripe_baselines"
        ),
        match="isolated v2 folder",
    )
    _reject(
        world,
        lambda m: m["rebuild_execution"]["earth_engine"].update(
            file_name_prefix="araripe_baseline_month"
        ),
        match="isolated v2 prefix",
    )


def test_query_fingerprint_is_deterministic_and_recorded(world):
    fingerprint = baseline_query_fingerprint()
    assert fingerprint == baseline_query_fingerprint()
    assert len(fingerprint) == 64
    # The 2A.2 audit could not reconstruct the historical query; the v2
    # manifest carries it, and validation rejects any other value.
    assert (
        world.manifest["rebuild_execution"]["earth_engine"][
            "query_fingerprint_sha256"
        ]
        == fingerprint
    )
