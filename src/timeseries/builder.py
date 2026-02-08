"""Build multi-year pixel and regional time series from satellite imagery."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xarray as xr
from loguru import logger

from config.settings import TIMESERIES_DIR

DB_PATH = TIMESERIES_DIR / "timeseries.db"


def init_database(db_path: Path = DB_PATH) -> None:
    """Initialize the SQLite database for time series storage.

    Creates the tables if they don't exist.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS regional_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, index_name, region)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            total_alerts INTEGER,
            total_area_ha REAL,
            high_confidence INTEGER,
            medium_confidence INTEGER,
            low_confidence INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_regional_date
        ON regional_stats(date, index_name)
    """)

    conn.commit()
    conn.close()
    logger.debug("Database initialized at {}", db_path)


def store_regional_stats(
    date: str,
    index_name: str,
    index_data: xr.DataArray,
    region: str = "full_aoi",
    db_path: Path = DB_PATH,
) -> None:
    """Compute and store regional statistics for a single observation.

    Parameters
    ----------
    date : str
        Observation date (YYYY-MM-DD).
    index_name : str
        Name of the vegetation index.
    index_data : xr.DataArray
        Index raster for the region.
    region : str
        Region identifier.
    db_path : Path
        Path to SQLite database.
    """
    init_database(db_path)

    values = index_data.values.flatten()
    valid = values[~np.isnan(values)]

    if len(valid) == 0:
        logger.warning("No valid pixels for {} on {}", index_name, date)
        return

    stats = {
        "date": date,
        "index_name": index_name,
        "region": region,
        "mean": float(np.mean(valid)),
        "median": float(np.median(valid)),
        "std": float(np.std(valid)),
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "pct_valid": float(len(valid) / len(values) * 100),
        "n_pixels": int(len(valid)),
    }

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO regional_stats
        (date, index_name, region, mean, median, std, min, max, pct_valid, n_pixels)
        VALUES (:date, :index_name, :region, :mean, :median, :std, :min, :max,
                :pct_valid, :n_pixels)
        """,
        stats,
    )

    conn.commit()
    conn.close()
    logger.debug("Stored stats for {} {} on {}", region, index_name, date)


def store_alert_stats(
    date: str,
    summary: dict,
    db_path: Path = DB_PATH,
) -> None:
    """Store alert summary statistics.

    Parameters
    ----------
    date : str
        Detection date.
    summary : dict
        Output of alerts.summarize_alerts().
    db_path : Path
        Path to SQLite database.
    """
    init_database(db_path)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO alert_stats
        (date, total_alerts, total_area_ha, high_confidence, medium_confidence,
         low_confidence)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            date,
            summary["total_alerts"],
            summary["total_area_ha"],
            summary["by_confidence"]["high"],
            summary["by_confidence"]["medium"],
            summary["by_confidence"]["low"],
        ),
    )

    conn.commit()
    conn.close()


def load_timeseries(
    index_name: str,
    region: str = "full_aoi",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> pd.DataFrame:
    """Load regional time series from the database.

    Parameters
    ----------
    index_name : str
        Vegetation index name.
    region : str
        Region identifier.
    start_date : str, optional
        Start date filter (inclusive).
    end_date : str, optional
        End date filter (inclusive).
    db_path : Path
        Database path.

    Returns
    -------
    pd.DataFrame
        Time series with columns: date, mean, median, std, min, max, etc.
    """
    conn = sqlite3.connect(str(db_path))

    query = """
        SELECT date, mean, median, std, min, max, pct_valid, n_pixels
        FROM regional_stats
        WHERE index_name = ? AND region = ?
    """
    params = [index_name, region]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)

    query += " ORDER BY date"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])

    return df


def load_alert_timeseries(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> pd.DataFrame:
    """Load alert statistics time series."""
    conn = sqlite3.connect(str(db_path))

    query = "SELECT * FROM alert_stats WHERE 1=1"
    params = []

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)

    query += " ORDER BY date"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])

    return df
