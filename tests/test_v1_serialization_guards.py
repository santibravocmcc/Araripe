"""V2 scientific records must never enter audit-only v1 serializers."""

import sqlite3
from pathlib import Path

import pytest

from src.detection.identity import write_acquisition_metadata
from src.detection.identity_v2 import create_acquisition_v2
from src.detection.persistence import save_persistence_state
from src.detection.scene_quality import SceneQuality, save_scene_quality
from src.timeseries.schema import (
    connect_database,
    init_clean_database,
    register_generation,
)


def _acquisition_v2():
    return create_acquisition_v2(
        run_manifest_id="run-v2-" + "1" * 64,
        run_manifest_sha256="2" * 64,
        collection_id="COPERNICUS_S2_SR_HARMONIZED",
        platform="S2A",
        datatake_id="GS2A_20260407T131241",
        acquisition_timestamp_utc="2026-04-07T13:12:41Z",
        scene_ids=["scene-a"],
        monitoring_extent_id="araripe-implementation-rectangle-v1",
        composite_method_id="coverage-ranked-first-valid-v2",
        grid_id="araripe-detector-grid-v2",
    )


def test_v1_acquisition_writer_rejects_v2_payload(tmp_path: Path):
    destination = tmp_path / "acquisition.json"

    with pytest.raises(TypeError, match="v1 acquisition writer"):
        write_acquisition_metadata(destination, _acquisition_v2())

    assert not destination.exists()


def test_v1_scene_quality_writer_rejects_v2_acquisition(tmp_path: Path):
    quality = SceneQuality(
        scene_decision="accepted",
        valid_coverage_fraction=1.0,
        minimum_required_fraction=0.3,
        alert_fraction_of_valid=0.0,
        anomaly_reject_fraction=0.3,
        valid_pixel_count=1,
        total_pixel_count=1,
        alert_pixel_count=0,
        qa_flags=(),
        rejection_reason=None,
    )

    with pytest.raises(ValueError, match="acq-v1-"):
        save_scene_quality(
            quality,
            output_dir=tmp_path,
            record_id="v2-forbidden",
            acquisition_id=_acquisition_v2().acquisition_id,
            observed_on="2026-04-07",
            scene_ids=["scene-a"],
        )

    assert not list(tmp_path.iterdir())


def test_v1_timeseries_registration_rejects_v2_generation(tmp_path: Path):
    database = tmp_path / "audit-v1.db"
    init_clean_database(database)

    with pytest.raises(ValueError, match="audit-only v1"):
        register_generation(
            database,
            generation_id="gen-v2-" + "3" * 64,
            algorithm_version="2.0.0",
            baseline_version="2.0.0",
            monitoring_extent_id="araripe-implementation-rectangle-v1",
            monitoring_extent_sha256="4" * 64,
            source_collection_id="COPERNICUS/S2_SR_HARMONIZED",
            composition_method_id="coverage-ranked-first-valid-v2",
            reflectance_scaling=True,
        )


def test_v1_timeseries_table_rejects_v2_acquisition_id(tmp_path: Path):
    database = tmp_path / "audit-v1.db"
    init_clean_database(database)
    register_generation(
        database,
        generation_id="gen-audit-v1",
        algorithm_version="1.0.0",
        baseline_version="1.0.0",
        monitoring_extent_id="araripe-implementation-rectangle-v1",
        monitoring_extent_sha256="4" * 64,
        source_collection_id="COPERNICUS/S2_SR_HARMONIZED",
        composition_method_id="daily-mosaic-v1",
        reflectance_scaling=True,
    )
    connection = connect_database(database)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO acquisitions (
                    generation_id, observed_on, acquisition_id,
                    source_collection_id, scene_ids_json,
                    source_metadata_sha256, valid_pixels, total_pixels,
                    coverage_fraction, qa_status, qa_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "gen-audit-v1",
                    "2026-04-07",
                    _acquisition_v2().acquisition_id,
                    "COPERNICUS/S2_SR_HARMONIZED",
                    '["scene-a"]',
                    "5" * 64,
                    1,
                    1,
                    1.0,
                    "accepted",
                    None,
                ),
            )
    finally:
        connection.close()


def test_v1_persistence_writer_rejects_v2_state_before_writing(tmp_path: Path):
    destination = tmp_path / "persistence-v1.geojson"

    with pytest.raises(TypeError, match="audit-only v1 writer"):
        save_persistence_state(
            {
                "schema_version": "2.0.0",
                "state_id": "state-v2-" + "6" * 64,
            },
            destination,
        )

    assert not destination.exists()
