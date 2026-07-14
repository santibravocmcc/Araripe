"""compute_persistence_counts: consecutive-observation streak per alert."""

import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import TARGET_CRS  # noqa: E402
from src.detection.persistence import compute_persistence_counts  # noqa: E402


def _g(boxes, counts=None):
    gdf = gpd.GeoDataFrame(geometry=[box(*b) for b in boxes], crs=TARGET_CRS)
    if counts is not None:
        gdf["persistence_count"] = counts
    return gdf


def test_no_previous_all_ones():
    cur = _g([(0, 0, 100, 100), (500, 500, 600, 600)])
    s = compute_persistence_counts(cur, None)
    assert list(s) == [1, 1]


def test_streak_inherits_and_increments():
    cur = _g([(0, 0, 100, 100), (9000, 9000, 9100, 9100)])
    prev = _g([(0, 0, 100, 100)], counts=[3])  # overlapping prior has a streak of 3
    s = compute_persistence_counts(cur, prev)
    assert s.loc[cur.index[0]] == 4   # overlaps prior streak 3 -> 4
    assert s.loc[cur.index[1]] == 1   # overlaps nothing -> fresh


def test_missing_prev_count_defaults_to_one():
    cur = _g([(0, 0, 100, 100)])
    prev = _g([(0, 0, 100, 100)])  # no persistence_count column (old archive file)
    s = compute_persistence_counts(cur, prev)
    assert s.iloc[0] == 2


def test_tiny_overlap_below_threshold_not_counted():
    cur = _g([(0, 0, 100, 100)])          # area 10000
    prev = _g([(99, 99, 199, 199)], counts=[5])  # overlaps only 1x1 corner (<5%)
    s = compute_persistence_counts(cur, prev, min_overlap_frac=0.05)
    assert s.iloc[0] == 1
