"""D4: the green time-series rows and the clean database built from them."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from src.timeseries import green_rows as gr

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "green_timeseries.py"


def _script():
    spec = importlib.util.spec_from_file_location("green_timeseries", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stats(valid=900, total=1000, mean=0.2):
    return {name: {"valid_pixels": valid, "total_pixels": total, "mean": mean,
                   "median": mean, "std": 0.05, "min": -0.5, "max": 0.9}
            for name in gr.SERIES_INDICES}


def _acq(n, observed_on, datatake):
    return {"acquisition_id": f"acq-v3-{n:064d}", "observed_on": observed_on,
            "datatake_id": datatake, "scene_ids": [f"S/{datatake}/T24MUS"],
            "identity_inputs_sha256": f"{n:064d}",
            "composite_method_id": "datatake_mosaic-v1",
            "collection_id": "COPERNICUS/S2_SR_HARMONIZED"}


def _row(acq, status, sha=None, code=None):
    return {"acquisition_id": acq["acquisition_id"], "observed_on": acq["observed_on"],
            "status": status, "output": {"artifact_sha256": sha},
            "reason": {"code": code} if code else None}


def _composite(directory: Path, acq, content: bytes) -> str:
    path = directory / gr.COMPOSITE_NAME.format(
        observed_on=acq["observed_on"], datatake_id=acq["datatake_id"])
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _ledger(expected, rows):
    return {"ledger_id": "pl-v3-" + "a" * 64, "run_manifest_id": "run-v3-x",
            "monitoring_extent_id": "araripe-implementation-rectangle-v1",
            "algorithm_version": "1.1.0", "expected_acquisitions": expected,
            "terminal_rows": rows}


def _rows(ledger, directory, measure=lambda path: _stats()):
    return gr.run_rows(ledger, directory, baseline_version="2.1.0",
                       algorithm_version="1.1.0", measure=measure)


# ── the statistics are the blue writer's ─────────────────────────────────────


def test_band_statistics_are_store_regional_stats_values(tmp_path):
    """Same pixels, same numbers: the blue writer's own function on the band.

    The values that differ between the series must come from composition, not
    from arithmetic. float32, as ``rioxarray`` hands the blue path the band.
    """

    from src.timeseries.builder import store_regional_stats_values

    rng = np.random.default_rng(7)
    band = rng.normal(0.2, 0.1, 5000).astype("float32")
    band[:700] = -9999.0  # the export fill, restored to NaN by _load_composite
    db = tmp_path / "blue.db"
    expected = np.where(band > -9990, band, np.nan)
    store_regional_stats_values("2026-01-02", "ndmi", expected[~np.isnan(expected)],
                                total_pixels=band.size, db_path=db)
    blue = sqlite3.connect(db).execute(
        "select mean, median, std, min, max, n_pixels, pct_valid from regional_stats"
    ).fetchone()
    green = gr.band_statistics(band)
    assert (green["mean"], green["median"], green["std"], green["min"],
            green["max"], green["valid_pixels"]) == blue[:6]
    assert green["valid_pixels"] / green["total_pixels"] * 100 == pytest.approx(blue[6])


def test_an_all_fill_band_has_no_statistics():
    assert gr.band_statistics(np.full(10, -9999.0, "float32"))["mean"] is None


# ── the ledger decides which composites exist ────────────────────────────────


def test_accepted_and_quality_rejected_rows_low_coverage_none_failed_absent(tmp_path):
    a, q, low, failed = (_acq(1, "2026-01-02", "D1"), _acq(2, "2026-01-04", "D2"),
                         _acq(3, "2026-01-06", "D3"), _acq(4, "2026-01-08", "D4"))
    sha = _composite(tmp_path, a, b"accepted")
    _composite(tmp_path, q, b"rejected-quality")
    _composite(tmp_path, low, b"a stray file the ledger does not name")
    document = _rows(_ledger([a, q, low, failed], [
        _row(a, "complete_zero_alerts", sha),
        _row(q, "rejected_quality", code="scene-anomaly-fraction-too-high"),
        _row(low, "rejected_low_coverage"),
        _row(failed, "failed_download"),
    ]), tmp_path)
    by_date = {x["observed_on"]: x for x in document["acquisitions"]}
    assert sorted(by_date) == ["2026-01-02", "2026-01-04"]
    assert by_date["2026-01-02"]["qa_status"] == "accepted"
    assert by_date["2026-01-02"]["qa_reason"] is None
    assert by_date["2026-01-04"]["qa_status"] == "rejected_quality"
    assert by_date["2026-01-04"]["qa_reason"] == "scene-anomaly-fraction-too-high"
    assert document["absent"] == [{"acquisition_id": failed["acquisition_id"],
                                   "observed_on": "2026-01-08",
                                   "status": "failed_download"}]


def test_an_accepted_composite_that_is_not_the_sealed_one_is_refused(tmp_path):
    a = _acq(1, "2026-01-02", "D1")
    _composite(tmp_path, a, b"other pixels")
    with pytest.raises(gr.RowsRejected, match="the ledger sealed"):
        _rows(_ledger([a], [_row(a, "complete_with_alerts", "f" * 64)]), tmp_path)


def test_a_missing_composite_is_refused_not_skipped(tmp_path):
    a = _acq(1, "2026-01-02", "D1")
    with pytest.raises(gr.RowsRejected, match="no composite"):
        _rows(_ledger([a], [_row(a, "rejected_quality", code="x")]), tmp_path)


def test_two_composites_on_one_date_keep_one_and_name_the_other(tmp_path):
    accepted, quality = _acq(1, "2026-04-07", "DA"), _acq(2, "2026-04-07", "DB")
    sha = _composite(tmp_path, accepted, b"a")
    _composite(tmp_path, quality, b"b")
    # the quality-rejected one has MORE valid pixels and still loses
    pixels = {"DA": 100, "DB": 900}
    document = _rows(
        _ledger([accepted, quality], [_row(accepted, "complete_with_alerts", sha),
                                      _row(quality, "rejected_quality", code="x")]),
        tmp_path,
        measure=lambda path: _stats(valid=pixels[path.stem.split("_")[-1]]))
    assert [x["acquisition_id"] for x in document["acquisitions"]] == [accepted["acquisition_id"]]
    assert document["superseded"] == [{"observed_on": "2026-04-07",
                                       "acquisition_id": quality["acquisition_id"],
                                       "kept": accepted["acquisition_id"]}]


def test_the_generation_is_the_configuration_and_not_the_run():
    one = gr.generation_identity(algorithm_version="1.1.0", baseline_version="2.1.0",
                                 monitoring_extent_id="e", source_collection_id="c",
                                 composition_method_id="datatake_mosaic-v1")
    assert one == gr.generation_identity(
        algorithm_version="1.1.0", baseline_version="2.1.0", monitoring_extent_id="e",
        source_collection_id="c", composition_method_id="datatake_mosaic-v1")
    other = dict(one, baseline_version="2.2.0")
    assert gr.generation_identity(**{k: other[k] for k in (
        "algorithm_version", "baseline_version", "monitoring_extent_id",
        "source_collection_id", "composition_method_id")})["generation_id"] != one["generation_id"]
    assert one["generation_id"].startswith("gen-g1-")


# ── the clean database ───────────────────────────────────────────────────────


def _document(tmp_path, statuses):
    expected, rows = [], []
    for n, (observed_on, status) in enumerate(statuses, 1):
        acq = _acq(n, observed_on, f"D{n}")
        sha = _composite(tmp_path, acq, f"pixels {n}".encode())
        expected.append(acq)
        rows.append(_row(acq, status, sha if status != "rejected_quality" else None,
                         code="x" if status == "rejected_quality" else None))
    return _rows(_ledger(expected, rows), tmp_path)


def test_apply_writes_the_clean_schema_and_a_repeat_adds_nothing(tmp_path):
    document = _document(tmp_path, [("2026-01-02", "complete_with_alerts"),
                                    ("2026-01-04", "rejected_quality")])
    db = tmp_path / "green.db"
    gr.apply_rows(db, [document])
    gr.apply_rows(db, [document])
    connection = sqlite3.connect(db)
    assert connection.execute("select count(*) from acquisitions").fetchone() == (2,)
    assert connection.execute("select count(*) from regional_stats_v1").fetchone() == (6,)
    assert connection.execute(
        "select qa_status, count(*) from regional_stats_v1 group by 1 order by 1"
    ).fetchall() == [("accepted", 3), ("rejected_quality", 3)]
    tables = {r[0] for r in connection.execute("select name from sqlite_master where type='table'")}
    assert "regional_stats" not in tables


def test_a_later_run_may_replace_a_dates_acquisition(tmp_path):
    """The foreign key from regional_stats_v1 forbids INSERT OR REPLACE of the parent."""

    db = tmp_path / "green.db"
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    gr.apply_rows(db, [_document(tmp_path / "a", [("2026-01-02", "rejected_quality")])])
    later = _document(tmp_path / "b", [("2026-01-02", "complete_with_alerts")])
    later["acquisitions"][0]["acquisition_id"] = "acq-v3-" + "9" * 64
    gr.apply_rows(db, [later])
    connection = sqlite3.connect(db)
    assert connection.execute(
        "select distinct acquisition_id, qa_status from regional_stats_v1").fetchall() == [
        ("acq-v3-" + "9" * 64, "accepted")]


def test_build_refuses_the_quarantined_legacy_database(tmp_path):
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps(_document(tmp_path, [("2026-01-02", "complete_with_alerts")])))
    with pytest.raises(SystemExit, match="quarantined"):
        _script().main(["build", "--db", str(tmp_path / "timeseries.db"), str(rows)])
    assert not (tmp_path / "timeseries.db").exists()


# ── the constants are the producers' own ────────────────────────────────────


def _literal(path: Path, name: str):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not in {path}")


def test_band_order_is_the_exports_and_the_loaders():
    assert list(gr.BAND_ORDER) == _literal(ROOT / "scripts" / "replay_2026.py", "BANDS")
    assert list(gr.BAND_ORDER) == _literal(
        ROOT / "scripts" / "run_detection_from_gee.py", "_BAND_ORDER")


def test_composite_name_is_the_exports():
    spec = importlib.util.spec_from_file_location(
        "build_detection_gee", ROOT / "scripts" / "build_detection_gee.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    name = module.composite_name("datatake", observed_on="2026-01-02", datatake_id="D")
    assert gr.COMPOSITE_NAME.format(observed_on="2026-01-02", datatake_id="D") == name + ".tif"


def test_extent_hash_is_the_baseline_manifests():
    from src.detection.baseline_manifest import MONITORING_EXTENT_BOUNDS_SHA256
    assert gr.MONITORING_EXTENT_BOUNDS_SHA256 == MONITORING_EXTENT_BOUNDS_SHA256
