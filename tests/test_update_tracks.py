"""Gap-tolerant persistence tracking (update_tracks).

Guards the 2026-07-17 design: chain alerts by spatial overlap tolerating gaps up
to grace_days; tiers first_observation(1)/candidate(2-14)/confirmed(>=15);
confirmed tracks get infinite tolerance.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import TARGET_CRS  # noqa: E402
from src.detection.persistence import (  # noqa: E402
    persistence_tier,
    update_tracks,
)

# realistic metric coords inside UTM 24S near the AOI (clean WGS84 round-trip)
X, Y = 400000, 9200000
BOX = (X, Y, X + 100, Y + 100)
FAR = (X + 5000, Y + 5000, X + 5100, Y + 5100)


def _g(boxes):
    return gpd.GeoDataFrame(geometry=[box(*b) for b in boxes], crs=TARGET_CRS)


def _iso(d0, days):
    return (d0 + timedelta(days=days)).isoformat()


def test_tier_boundaries():
    assert persistence_tier(1) == "first_observation"
    assert persistence_tier(2) == "candidate"
    assert persistence_tier(14) == "candidate"
    assert persistence_tier(15) == "confirmed"


def test_first_observation():
    out, st = update_tracks(_g([BOX]), None, "2026-01-01")
    assert out["persistence_count"].iloc[0] == 1
    assert out["persistence_status"].iloc[0] == "first_observation"
    assert out["first_seen"].iloc[0] == "2026-01-01"
    assert len(st) == 1


def test_overlap_increments_to_candidate():
    _, st0 = update_tracks(_g([BOX]), None, "2026-01-01")
    out1, _ = update_tracks(_g([BOX]), st0, "2026-01-05")
    assert out1["persistence_count"].iloc[0] == 2
    assert out1["persistence_status"].iloc[0] == "candidate"
    assert out1["first_seen"].iloc[0] == "2026-01-01"   # inherited


def test_non_overlap_is_new_track():
    _, st0 = update_tracks(_g([BOX]), None, "2026-01-01")
    out1, st1 = update_tracks(_g([FAR]), st0, "2026-01-05")
    assert out1["persistence_count"].iloc[0] == 1
    assert len(st1) == 2   # both locations tracked


def test_gap_within_grace_continues_but_beyond_resets():
    d0 = date(2026, 1, 1)
    _, st = update_tracks(_g([BOX]), None, _iso(d0, 0))
    out1, st = update_tracks(_g([BOX]), st, _iso(d0, 4))     # n=2
    assert out1["persistence_count"].iloc[0] == 2
    # reappears 150d later (<=180) -> continues
    out2, st = update_tracks(_g([BOX]), st, _iso(d0, 154))
    assert out2["persistence_count"].iloc[0] == 3
    # reappears 199d after last (>180) -> resets to a fresh first_observation
    out3, st = update_tracks(_g([BOX]), st, _iso(d0, 154 + 199))
    assert out3["persistence_count"].iloc[0] == 1
    assert out3["persistence_status"].iloc[0] == "first_observation"


def test_confirmed_gets_infinite_tolerance():
    d0 = date(2026, 1, 1)
    st = None
    out = None
    for i in range(15):
        out, st = update_tracks(_g([BOX]), st, _iso(d0, 4 * i))
    assert out["persistence_count"].iloc[0] == 15
    assert out["persistence_status"].iloc[0] == "confirmed"
    # gap of 300 days (>>180) — established track must still continue
    out2, st = update_tracks(_g([BOX]), st, _iso(d0, 4 * 14 + 300))
    assert out2["persistence_count"].iloc[0] == 16
    assert out2["persistence_status"].iloc[0] == "confirmed"


def test_per_date_increment_once_for_multiple_overlaps():
    """Two current polygons overlapping one track -> track +1 (not +2)."""
    _, st0 = update_tracks(_g([BOX]), None, "2026-01-01")
    # two overlapping polygons this date
    out1, st1 = update_tracks(_g([BOX, (X, Y, X + 60, Y + 60)]), st0, "2026-01-05")
    assert set(out1["persistence_count"]) == {2}   # both inherit the single +1
    assert len(st1) == 1
