"""Regression tests for the authoritative 72-object baseline contract."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from config import settings
from src.detection.baseline_manifest import (
    BASELINE_VERSION,
    BaselineAuditError,
    audit_baseline_directory,
    build_manifest,
    expected_filenames,
    inventory_sha256,
    load_manifest,
    parse_baseline_filename,
    validate_manifest,
)


def _write_raster(path: Path, value: float, *, transform=None) -> None:
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
        # A tiny synthetic grid covering part of the real extent is sufficient
        # for structural tests; full extent coverage is exercised by the
        # checked-in production manifest.
        transform=transform or from_origin(300000, 9200000, 20, 20),
        nodata=np.nan,
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="deflate",
    ) as dst:
        dst.write(data, 1)


def test_exact_inventory_and_historical_mean_label():
    names = expected_filenames()
    assert len(names) == 72
    assert len(set(names)) == 72
    parsed = parse_baseline_filename("ndmi_month07_mean.tif")
    assert parsed == {
        "index": "ndmi",
        "month": 7,
        "filename_statistic": "mean",
        "statistic": "median",
    }


def test_checked_in_manifest_is_authoritative_and_matches_runtime_version():
    manifest = load_manifest(settings.BASELINE_MANIFEST_PATH)
    assert manifest["baseline_version"] == settings.BASELINE_VERSION == BASELINE_VERSION
    assert manifest["aggregate"]["object_count"] == 72
    assert manifest["aggregate"]["range_violation_pixels"] == 0
    assert manifest["decision"]["rebuild_required"] is False
    assert manifest["source"]["provenance_completeness"]["status"] == "partial"
    assert manifest["source"]["years"] == settings.BASELINE_SOURCE_YEARS
    assert (
        manifest["source"]["scene_cloud_filter_percent"]
        == settings.BASELINE_MAX_CLOUD_COVER
    )
    assert manifest["source"]["scl_clear_classes"] == settings.BASELINE_SCL_CLEAR_CLASSES
    assert (
        manifest["source"]["generator"]["generation_bounds_epsg4326"]
        == settings.BASELINE_GENERATION_BOUNDS
    )
    assert (
        manifest["raster_contract"]["pixel_size"]
        == [settings.BASELINE_RESOLUTION, settings.BASELINE_RESOLUTION]
    )


def test_manifest_rejects_inventory_checksum_drift():
    manifest = json.loads(settings.BASELINE_MANIFEST_PATH.read_text())
    manifest["objects"][0]["sha256"] = "0" * 64
    with pytest.raises(BaselineAuditError, match="inventory checksum"):
        validate_manifest(manifest)


def test_inventory_hash_is_order_independent():
    objects = [
        {"key": "baselines/b.tif", "bytes": 2, "sha256": "b" * 64},
        {"key": "baselines/a.tif", "bytes": 1, "sha256": "a" * 64},
    ]
    assert inventory_sha256(objects) == inventory_sha256(reversed(objects))


def test_audit_rejects_incomplete_local_set(tmp_path):
    _write_raster(tmp_path / expected_filenames()[0], 0.1)
    with pytest.raises(BaselineAuditError, match="exact canonical 72"):
        audit_baseline_directory(tmp_path)


def test_build_manifest_rejects_incomplete_object_evidence():
    with pytest.raises(BaselineAuditError, match="incomplete"):
        build_manifest([], audit_date="2026-07-28")


def test_production_loader_rejects_unmanifested_bytes(tmp_path, monkeypatch):
    from src.detection import baseline

    filename = "ndmi_month07_mean.tif"
    _write_raster(tmp_path / filename, 0.1)
    monkeypatch.setattr(baseline, "BASELINES_DIR", tmp_path)
    monkeypatch.setattr(baseline, "BASELINE_MANIFEST_PATH", settings.BASELINE_MANIFEST_PATH)
    baseline._verify_authoritative_file.cache_clear()
    with pytest.raises(ValueError, match="size does not match"):
        baseline.load_baseline("ndmi", 7, "mean", baselines_dir=tmp_path)
