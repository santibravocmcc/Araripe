"""Read-only audit helpers for legacy and candidate time-series databases."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

LEGACY_REQUIRED_TABLES = {"regional_stats", "alert_stats"}
CLEAN_REQUIRED_REGIONAL_COLUMNS = {
    "generation_id",
    "acquisition_id",
    "observed_on",
    "index_name",
    "region",
    "source_collection_id",
    "scene_ids_json",
    "baseline_version",
    "algorithm_version",
    "monitoring_extent_id",
    "mean",
    "median",
    "std",
    "min",
    "max",
    "valid_pixels",
    "total_pixels",
    "coverage_fraction",
    "qa_status",
    "qa_reason",
}


class TimeseriesAuditError(ValueError):
    """Raised when a database cannot be safely audited."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    }


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def audit_legacy_database(db_path: Path) -> dict[str, Any]:
    """Classify the tracked legacy database without modifying it.

    Legacy rows cannot be assigned to an accepted generation when they lack
    acquisition, baseline, algorithm, extent, source-scene, and QA identities.
    The audit therefore reports evidence but quarantines the source as a whole.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise TimeseriesAuditError(f"time-series database not found: {db_path}")

    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        tables = _table_names(conn)
        missing_tables = sorted(LEGACY_REQUIRED_TABLES - tables)
        if missing_tables:
            raise TimeseriesAuditError(
                f"legacy database missing required tables: {missing_tables}"
            )

        regional_columns = _columns(conn, "regional_stats")
        alert_columns = _columns(conn, "alert_stats")
        regional_count, regional_min, regional_max = conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM regional_stats"
        ).fetchone()
        alert_count, alert_min, alert_max = conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM alert_stats"
        ).fetchone()
        distinct_dates = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM regional_stats"
        ).fetchone()[0]
        indices = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT index_name FROM regional_stats ORDER BY index_name"
            )
        ]
        write_days = [
            {"day": row[0], "rows": row[1], "min_date": row[2], "max_date": row[3]}
            for row in conn.execute(
                """
                SELECT substr(created_at, 1, 10), COUNT(*), MIN(date), MAX(date)
                FROM regional_stats
                GROUP BY substr(created_at, 1, 10)
                ORDER BY substr(created_at, 1, 10)
                """
            )
        ]
        low_coverage_rows = conn.execute(
            "SELECT COUNT(*) FROM regional_stats WHERE pct_valid < 10"
        ).fetchone()[0]
        low_coverage_dates = conn.execute(
            "SELECT COUNT(DISTINCT date) FROM regional_stats WHERE pct_valid < 10"
        ).fetchone()[0]
        inconsistent_coverage_dates = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT date
                FROM regional_stats
                GROUP BY date
                HAVING MAX(pct_valid) - MIN(pct_valid) > 0.000001
            )
            """
        ).fetchone()[0]
        out_of_range_evi2_rows = conn.execute(
            """
            SELECT COUNT(*)
            FROM regional_stats
            WHERE index_name = 'evi2'
              AND (
                mean < -1.5 OR mean > 1.5 OR
                median < -1.5 OR median > 1.5 OR
                min < -1.5 OR max > 1.5
              )
            """
        ).fetchone()[0]
        per_index = [
            {
                "index": row[0],
                "rows": row[1],
                "minimum_mean": row[2],
                "maximum_mean": row[3],
                "minimum_coverage_percent": row[4],
                "maximum_coverage_percent": row[5],
            }
            for row in conn.execute(
                """
                SELECT index_name, COUNT(*), MIN(mean), MAX(mean),
                       MIN(pct_valid), MAX(pct_valid)
                FROM regional_stats
                GROUP BY index_name
                ORDER BY index_name
                """
            )
        ]
    finally:
        conn.close()

    missing_clean_columns = sorted(
        CLEAN_REQUIRED_REGIONAL_COLUMNS - set(regional_columns)
    )
    issues = [
        "Rows do not identify a processing generation or canonical acquisition.",
        "Rows do not record source collection and provider-native scene IDs.",
        "Rows do not record baseline, algorithm, or monitoring-extent versions.",
        "Rows do not carry an explicit per-date QA status and reason.",
    ]
    if low_coverage_rows:
        issues.append(
            f"{low_coverage_rows} regional rows across {low_coverage_dates} dates "
            "have under 10% valid coverage."
        )
    if inconsistent_coverage_dates:
        issues.append(
            f"{inconsistent_coverage_dates} dates report inconsistent coverage "
            "between indices."
        )
    if out_of_range_evi2_rows:
        issues.append(
            f"{out_of_range_evi2_rows} EVI2 rows exceed the accepted [-1.5, 1.5] "
            "splitter range."
        )

    return {
        "audit_schema_version": "1.0.0",
        "source": {
            "path_label": "data/timeseries/timeseries.db",
            "bytes": db_path.stat().st_size,
            "sha256": _sha256_file(db_path),
        },
        "legacy_schema": {
            "regional_stats_columns": regional_columns,
            "alert_stats_columns": alert_columns,
            "missing_clean_regional_columns": missing_clean_columns,
        },
        "inventory": {
            "regional_rows": regional_count,
            "regional_dates": distinct_dates,
            "regional_min_date": regional_min,
            "regional_max_date": regional_max,
            "alert_rows": alert_count,
            "alert_min_date": alert_min,
            "alert_max_date": alert_max,
            "indices": indices,
            "write_day_groups": write_days,
            "per_index": per_index,
        },
        "quality": {
            "low_coverage_rows_under_10_percent": low_coverage_rows,
            "low_coverage_dates_under_10_percent": low_coverage_dates,
            "inconsistent_coverage_dates": inconsistent_coverage_dates,
            "out_of_range_evi2_rows": out_of_range_evi2_rows,
        },
        "disposition": {
            "classification": "quarantined_mixed_generation_audit",
            "publishable": False,
            "row_level_salvage_permitted": False,
            "reason": (
                "The missing provenance/version fields make row-level generation "
                "assignment unverifiable. Preserve this database unchanged as audit "
                "material; build the corrected 2026 series from empty chronology in a "
                "new generation."
            ),
        },
        "issues": issues,
    }
