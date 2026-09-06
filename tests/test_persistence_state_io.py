"""Fail-closed loading of the persistence track state (Package 2B.1).

`scripts/run_detection.py` and `scripts/run_detection_from_gee.py` used to catch
every read error and continue with `state = None`, i.e. "start from zero". That
is the same silent corruption `scripts/r2_state.py` guards against, one layer
down: a state file that arrives corrupt or truncated would reset every track's
`n_sightings`/`first_seen`/`last_seen` while the run stayed green.

Genuine absence (the first-ever run) is still allowed — and is the only case
that returns `None`.
"""
from __future__ import annotations

import json

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from src.detection.persistence import (
    PersistenceStateError,
    empty_persistence_state,
    load_persistence_state,
    save_persistence_state,
)


def sample_state():
    return gpd.GeoDataFrame(
        {
            "n_sightings": [3, 17],
            "first_seen": ["2026-01-05", "2026-02-01"],
            "last_seen": ["2026-02-10", "2026-03-03"],
        },
        geometry=[
            Polygon([(-39.5, -7.5), (-39.5, -7.4), (-39.4, -7.4), (-39.5, -7.5)]),
            Polygon([(-39.3, -7.3), (-39.3, -7.2), (-39.2, -7.2), (-39.3, -7.3)]),
        ],
        crs="EPSG:4326",
    )


def test_absent_state_is_the_first_run(tmp_path):
    assert load_persistence_state(tmp_path / "persistence_state.geojson") is None


def test_valid_state_round_trips(tmp_path):
    path = tmp_path / "persistence_state.geojson"
    save_persistence_state(sample_state(), path)
    loaded = load_persistence_state(path)
    assert len(loaded) == 2
    assert sorted(loaded["n_sightings"].tolist()) == [3, 17]


def test_empty_state_is_valid(tmp_path):
    """No alert ever seen is a legitimate state, not a corrupt one."""
    path = tmp_path / "persistence_state.geojson"
    save_persistence_state(empty_persistence_state(), path)
    assert len(load_persistence_state(path)) == 0


def test_corrupt_state_raises_instead_of_resetting(tmp_path):
    """The regression: an unreadable state must stop the run, not empty it."""
    path = tmp_path / "persistence_state.geojson"
    path.write_text('{"type": "FeatureCollection", "features": [ truncated')
    with pytest.raises(PersistenceStateError):
        load_persistence_state(path)


def test_empty_file_raises(tmp_path):
    path = tmp_path / "persistence_state.geojson"
    path.write_text("")
    with pytest.raises(PersistenceStateError):
        load_persistence_state(path)


def test_state_without_track_columns_raises(tmp_path):
    """Parseable GeoJSON from another schema is still not a track state."""
    path = tmp_path / "persistence_state.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"area_ha": 2.5},
            "geometry": {"type": "Point", "coordinates": [-39.5, -7.5]},
        }],
    }))
    with pytest.raises(PersistenceStateError, match="n_sightings"):
        load_persistence_state(path)
