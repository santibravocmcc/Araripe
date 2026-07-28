"""Gap-tolerant persistence tracking (update_tracks).

Guards the 2026-07-17 design: chain alerts by spatial overlap tolerating gaps up
to grace_days; tiers first_observation(1)/candidate(2-14)/confirmed(>=15);
confirmed tracks get infinite tolerance.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import TARGET_CRS  # noqa: E402
from config.settings import (  # noqa: E402
    BASELINE_VERSION,
    DETECTION_ALGORITHM_VERSION,
    MONITORING_EXTENT_ID,
)
from src.detection.identity import create_acquisition_identity  # noqa: E402
from src.detection.persistence import (  # noqa: E402
    OutOfOrderAcquisitionError,
    SameDateAcquisitionError,
    load_persistence_state,
    persistence_tier,
    save_persistence_state,
    update_tracks as _update_tracks,
)

# realistic metric coords inside UTM 24S near the AOI (clean WGS84 round-trip)
X, Y = 400000, 9200000
BOX = (X, Y, X + 100, Y + 100)
FAR = (X + 5000, Y + 5000, X + 5100, Y + 5100)


def _g(boxes):
    return gpd.GeoDataFrame(geometry=[box(*b) for b in boxes], crs=TARGET_CRS)


def _iso(d0, days):
    return (d0 + timedelta(days=days)).isoformat()


def _acquisition(observed_on, scene_suffix="a"):
    return create_acquisition_identity(
        collection_id="COPERNICUS/S2_SR_HARMONIZED",
        observed_on=observed_on,
        scene_ids=[
            f"COPERNICUS/S2_SR_HARMONIZED/{observed_on.replace('-', '')}_{scene_suffix}"
        ],
        monitoring_extent_id=MONITORING_EXTENT_ID,
        composite_method_id="daily_mosaic-v1",
    )


def update_tracks(current, state, observed_on, *, scene_suffix="a", **kwargs):
    return _update_tracks(
        current,
        state,
        observed_on,
        acquisition=_acquisition(observed_on, scene_suffix),
        algorithm_version=DETECTION_ALGORITHM_VERSION,
        baseline_version=BASELINE_VERSION,
        monitoring_extent_id=MONITORING_EXTENT_ID,
        **kwargs,
    )


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


def test_split_creates_deterministic_children_and_supersedes_parent():
    _, st0 = update_tracks(_g([BOX]), None, "2026-01-01")
    out1, st1 = update_tracks(_g([BOX, (X, Y, X + 60, Y + 60)]), st0, "2026-01-05")
    assert set(out1["persistence_count"]) == {1}
    assert len(set(out1["event_id"])) == 2
    parent = st1.loc[st1["identity_kind"] == "origin"].iloc[0]
    children = st1.loc[st1["identity_kind"] == "split"]
    assert parent["status"] == "superseded"
    assert set(parent["child_event_ids"]) == set(children["event_id"])
    assert len(children) == 2
    assert len(
        {
            edge["lineage_id"]
            for edges in children["incoming_lineage"]
            for edge in edges
        }
    ) == 1


def test_merge_creates_one_child_and_supersedes_parents():
    left = (X, Y, X + 100, Y + 100)
    right = (X + 120, Y, X + 220, Y + 100)
    _, state = update_tracks(_g([left, right]), None, "2026-01-01")
    current = _g([(X, Y, X + 220, Y + 100)])
    out, state = update_tracks(
        current, state, "2026-01-05", min_overlap_frac=0.05
    )
    assert out["persistence_count"].iloc[0] == 1
    child = state.loc[state["event_id"] == out["event_id"].iloc[0]].iloc[0]
    parents = state.loc[state["event_id"].isin(child["parent_event_ids"])]
    assert child["identity_kind"] == "merge"
    assert len(child["parent_event_ids"]) == 2
    assert set(parents["status"]) == {"superseded"}


def test_exact_retry_and_overlap_are_no_op_with_byte_identical_state(tmp_path):
    alerts = _g([BOX])
    first, state = update_tracks(alerts, None, "2026-01-01")
    before = tmp_path / "before.geojson"
    after = tmp_path / "after.geojson"
    save_persistence_state(state, before)

    replay, replay_state = update_tracks(alerts, state, "2026-01-01")
    save_persistence_state(replay_state, after)

    assert replay.attrs["persistence_transition"]["outcome"] == "no_op_replay"
    assert replay["observation_id"].iloc[0] == first["observation_id"].iloc[0]
    assert replay["persistence_count"].iloc[0] == 1
    assert before.read_bytes() == after.read_bytes()


def test_out_of_order_live_mutation_is_rejected():
    _, state = update_tracks(_g([BOX]), None, "2026-01-05")
    with pytest.raises(OutOfOrderAcquisitionError):
        update_tracks(_g([BOX]), state, "2026-01-01")


def test_same_date_corrected_acquisition_requires_new_generation():
    _, state = update_tracks(_g([BOX]), None, "2026-01-05")
    with pytest.raises(SameDateAcquisitionError):
        update_tracks(
            _g([BOX]), state, "2026-01-05", scene_suffix="corrected"
        )


def test_state_round_trip_preserves_ids_and_metadata(tmp_path):
    _, state = update_tracks(_g([BOX]), None, "2026-01-01")
    path = tmp_path / "state.geojson"
    save_persistence_state(state, path)
    loaded = load_persistence_state(path)
    assert list(loaded["event_id"]) == list(state["event_id"])
    assert loaded.attrs["persistence_metadata"] == state.attrs["persistence_metadata"]
