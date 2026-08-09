"""Offline tests for the provisional Phase 2A.4 rainfall input artifact."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from src.detection.baseline_manifest import MONITORING_EXTENT_BOUNDS, sha256_file
import src.validation.phase2a4_rainfall as rainfall_module
from src.validation.phase2a4_rainfall import (
    CHIRPS_COG_BASE_URL,
    FetchedRainfallWindow,
    RainfallArtifactError,
    RainfallFetchError,
    build_month_plan,
    build_rainfall_reference_artifact,
    chirps_cog_url,
    iter_reference_months,
    load_rainfall_monthly_values,
    read_cell_center_window,
    summarize_weighted_window,
    _validate_generator_source_inventory,
    validate_rainfall_reference_artifact,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GENERATED_AT = "2026-07-31T15:30:00-03:00"
ACCESSED_AT = "2026-07-31T15:00:00-03:00"
TARGET_MONTHS = ("2026-01", "2026-02")
GENERATION_COMMAND = ["synthetic-offline-phase2a4-rainfall-test"]


def _available_window(month: str) -> FetchedRainfallWindow:
    year, number = (int(part) for part in month.split("-"))
    base = np.float32((year * 12 + number) % 71)
    values = np.asarray(
        [[base, base + np.float32(1.0)], [np.nan, base + np.float32(3.0)]],
        dtype="<f4",
    )
    return FetchedRainfallWindow(
        values=values,
        latitude_centers=np.asarray([-7.0, -7.5], dtype="<f8"),
        longitude_centers=np.asarray([-40.5, -39.5], dtype="<f8"),
        source_grid={
            "crs": "EPSG:4326",
            "source_width": 7200,
            "source_height": 2000,
            "source_transform": [0.05, 0.0, -180.0, 0.0, -0.05, 50.0],
            "source_dtype": "float32",
            "source_nodata": -9999.0,
            "selected_window": {
                "column_offset": 2782,
                "row_offset": 1139,
                "width": 2,
                "height": 2,
            },
        },
        http_metadata={
            "status_code": 200,
            "content_length": "123456",
            "etag": f'"synthetic-{month}"',
            "last_modified": "Thu, 30 Jul 2026 12:00:00 GMT",
            "content_type": "image/tiff",
            "accept_ranges": "bytes",
            "authorization": "must-not-persist",
        },
    )


def _synthetic_fetch(
    month: str,
    source_url: str,
    bounds: tuple[float, float, float, float],
    accessed_at: str,
) -> FetchedRainfallWindow:
    assert source_url == chirps_cog_url(month)
    assert bounds == MONITORING_EXTENT_BOUNDS
    assert accessed_at == ACCESSED_AT
    if month == "2026-02":
        raise RainfallFetchError(
            "failed https://user:password@example.invalid/month.cog?token=secret-token "
            "credential=another-secret",
            http_metadata={
                "status_code": 404,
                "content_length": "0",
                "content_type": "text/plain",
                "x-secret": "must-not-persist",
            },
        )
    return _available_window(month)


def _file_digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _build(root: Path, *, workers: int) -> dict[str, Any]:
    return build_rainfall_reference_artifact(
        output_dir=root,
        target_months=TARGET_MONTHS,
        generated_at=GENERATED_AT,
        accessed_at=ACCESSED_AT,
        workers=workers,
        fetch_month=_synthetic_fetch,
        generation_command=GENERATION_COMMAND,
        repository_root=REPOSITORY_ROOT,
    )


def test_fixed_reference_plan_and_official_month_urls() -> None:
    reference = iter_reference_months()
    assert len(reference) == 540
    assert reference[0] == "1981-01"
    assert reference[-1] == "2025-12"

    plan = build_month_plan(("2026-02", "2026-01", "2026-02"))
    assert len(plan) == 542
    assert [entry["month"] for entry in plan[-2:]] == ["2026-01", "2026-02"]
    assert plan[0] == {
        "month": "1981-01",
        "roles": ["reference"],
        "source_url": (
            f"{CHIRPS_COG_BASE_URL}/chirps-v2.0.1981.01.cog"
        ),
    }
    assert chirps_cog_url("2026-06").endswith("/chirps-v2.0.2026.06.cog")
    with pytest.raises(RainfallArtifactError, match="at least one"):
        build_month_plan(())
    with pytest.raises(RainfallArtifactError, match="expected YYYY-MM"):
        chirps_cog_url("2026-6")


def test_rainfall_generator_inventory_requires_all_direct_sources() -> None:
    inventory = [
        {"path": path, "bytes": 1, "sha256": "a" * 64}
        for path in (
            "src/detection/baseline_manifest.py",
            "src/detection/identity.py",
            "src/validation/phase2a4_rainfall.py",
            "scripts/build_phase2a4_rainfall_reference.py",
        )
    ]
    _validate_generator_source_inventory(inventory)
    with pytest.raises(RainfallArtifactError, match="incomplete or reordered"):
        _validate_generator_source_inventory(inventory[1:])


def test_exact_cell_center_window_and_cosine_weighting(tmp_path: Path) -> None:
    source = tmp_path / "source.tif"
    data = np.arange(16, dtype=np.float32).reshape(4, 4)
    data[2, 2] = -9999.0
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-41.0, -6.0, 0.5, 0.5),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(data, 1)

    values, latitudes, longitudes, grid = read_cell_center_window(
        source,
        bounds=(-40.3, -7.3, -39.7, -6.7),
    )
    np.testing.assert_array_equal(latitudes, np.asarray([-6.75, -7.25]))
    np.testing.assert_array_equal(longitudes, np.asarray([-40.25, -39.75]))
    assert values.shape == (2, 2)
    assert values[0, 0] == 5.0
    assert values[0, 1] == 6.0
    assert values[1, 0] == 9.0
    assert np.isnan(values[1, 1])
    assert grid["selected_window"] == {
        "column_offset": 1,
        "row_offset": 1,
        "width": 2,
        "height": 2,
    }

    summary = summarize_weighted_window(values, latitudes, longitudes)
    north_weight = np.cos(np.deg2rad(-6.75))
    south_weight = np.cos(np.deg2rad(-7.25))
    assert summary["mean_mm"] == pytest.approx(
        (5.0 * north_weight + 6.0 * north_weight + 9.0 * south_weight)
        / (2.0 * north_weight + south_weight)
    )
    assert summary["coverage_fraction"] == pytest.approx(
        (2.0 * north_weight + south_weight)
        / (2.0 * north_weight + 2.0 * south_weight)
    )
    assert summary["finite_cells"] == 3
    assert summary["total_cells"] == 4


def test_artifact_is_deterministic_resumable_and_retains_errors(
    tmp_path: Path, monkeypatch,
) -> None:
    first_root = tmp_path / "workers-eight"
    second_root = tmp_path / "workers-one"

    first = _build(first_root, workers=8)
    assert first["month_count"] == 542
    assert first["reference_period"] == {
        "start_month": "1981-01",
        "end_month": "2025-12",
        "expected_month_count": 540,
        "available_month_count": 540,
        "status": "complete",
    }
    assert first["target_status"] == "incomplete"
    assert first["overall_status"] == "incomplete_retained_source_evidence"
    assert first["status_counts"] == {"available": 541, "error": 1}
    assert first["claims"] == {
        "rainfall_reference_only": True,
        "drought_status_computed": False,
        "drought_adjustment_activated": False,
        "method_selected": False,
        "scientific_accuracy_claim": False,
        "qualified_human_labels_present": False,
        "raw_detection_modified": False,
    }

    values_by_month = {item["month"]: item for item in first["monthly_values"]}
    january = values_by_month["2026-01"]
    assert january["status"] == "available"
    assert january["precipitation_mm"] is not None
    assert 0.0 < january["valid_coverage_fraction"] < 1.0
    assert january["source_record"]["path"] == "records/2026-01.json"
    assert january["source_window"]["path"].endswith("2026.01.araripe.npy")

    february = values_by_month["2026-02"]
    assert february == {
        "month": "2026-02",
        "status": "error",
        "precipitation_mm": None,
        "valid_coverage_fraction": None,
        "source_record": {
            "path": "records/2026-02.json",
            "sha256": sha256_file(first_root / "records/2026-02.json"),
        },
        "source_window": None,
    }
    error_record = json.loads(
        (first_root / "records/2026-02.json").read_text(encoding="utf-8")
    )
    assert error_record["http"] == {
        "status_code": 404,
        "content_length": 0,
        "etag": None,
        "last_modified": None,
        "content_type": "text/plain",
        "accept_ranges": None,
    }
    assert error_record["retrieval"] == {
        "access_mode": "remote_cog_range_read_attempt",
        "source_url_unsigned": True,
        "upstream_full_asset_sha256": None,
        "local_window_sha256": None,
    }
    assert not (first_root / "windows/chirps-v2.0.2026.02.araripe.npy").exists()
    assert "[query-redacted]" in error_record["reason"]
    assert "[userinfo-redacted]" in error_record["reason"]
    assert "credential=[redacted]" in error_record["reason"]
    for path in first_root.rglob("*"):
        if path.is_file() and path.suffix != ".npy":
            text = path.read_text(encoding="utf-8")
            assert "secret-token" not in text
            assert "another-secret" not in text
            assert "must-not-persist" not in text
            assert "user:password" not in text

    validated = validate_rainfall_reference_artifact(first_root)
    loaded = load_rainfall_monthly_values(first_root)
    assert validated["artifact_id"] == first["artifact_id"]
    assert loaded["artifact_id"] == first["artifact_id"]
    assert loaded["manifest_sha256"] == sha256_file(first_root / "manifest.json")
    assert loaded["monthly_values"]["2026-02"] == february
    assert loaded["precipitation_mm_by_month"]["2026-01"] == january[
        "precipitation_mm"
    ]
    assert loaded["precipitation_mm_by_month"]["2026-02"] is None

    before_resume = _file_digests(first_root)

    def unexpected_fetch(*_args: Any, **_kwargs: Any) -> FetchedRainfallWindow:
        raise AssertionError("a complete valid artifact must resume without fetching")

    resumed = build_rainfall_reference_artifact(
        output_dir=first_root,
        target_months=TARGET_MONTHS,
        generated_at=GENERATED_AT,
        accessed_at=ACCESSED_AT,
        workers=3,
        fetch_month=unexpected_fetch,
        generation_command=GENERATION_COMMAND,
        repository_root=REPOSITORY_ROOT,
    )
    assert resumed == first
    assert _file_digests(first_root) == before_resume

    second = _build(second_root, workers=1)
    assert second == first
    assert _file_digests(second_root) == before_resume

    interrupted_root = tmp_path / "interrupted-source-drift"
    shutil.copytree(first_root, interrupted_root)
    (interrupted_root / "manifest.json").unlink()
    (interrupted_root / "CHECKSUMS.sha256").unlink()
    original_inventory = rainfall_module._generator_source_inventory
    changed_inventory = original_inventory(REPOSITORY_ROOT)
    changed_inventory[0] = {**changed_inventory[0], "sha256": "0" * 64}
    with monkeypatch.context() as scoped:
        scoped.setattr(
            rainfall_module,
            "_generator_source_inventory",
            lambda _root: changed_inventory,
        )
        with pytest.raises(RainfallArtifactError, match="changed after retrieval"):
            build_rainfall_reference_artifact(
                output_dir=interrupted_root,
                target_months=TARGET_MONTHS,
                generated_at=GENERATED_AT,
                accessed_at=ACCESSED_AT,
                workers=1,
                fetch_month=unexpected_fetch,
                generation_command=GENERATION_COMMAND,
                repository_root=REPOSITORY_ROOT,
            )

    retried_months: list[str] = []

    def recovered_fetch(
        month: str,
        source_url: str,
        bounds: tuple[float, float, float, float],
        accessed_at: str,
    ) -> FetchedRainfallWindow:
        retried_months.append(month)
        assert month == "2026-02"
        assert source_url == chirps_cog_url(month)
        assert bounds == MONITORING_EXTENT_BOUNDS
        assert accessed_at == ACCESSED_AT
        return _available_window(month)

    recovered = build_rainfall_reference_artifact(
        output_dir=second_root,
        target_months=TARGET_MONTHS,
        generated_at=GENERATED_AT,
        accessed_at=ACCESSED_AT,
        workers=4,
        fetch_month=recovered_fetch,
        retry_errors=True,
        generation_command=GENERATION_COMMAND,
        repository_root=REPOSITORY_ROOT,
    )
    assert retried_months == ["2026-02"]
    assert recovered["overall_status"] == "complete"
    assert recovered["status_counts"] == {"available": 542}
    assert recovered["monthly_values"][-1]["status"] == "available"
    validate_rainfall_reference_artifact(second_root)

    with pytest.raises(RainfallArtifactError, match="existing output plan differs"):
        build_rainfall_reference_artifact(
            output_dir=first_root,
            target_months=("2026-01",),
            generated_at=GENERATED_AT,
            accessed_at=ACCESSED_AT,
            fetch_month=unexpected_fetch,
            generation_command=GENERATION_COMMAND,
            repository_root=REPOSITORY_ROOT,
        )

    january_path = first_root / "windows/chirps-v2.0.2026.01.araripe.npy"
    january_path.write_bytes(january_path.read_bytes() + b"tamper")
    with pytest.raises(RainfallArtifactError, match="checksum"):
        validate_rainfall_reference_artifact(first_root)
