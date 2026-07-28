"""Clean-generation SQLite schema for future 2026 time-series rebuilding.

Package 2A.2 defines this schema but deliberately does not migrate or replay the
tracked legacy database. A later replay creates a new database from empty
chronology and binds every date to one generation and one acquisition.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

TIMESERIES_SCHEMA_VERSION = "1.0.0"
GENERATION_STATUSES = ("candidate", "accepted", "quarantined")
ACQUISITION_QA_STATUSES = (
    "accepted",
    "rejected_low_coverage",
    "rejected_quality",
)

_SCHEMA_SQL = f"""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS processing_generations (
    generation_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL CHECK (schema_version = '{TIMESERIES_SCHEMA_VERSION}'),
    release_id TEXT,
    algorithm_version TEXT NOT NULL,
    baseline_version TEXT NOT NULL,
    monitoring_extent_id TEXT NOT NULL,
    monitoring_extent_sha256 TEXT NOT NULL
        CHECK (length(monitoring_extent_sha256) = 64),
    source_collection_id TEXT NOT NULL,
    composition_method_id TEXT NOT NULL,
    reflectance_scaling INTEGER NOT NULL CHECK (reflectance_scaling IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN {GENERATION_STATUSES}),
    quarantine_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (status = 'quarantined' AND quarantine_reason IS NOT NULL)
        OR (status != 'quarantined' AND quarantine_reason IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS acquisitions (
    generation_id TEXT NOT NULL,
    observed_on TEXT NOT NULL CHECK (
        length(observed_on) = 10
        AND substr(observed_on, 5, 1) = '-'
        AND substr(observed_on, 8, 1) = '-'
    ),
    acquisition_id TEXT NOT NULL,
    source_collection_id TEXT NOT NULL,
    scene_ids_json TEXT NOT NULL CHECK (json_valid(scene_ids_json)),
    source_metadata_sha256 TEXT NOT NULL
        CHECK (length(source_metadata_sha256) = 64),
    valid_pixels INTEGER NOT NULL CHECK (valid_pixels >= 0),
    total_pixels INTEGER NOT NULL CHECK (total_pixels > 0),
    coverage_fraction REAL NOT NULL CHECK (
        coverage_fraction >= 0.0 AND coverage_fraction <= 1.0
    ),
    qa_status TEXT NOT NULL CHECK (qa_status IN {ACQUISITION_QA_STATUSES}),
    qa_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (generation_id, observed_on),
    UNIQUE (generation_id, acquisition_id),
    FOREIGN KEY (generation_id)
        REFERENCES processing_generations(generation_id),
    CHECK (valid_pixels <= total_pixels),
    CHECK (
        abs(coverage_fraction - (CAST(valid_pixels AS REAL) / total_pixels))
        <= 0.000000001
    ),
    CHECK (
        (qa_status = 'accepted' AND qa_reason IS NULL)
        OR (qa_status != 'accepted' AND qa_reason IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS regional_stats_v1 (
    generation_id TEXT NOT NULL,
    acquisition_id TEXT NOT NULL,
    observed_on TEXT NOT NULL,
    index_name TEXT NOT NULL CHECK (index_name IN ('evi2', 'nbr', 'ndmi')),
    region TEXT NOT NULL,
    source_collection_id TEXT NOT NULL,
    scene_ids_json TEXT NOT NULL CHECK (json_valid(scene_ids_json)),
    baseline_version TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    monitoring_extent_id TEXT NOT NULL,
    mean REAL,
    median REAL,
    std REAL CHECK (std IS NULL OR std >= 0),
    min REAL,
    max REAL,
    valid_pixels INTEGER NOT NULL CHECK (valid_pixels >= 0),
    total_pixels INTEGER NOT NULL CHECK (total_pixels > 0),
    coverage_fraction REAL NOT NULL CHECK (
        coverage_fraction >= 0.0 AND coverage_fraction <= 1.0
    ),
    qa_status TEXT NOT NULL CHECK (qa_status IN {ACQUISITION_QA_STATUSES}),
    qa_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (generation_id, observed_on, index_name, region),
    FOREIGN KEY (generation_id, observed_on)
        REFERENCES acquisitions(generation_id, observed_on),
    FOREIGN KEY (generation_id, acquisition_id)
        REFERENCES acquisitions(generation_id, acquisition_id),
    CHECK (valid_pixels <= total_pixels),
    CHECK (
        abs(coverage_fraction - (CAST(valid_pixels AS REAL) / total_pixels))
        <= 0.000000001
    ),
    CHECK (
        (qa_status = 'accepted' AND valid_pixels > 0 AND qa_reason IS NULL)
        OR (qa_status != 'accepted' AND qa_reason IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS alert_stats_v1 (
    generation_id TEXT NOT NULL,
    acquisition_id TEXT NOT NULL,
    observed_on TEXT NOT NULL,
    total_alerts INTEGER NOT NULL CHECK (total_alerts >= 0),
    total_area_ha REAL NOT NULL CHECK (total_area_ha >= 0),
    high_confidence INTEGER NOT NULL CHECK (high_confidence >= 0),
    medium_confidence INTEGER NOT NULL CHECK (medium_confidence >= 0),
    low_confidence INTEGER NOT NULL CHECK (low_confidence >= 0),
    qa_status TEXT NOT NULL CHECK (qa_status IN {ACQUISITION_QA_STATUSES}),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (generation_id, observed_on),
    FOREIGN KEY (generation_id, observed_on)
        REFERENCES acquisitions(generation_id, observed_on),
    FOREIGN KEY (generation_id, acquisition_id)
        REFERENCES acquisitions(generation_id, acquisition_id),
    CHECK (
        total_alerts = high_confidence + medium_confidence + low_confidence
    ),
    CHECK (
        (qa_status = 'accepted')
        OR (total_alerts = 0 AND total_area_ha = 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_regional_v1_generation_date
ON regional_stats_v1(generation_id, observed_on, index_name);
"""


def connect_database(db_path: Path) -> sqlite3.Connection:
    """Open a clean database connection with referential checks enabled."""
    connection = sqlite3.connect(str(db_path))
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_clean_database(db_path: Path) -> None:
    """Create an empty clean-generation schema."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_database(db_path)
    try:
        connection.executescript(_SCHEMA_SQL)
        connection.commit()
    finally:
        connection.close()


def register_generation(
    db_path: Path,
    *,
    generation_id: str,
    algorithm_version: str,
    baseline_version: str,
    monitoring_extent_id: str,
    monitoring_extent_sha256: str,
    source_collection_id: str,
    composition_method_id: str,
    reflectance_scaling: bool,
    status: str = "candidate",
    quarantine_reason: str | None = None,
) -> None:
    """Register one isolated processing generation."""
    connection = connect_database(db_path)
    try:
        connection.execute(
            """
            INSERT INTO processing_generations (
                generation_id, schema_version, algorithm_version,
                baseline_version, monitoring_extent_id,
                monitoring_extent_sha256, source_collection_id,
                composition_method_id, reflectance_scaling, status,
                quarantine_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                TIMESERIES_SCHEMA_VERSION,
                algorithm_version,
                baseline_version,
                monitoring_extent_id,
                monitoring_extent_sha256,
                source_collection_id,
                composition_method_id,
                int(reflectance_scaling),
                status,
                quarantine_reason,
            ),
        )
        connection.commit()
    finally:
        connection.close()
