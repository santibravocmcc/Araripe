"""Tests for legacy quarantine and the clean time-series generation schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.timeseries.audit import audit_legacy_database
from src.timeseries.schema import (
    TIMESERIES_SCHEMA_VERSION,
    connect_database,
    init_clean_database,
    register_generation,
)


def _legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE regional_stats (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            index_name TEXT NOT NULL,
            region TEXT NOT NULL,
            mean REAL,
            median REAL,
            std REAL,
            min REAL,
            max REAL,
            pct_valid REAL,
            n_pixels INTEGER,
            created_at TEXT
        );
        CREATE TABLE alert_stats (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            total_alerts INTEGER,
            total_area_ha REAL,
            high_confidence INTEGER,
            medium_confidence INTEGER,
            low_confidence INTEGER,
            created_at TEXT
        );
        INSERT INTO regional_stats VALUES
            (1, '2026-01-02', 'evi2', 'full_aoi', 1.8, 1.9, 0.2,
             -0.2, 2.2, 5.0, 10, '2026-04-28 00:00:00'),
            (2, '2026-01-02', 'ndmi', 'full_aoi', 0.2, 0.2, 0.1,
             -0.2, 0.4, 50.0, 100, '2026-07-14 00:00:00');
        INSERT INTO alert_stats VALUES
            (1, '2026-01-02', 1, 2.0, 1, 0, 0, '2026-07-14 00:00:00');
        """
    )
    connection.commit()
    connection.close()


def _register_candidate(db: Path) -> None:
    register_generation(
        db,
        generation_id="gen-2026-candidate-001",
        algorithm_version="1.0.0",
        baseline_version="1.0.0",
        monitoring_extent_id="araripe-implementation-rectangle-v1",
        monitoring_extent_sha256="a" * 64,
        source_collection_id="COPERNICUS/S2_SR_HARMONIZED",
        composition_method_id="daily_mosaic-v1",
        reflectance_scaling=True,
    )


def test_legacy_database_is_quarantined_as_a_whole(tmp_path):
    db = tmp_path / "legacy.db"
    _legacy_database(db)
    report = audit_legacy_database(db)
    assert report["disposition"] == {
        "classification": "quarantined_mixed_generation_audit",
        "publishable": False,
        "row_level_salvage_permitted": False,
        "reason": (
            "The missing provenance/version fields make row-level generation "
            "assignment unverifiable. Preserve this database unchanged as audit "
            "material; build the corrected 2026 series from empty chronology in a "
            "new generation."
        ),
    }
    assert report["quality"]["low_coverage_rows_under_10_percent"] == 1
    assert report["quality"]["inconsistent_coverage_dates"] == 1
    assert report["quality"]["out_of_range_evi2_rows"] == 1
    assert "baseline_version" in report["legacy_schema"]["missing_clean_regional_columns"]


def test_clean_schema_requires_generation_and_acquisition_provenance(tmp_path):
    db = tmp_path / "clean.db"
    init_clean_database(db)
    _register_candidate(db)

    connection = connect_database(db)
    generation = connection.execute(
        "SELECT schema_version, baseline_version, status "
        "FROM processing_generations"
    ).fetchone()
    assert generation == (TIMESERIES_SCHEMA_VERSION, "1.0.0", "candidate")

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO regional_stats_v1 (
                generation_id, acquisition_id, observed_on, index_name, region,
                source_collection_id, scene_ids_json, baseline_version,
                algorithm_version, monitoring_extent_id, mean, median, std,
                min, max, valid_pixels, total_pixels, coverage_fraction,
                qa_status, qa_reason
            ) VALUES (
                'gen-2026-candidate-001', 'missing-acquisition', '2026-01-02',
                'ndmi', 'full_aoi', 'COPERNICUS/S2_SR_HARMONIZED', '[]',
                '1.0.0', '1.0.0', 'araripe-implementation-rectangle-v1',
                0.1, 0.1, 0.01, 0.0, 0.2, 1, 1, 1.0, 'accepted', NULL
            )
            """
        )
    connection.close()


def test_coverage_arithmetic_and_rejection_reason_are_enforced(tmp_path):
    db = tmp_path / "clean.db"
    init_clean_database(db)
    _register_candidate(db)
    connection = connect_database(db)

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO acquisitions (
                generation_id, observed_on, acquisition_id,
                source_collection_id, scene_ids_json, source_metadata_sha256,
                valid_pixels, total_pixels, coverage_fraction, qa_status,
                qa_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "gen-2026-candidate-001",
                "2026-01-02",
                "acq-v1-example",
                "COPERNICUS/S2_SR_HARMONIZED",
                '["scene-1"]',
                "b" * 64,
                2,
                4,
                0.75,
                "rejected_low_coverage",
                None,
            ),
        )
    connection.close()


def test_quarantined_generation_requires_reason(tmp_path):
    db = tmp_path / "clean.db"
    init_clean_database(db)
    with pytest.raises(sqlite3.IntegrityError):
        register_generation(
            db,
            generation_id="bad-quarantine",
            algorithm_version="1.0.0",
            baseline_version="1.0.0",
            monitoring_extent_id="araripe-implementation-rectangle-v1",
            monitoring_extent_sha256="c" * 64,
            source_collection_id="COPERNICUS/S2_SR_HARMONIZED",
            composition_method_id="daily_mosaic-v1",
            reflectance_scaling=True,
            status="quarantined",
        )
