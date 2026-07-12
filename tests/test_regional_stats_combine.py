"""store_regional_stats_values must combine tiles into one full-AOI row.

Guards the fix for the multi-tile clobber: writing regional stats once per UTM
tile collided on UNIQUE(date, index_name, 'full_aoi') and kept only the last
tile. The combined path pools all tiles' valid pixels + total pixel counts.
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.timeseries.builder import store_regional_stats_values  # noqa: E402


def _read(db, date, index_name):
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT mean, median, std, pct_valid, n_pixels FROM regional_stats "
        "WHERE date=? AND index_name=? AND region='full_aoi'",
        (date, index_name),
    ).fetchone()
    conn.close()
    return row


def test_combined_row_covers_all_tiles(tmp_path):
    db = tmp_path / "ts.db"
    # Two tiles pooled: valid [0.1,0.2] of 4 px, plus [0.3] of 2 px.
    tile1 = np.array([0.1, 0.2], dtype="float32")
    tile2 = np.array([0.3], dtype="float32")
    combined = np.concatenate([tile1, tile2])
    store_regional_stats_values("2026-05-01", "ndmi", combined, total_pixels=6, db_path=db)

    mean, median, std, pct_valid, n_pixels = _read(db, "2026-05-01", "ndmi")
    assert n_pixels == 3                      # all tiles' valid pixels, not just the last
    assert pct_valid == 50.0                  # 3 valid / 6 total
    assert mean == pytest.approx(0.2, abs=1e-6)
    assert median == pytest.approx(0.2, abs=1e-6)


def test_ignores_nans_and_floors_total(tmp_path):
    db = tmp_path / "ts.db"
    vals = np.array([1.0, np.nan, 3.0], dtype="float32")
    # total_pixels smaller than valid count must not produce pct_valid > 100.
    store_regional_stats_values("2026-05-02", "nbr", vals, total_pixels=1, db_path=db)
    mean, median, std, pct_valid, n_pixels = _read(db, "2026-05-02", "nbr")
    assert n_pixels == 2
    assert pct_valid == 100.0
    assert mean == pytest.approx(2.0, abs=1e-6)
