"""Tests for the temporal-persistence filter."""

import geopandas as gpd
from shapely.geometry import box

from src.detection.persistence import (
    apply_persistence_to_history,
    filter_alerts_by_persistence,
)


def _gdf(boxes):
    return gpd.GeoDataFrame({"geometry": [box(*b) for b in boxes]}, crs="EPSG:32724")


def test_first_observation_confirms_nothing():
    current = _gdf([(0, 0, 100, 100)])
    out = filter_alerts_by_persistence(current, previous=None)
    assert len(out) == 0


def test_overlapping_alert_is_confirmed():
    prev = _gdf([(0, 0, 100, 100)])
    # Same footprint → confirmed.
    current = _gdf([(10, 10, 110, 110)])
    out = filter_alerts_by_persistence(current, previous=prev)
    assert len(out) == 1


def test_non_overlapping_alert_is_dropped():
    prev = _gdf([(0, 0, 100, 100)])
    # Far away → not confirmed.
    current = _gdf([(1000, 1000, 1100, 1100)])
    out = filter_alerts_by_persistence(current, previous=prev)
    assert len(out) == 0


def test_mixed_batch_keeps_only_confirmed():
    prev = _gdf([(0, 0, 100, 100)])
    current = _gdf([
        (0, 0, 100, 100),         # overlaps → keep
        (5000, 5000, 5100, 5100),  # no overlap → drop
    ])
    out = filter_alerts_by_persistence(current, previous=prev)
    assert len(out) == 1
    assert out.geometry.iloc[0].bounds == (0.0, 0.0, 100.0, 100.0)


def test_tiny_edge_touch_below_threshold_dropped():
    prev = _gdf([(0, 0, 100, 100)])
    # Overlaps only a thin 100x1 sliver of a 100x100 current alert (~1%).
    current = _gdf([(0, 99, 100, 199)])
    out = filter_alerts_by_persistence(current, previous=prev, min_overlap_frac=0.05)
    assert len(out) == 0


def test_history_summary_shape_and_first_row():
    hist = [
        ("2025-11-26", _gdf([(0, 0, 100, 100)])),
        ("2025-11-28", _gdf([(0, 0, 100, 100), (5000, 5000, 5100, 5100)])),
    ]
    confirmed, summary = apply_persistence_to_history(hist, min_consecutive=2)
    assert list(summary["date"]) == ["2025-11-26", "2025-11-28"]
    # First observation: nothing confirmed.
    assert int(summary.loc[summary.date == "2025-11-26", "confirmed"].iloc[0]) == 0
    # Second observation: only the overlapping alert confirmed.
    assert int(summary.loc[summary.date == "2025-11-28", "confirmed"].iloc[0]) == 1
    assert len(confirmed["2025-11-28"]) == 1
