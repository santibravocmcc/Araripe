"""Tests for the per-date tile-merge + gap-tolerant persistence in run_detection.

Guards (1) the fix for the streaming path's same-date tile-overwrite bug —
``_merge_and_confirm`` must merge all tiles of a date into one result — and
(2) the gap-tolerant persistence wiring: it threads a running track ``state``
and stamps the tiers first_observation(1)/candidate(2-14)/confirmed(>=15).
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

# realistic metric coords inside UTM 24S near the AOI (clean WGS84 round-trip)
X, Y = 400000, 9200000


def _tile(boxes, confidences):
    return gpd.GeoDataFrame(
        {"confidence": confidences},
        geometry=[box(*b) for b in boxes],
        crs=TARGET_CRS,
    )


def test_merge_keeps_all_tiles():
    """Two tiles for one date -> all polygons survive (bug would keep only 1)."""
    t1 = _tile([(X, Y, X + 100, Y + 100), (X + 500, Y + 500, X + 600, Y + 600)], [3, 1])
    t2 = _tile([(X + 2000, Y + 2000, X + 2100, Y + 2100)], [2])

    merged, state = run_detection._merge_and_confirm(
        "2026-05-01", [t1, t2], True, 0.05, None,
    )
    assert len(merged) == 3  # would be 1 under the old per-tile overwrite
    assert set(merged["persistence_status"]) == {"first_observation"}  # no prior state
    assert len(state) == 3


def test_persistence_gap_tolerant_tiers():
    """With a prior state, an overlapping alert -> candidate (n=2); a far one -> 1ª obs."""
    prev = _tile([(X, Y, X + 100, Y + 100)], [3])
    _, state = run_detection._merge_and_confirm("2026-04-27", [prev], True, 0.05, None)

    cur = _tile([(X, Y, X + 100, Y + 100), (X + 9000, Y + 9000, X + 9100, Y + 9100)], [3, 2])
    merged, state = run_detection._merge_and_confirm("2026-05-01", [cur], True, 0.05, state)

    overl = merged.loc[merged.geometry.centroid.x < X + 1000]
    far = merged.loc[merged.geometry.centroid.x > X + 1000]
    assert int(overl["persistence_count"].iloc[0]) == 2
    assert overl["persistence_status"].iloc[0] == "candidate"
    assert far["persistence_status"].iloc[0] == "first_observation"


def test_no_persistence_flag():
    """--no-persistence: merge still combines tiles, no status column forced."""
    t1 = _tile([(X, Y, X + 100, Y + 100)], [3])
    t2 = _tile([(X + 500, Y + 500, X + 600, Y + 600)], [2])
    merged, _ = run_detection._merge_and_confirm("2026-05-01", [t1, t2], False, 0.05, None)
    assert len(merged) == 2
    assert "persistence_status" not in merged.columns
