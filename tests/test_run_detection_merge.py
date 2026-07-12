"""Tests for the per-date tile-merge in scripts/run_detection.py.

Guards the fix for the streaming path's same-date tile-overwrite bug: the loop
yields one GeoDataFrame per UTM tile, and several tiles can share one
acquisition date. The old code saved once per tile, so tiles clobbered each
other and only the last one survived on disk. `_merge_and_confirm` must merge
all tiles of a date into one result and stamp the persistence status.
"""

import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from config.settings import TARGET_CRS  # noqa: E402
import run_detection  # noqa: E402


def _tile(boxes, confidences):
    return gpd.GeoDataFrame(
        {"confidence": confidences},
        geometry=[box(*b) for b in boxes],
        crs=TARGET_CRS,
    )


def test_merge_keeps_all_tiles(tmp_path):
    """Two tiles for one date -> all polygons survive (bug would keep only 1)."""
    t1 = _tile([(0, 0, 100, 100), (500, 500, 600, 600)], [3, 1])
    t2 = _tile([(2000, 2000, 2100, 2100)], [2])

    merged = run_detection._merge_and_confirm(
        "2026-05-01", [t1, t2], tmp_path, persistence=True, min_overlap_frac=0.05,
    )

    assert len(merged) == 3  # would be 1 under the old per-tile overwrite
    assert set(merged["persistence_status"]) == {"first_observation"}  # no prior file


def test_persistence_confirms_only_overlapping(tmp_path):
    """With a prior-date file, only alerts overlapping it are 'confirmed'."""
    # A previous observation, written like save_alerts does (WGS84 on disk).
    prev = _tile([(0, 0, 100, 100)], [3]).to_crs(4326)
    prev.to_file(tmp_path / "alerts_2026-04-27.geojson", driver="GeoJSON")

    # Current date: one poly on top of the prior one, one far away.
    cur = _tile([(0, 0, 100, 100), (9000, 9000, 9100, 9100)], [3, 2])
    merged = run_detection._merge_and_confirm(
        "2026-05-01", [cur], tmp_path, persistence=True, min_overlap_frac=0.05,
    )

    overlapping = merged.loc[merged.geometry.centroid.x < 1000, "persistence_status"]
    far = merged.loc[merged.geometry.centroid.x > 1000, "persistence_status"]
    assert overlapping.iloc[0] == "confirmed"
    assert far.iloc[0] == "candidate"


def test_no_persistence_flag(tmp_path):
    """--no-persistence: merge still combines tiles, no status column forced."""
    t1 = _tile([(0, 0, 100, 100)], [3])
    t2 = _tile([(500, 500, 600, 600)], [2])
    merged = run_detection._merge_and_confirm(
        "2026-05-01", [t1, t2], tmp_path, persistence=False, min_overlap_frac=0.05,
    )
    assert len(merged) == 2
    assert "persistence_status" not in merged.columns
