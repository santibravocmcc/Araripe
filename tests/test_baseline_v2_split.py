"""Baseline 2.0.0 export splitter regressions (Package 2A.6C).

The v1 splitter is audit material for the accepted 1.0.0 generation and stays
unchanged.  These tests pin the two behaviours a v2 rebuild cannot inherit
from it: it must be impossible to write into the v1 directory, and an
out-of-contract statistic must fail closed instead of being silently masked
into a manifest that then validates.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from click.testing import CliRunner
from rasterio.transform import from_origin

from config import settings
from src.processing.baseline_rebuild_v2 import (
    REBUILD_EXPORT_BAND_NAMES,
    STATISTIC_EXPORT_SENTINEL,
    contribution_count_filename,
    month_export_filename,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:is_tiled will be removed:PendingDeprecationWarning"
)


def _load_cli():
    path = (
        Path(__file__).resolve().parent.parent
        / "scripts"
        / "split_baseline_v2_exports.py"
    )
    spec = importlib.util.spec_from_file_location(
        "split_baseline_v2_exports", path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_export(
    path: Path,
    *,
    ndmi_median=0.30,
    counts=3,
    masked_pixel=False,
    band_names=REBUILD_EXPORT_BAND_NAMES,
):
    """Write a synthetic nine-band monthly export on a 2x2 grid."""

    shape = (2, 2)
    planes = []
    for name in REBUILD_EXPORT_BAND_NAMES:
        if name.endswith("_count"):
            plane = np.full(shape, float(counts), dtype="float32")
        elif name == "ndmi_median":
            plane = np.full(shape, float(ndmi_median), dtype="float32")
        elif name.endswith("_std"):
            plane = np.full(shape, 0.05, dtype="float32")
        else:
            plane = np.full(shape, 0.20, dtype="float32")
        if masked_pixel:
            # Earth Engine unmasks statistics to the sentinel and counts to 0.
            plane[0, 0] = 0.0 if name.endswith("_count") else (
                STATISTIC_EXPORT_SENTINEL
            )
        planes.append(plane)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=shape[1],
        height=shape[0],
        count=len(planes),
        dtype="float32",
        crs="EPSG:32724",
        transform=from_origin(300000, 9200000, 20, 20),
        nodata=np.nan,
    ) as dst:
        for position, plane in enumerate(planes, start=1):
            dst.write(plane, position)
            dst.set_band_description(position, band_names[position - 1])


def _run(module, tmp_path, in_dir, **overrides):
    args = [
        "--in-dir",
        str(in_dir),
        "--out-dir",
        str(overrides.get("out_dir", tmp_path / "out")),
        "--counts-dir",
        str(overrides.get("counts_dir", tmp_path / "counts")),
    ]
    if "tolerance" in overrides:
        args += ["--tolerance", str(overrides["tolerance"])]
    return CliRunner().invoke(module.main, args)


@pytest.fixture
def exports(tmp_path):
    in_dir = tmp_path / "exports"
    in_dir.mkdir()
    return in_dir


def test_split_writes_six_cogs_and_three_count_rasters(tmp_path, exports):
    module = _load_cli()
    _write_export(exports / month_export_filename(4), counts=3)
    result = _run(module, tmp_path, exports)
    assert result.exit_code == 0, result.output

    out_dir = tmp_path / "out"
    counts_dir = tmp_path / "counts"
    for index in ("evi2", "nbr", "ndmi"):
        for statistic in ("mean", "std"):
            assert (out_dir / f"{index}_month04_{statistic}.tif").exists()
        assert (counts_dir / contribution_count_filename(index, 4)).exists()
    # Count rasters stay out of the audited inventory directory.
    assert sorted(p.name for p in out_dir.glob("*.tif")) == sorted(
        f"{i}_month04_{s}.tif"
        for i in ("evi2", "nbr", "ndmi")
        for s in ("mean", "std")
    )
    with rasterio.open(counts_dir / contribution_count_filename("ndmi", 4)) as src:
        assert src.dtypes[0] == "int16"
        assert src.nodata is None
        assert int(src.read(1).min()) == 3


def test_split_restores_the_sentinel_and_records_the_zero_tail(
    tmp_path, exports
):
    module = _load_cli()
    _write_export(exports / month_export_filename(5), masked_pixel=True)
    result = _run(module, tmp_path, exports)
    assert result.exit_code == 0, result.output

    with rasterio.open(tmp_path / "out" / "ndmi_month05_mean.tif") as src:
        values = src.read(1)
    assert np.isnan(values[0, 0])
    assert np.isfinite(values[1, 1])

    evidence = json.loads(
        (tmp_path / "counts" / "contribution_counts.json").read_text()
    )
    block = evidence["months"]["5"]["contribution_counts"]["ndmi"]
    assert block["pixels_with_zero_contributions"] == 1
    assert block["minimum"] == 0
    assert block["total_pixels"] == 4
    # The identity the manifest validator enforces: finite statistics exactly
    # where at least one composite contributed.
    assert block["total_pixels"] - block["pixels_with_zero_contributions"] == 3


def test_split_fails_closed_beyond_the_range_tolerance(tmp_path, exports):
    module = _load_cli()
    # NDMI is a normalized difference bounded to [-1, 1]; 1.2 is a scientific
    # signal. The v1 splitter would have silently masked it (|v| > 1.5 only).
    _write_export(exports / month_export_filename(6), ndmi_median=1.2)
    result = _run(module, tmp_path, exports)
    assert result.exit_code != 0
    assert "outside the accepted range" in result.output
    assert "investigate the composite" in result.output
    assert not (tmp_path / "out" / "ndmi_month06_mean.tif").exists()


def test_split_clamps_only_within_the_numerical_tolerance(tmp_path, exports):
    module = _load_cli()
    _write_export(exports / month_export_filename(7), ndmi_median=1.0 + 4e-7)
    result = _run(module, tmp_path, exports)
    assert result.exit_code == 0, result.output
    assert "clamped" in result.output
    with rasterio.open(tmp_path / "out" / "ndmi_month07_mean.tif") as src:
        assert float(src.read(1).max()) == pytest.approx(1.0)


def test_split_refuses_the_immutable_v1_directory(tmp_path, exports):
    module = _load_cli()
    _write_export(exports / month_export_filename(8))
    result = _run(
        module, tmp_path, exports, out_dir=settings.BASELINES_DIR
    )
    assert result.exit_code != 0
    assert "immutable baseline 1.0.0 directory" in result.output

    result = _run(
        module,
        tmp_path,
        exports,
        counts_dir=Path(settings.BASELINES_DIR) / "counts",
    )
    assert result.exit_code != 0
    assert "immutable baseline 1.0.0 directory" in result.output


def test_split_refuses_foreign_and_v1_export_names(tmp_path, exports):
    module = _load_cli()
    _write_export(exports / "araripe_baseline_month08.tif")
    result = _run(module, tmp_path, exports)
    assert result.exit_code != 0
    assert "canonical baseline 2.0.0 monthly export name" in result.output


def test_split_evidence_merges_across_incremental_runs(tmp_path, exports):
    module = _load_cli()
    _write_export(exports / month_export_filename(1))
    assert _run(module, tmp_path, exports).exit_code == 0
    (exports / month_export_filename(1)).unlink()

    _write_export(exports / month_export_filename(2))
    assert _run(module, tmp_path, exports).exit_code == 0

    evidence = json.loads(
        (tmp_path / "counts" / "contribution_counts.json").read_text()
    )
    # Month-by-month execution is the disk-bounded path; it must accumulate.
    assert sorted(evidence["months"]) == ["1", "2"]


def test_split_rejects_a_wrong_band_count(tmp_path, exports):
    module = _load_cli()
    path = exports / month_export_filename(9)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=6,
        dtype="float32",
        crs="EPSG:32724",
        transform=from_origin(300000, 9200000, 20, 20),
    ) as dst:
        for position in range(1, 7):
            dst.write(np.full((2, 2), 0.2, dtype="float32"), position)
    result = _run(module, tmp_path, exports)
    assert result.exit_code != 0
    assert "expected 9 bands" in result.output
