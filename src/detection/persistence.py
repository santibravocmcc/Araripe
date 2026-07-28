"""Temporal-persistence filter for deforestation alerts.

The spectral detector (``detect_deforestation``) classifies every scene in
isolation. During the Nov–Apr rainy season, residual cloud / cirrus / BRDF
artefacts produce large bursts of single-date false positives — the alert count
tracks cloudiness, not clearing (AUDITORIA_TECNICA.md item C). A genuine
clearing, by contrast, persists: it is still cleared at the next valid revisit.

This module enforces that intuition. An alert is only *confirmed* when the same
location is flagged in **≥2 consecutive independent observations** (the current
observation plus at least one immediately preceding one). Confirmation is by
spatial overlap, not pixel identity, because each date is vectorized on its own
Sentinel-2 grid and the same physical clearing can be polygonized slightly
differently from one date to the next.

Two entry points:

* :func:`filter_alerts_by_persistence` — the primitive: keep the current-date
  alerts that overlap alerts in each of the required preceding observations.
* :func:`apply_persistence_to_history` — walk a chronological sequence of
  per-date alert GeoDataFrames and return the confirmed subset for each date,
  plus a before/after count table. Used to re-evaluate the existing alert
  archive without re-streaming imagery.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import geopandas as gpd
import pandas as pd
from loguru import logger

from config.settings import TARGET_CRS

# Overlap area (as a fraction of the *current* alert's area) required to count a
# current alert as confirmed by a previous observation. A small positive value
# avoids confirming on a mere edge-touch while tolerating the grid/vectorization
# differences between dates.
DEFAULT_MIN_OVERLAP_FRAC = 0.05


def _to_metric(gdf: gpd.GeoDataFrame, crs: str = TARGET_CRS) -> gpd.GeoDataFrame:
    """Reproject to a metric CRS so intersection areas are meaningful."""
    if gdf is None or gdf.empty:
        return gdf
    if gdf.crs is None:
        # Assume already in the target metric CRS if unlabelled.
        return gdf.set_crs(crs, allow_override=True)
    if str(gdf.crs) != str(crs):
        return gdf.to_crs(crs)
    return gdf


def _confirmed_by_one(
    current_m: gpd.GeoDataFrame,
    previous_m: gpd.GeoDataFrame,
    min_overlap_frac: float,
) -> pd.Series:
    """Boolean Series (index-aligned to current_m): overlaps previous obs?"""
    if previous_m is None or previous_m.empty:
        return pd.Series(False, index=current_m.index)

    prev_union = previous_m.geometry.union_all() if hasattr(
        previous_m.geometry, "union_all"
    ) else previous_m.geometry.unary_union

    inter_area = current_m.geometry.intersection(prev_union).area
    cur_area = current_m.geometry.area.replace(0, float("nan"))
    frac = (inter_area / cur_area).fillna(0.0)
    return frac >= min_overlap_frac


def filter_alerts_by_persistence(
    current: gpd.GeoDataFrame,
    previous: Sequence[gpd.GeoDataFrame] | gpd.GeoDataFrame | None,
    min_overlap_frac: float = DEFAULT_MIN_OVERLAP_FRAC,
) -> gpd.GeoDataFrame:
    """Keep only current alerts confirmed by every preceding observation.

    Parameters
    ----------
    current : GeoDataFrame
        Alerts detected for the current observation date.
    previous : GeoDataFrame | sequence of GeoDataFrame | None
        The immediately preceding observation(s). For the minimum ``>=2
        consecutive observations`` requirement, pass the single previous
        observation. Passing *k* previous observations requires the alert to
        persist across all ``k+1`` consecutive observations.
    min_overlap_frac : float
        Minimum intersection area (as a fraction of the current alert's area)
        with a previous observation for that observation to count as a
        confirmation.

    Returns
    -------
    GeoDataFrame
        Subset of ``current`` (same CRS and columns) that is confirmed. The
        first-ever observation (no ``previous``) yields an empty result — a
        location cannot be confirmed until it is seen a second time.
    """
    if current is None or current.empty:
        return current.copy() if current is not None else current

    if previous is None:
        previous_list: list[gpd.GeoDataFrame] = []
    elif isinstance(previous, gpd.GeoDataFrame):
        previous_list = [previous]
    else:
        previous_list = [p for p in previous if p is not None]

    if not previous_list:
        # No prior observation to confirm against → nothing is persistent yet.
        return current.iloc[0:0].copy()

    current_m = _to_metric(current)
    confirmed = pd.Series(True, index=current_m.index)
    for prev in previous_list:
        prev_m = _to_metric(prev)
        confirmed &= _confirmed_by_one(current_m, prev_m, min_overlap_frac)

    kept = current.loc[confirmed.values].copy()
    logger.info(
        "Persistence filter: {}/{} alerts confirmed across {} consecutive "
        "observation(s) (min overlap {:.0%})",
        len(kept), len(current), len(previous_list) + 1, min_overlap_frac,
    )
    return kept


def compute_persistence_counts(
    current: gpd.GeoDataFrame,
    previous: gpd.GeoDataFrame | None,
    min_overlap_frac: float = DEFAULT_MIN_OVERLAP_FRAC,
    count_col: str = "persistence_count",
) -> pd.Series:
    """Consecutive-observation *streak* for each current alert.

    Returns a Series (indexed like ``current``) where each value is how many
    consecutive valid observations that location has been flagged in, **including
    the current one**:

      * 1  → seen only now (a fresh appearance, or the first-ever observation);
      * 2  → also present in the immediately-preceding observation;
      * N  → present in N consecutive observations.

    It chains: an alert inherits ``max(previous streak it overlaps) + 1``. So if
    the previous file already carries ``persistence_count`` (written by a prior
    run), the streak grows run over run — letting the front-end filter "appeared
    ≥ N times". Overlap uses the same ≥ ``min_overlap_frac`` rule (of the current
    alert's area) as :func:`filter_alerts_by_persistence`.
    """
    if current is None or current.empty:
        return pd.Series([], dtype=int)
    if previous is None or previous.empty:
        return pd.Series(1, index=current.index, dtype=int)

    from shapely import area as _area
    from shapely import intersection as _intersection

    cur = _to_metric(current)
    prev = _to_metric(previous).copy()
    if count_col in prev.columns:
        prev_count = pd.to_numeric(prev[count_col], errors="coerce").fillna(1).astype(int)
    else:
        prev_count = pd.Series(1, index=prev.index, dtype=int)

    cur_area = cur.geometry.area
    left = gpd.GeoDataFrame({"__cidx": cur.index}, geometry=cur.geometry.values, crs=cur.crs)
    right = gpd.GeoDataFrame(
        {"__pcount": prev_count.values}, geometry=prev.geometry.values, crs=prev.crs
    )
    joined = gpd.sjoin(left, right, predicate="intersects", how="inner")
    if joined.empty:
        return pd.Series(1, index=current.index, dtype=int)

    # Intersection area per matched pair (vectorized via shapely 2).
    cur_geom = joined.geometry.values
    prev_geom = right.geometry.values[joined["index_right"].values]
    inter_area = _area(_intersection(cur_geom, prev_geom))
    cidx = joined["__cidx"].values
    frac = inter_area / cur_area.loc[cidx].values
    ok = frac >= min_overlap_frac
    if not ok.any():
        return pd.Series(1, index=current.index, dtype=int)

    best = (
        pd.DataFrame({"__cidx": cidx[ok], "__pcount": joined["__pcount"].values[ok]})
        .groupby("__cidx")["__pcount"].max()
    )
    streak = pd.Series(1, index=current.index, dtype=int)
    streak.loc[best.index] = (best + 1).astype(int)
    return streak


def apply_persistence_to_history(
    dated_alerts: Iterable[tuple[str, gpd.GeoDataFrame]],
    min_consecutive: int = 2,
    min_overlap_frac: float = DEFAULT_MIN_OVERLAP_FRAC,
) -> tuple[dict[str, gpd.GeoDataFrame], pd.DataFrame]:
    """Re-evaluate an ordered alert archive under the persistence rule.

    Parameters
    ----------
    dated_alerts : iterable of (date_str, GeoDataFrame)
        Per-observation alerts in chronological order.
    min_consecutive : int
        Number of consecutive observations a location must appear in to be
        confirmed (>=2). ``min_consecutive=2`` requires the current plus one
        preceding observation.
    min_overlap_frac : float
        Passed through to :func:`filter_alerts_by_persistence`.

    Returns
    -------
    (confirmed_by_date, summary)
        ``confirmed_by_date`` maps each date to its confirmed GeoDataFrame;
        ``summary`` is a DataFrame with columns
        ``date, raw, confirmed, dropped, drop_frac``.
    """
    items = list(dated_alerts)
    confirmed_by_date: dict[str, gpd.GeoDataFrame] = {}
    rows = []
    k_prev = max(1, min_consecutive - 1)

    for i, (date, gdf) in enumerate(items):
        prev_window = [items[j][1] for j in range(max(0, i - k_prev), i)]
        if len(prev_window) < k_prev:
            # Not enough history yet to confirm this date.
            confirmed = gdf.iloc[0:0].copy() if gdf is not None and not gdf.empty else gdf
        else:
            confirmed = filter_alerts_by_persistence(
                gdf, prev_window, min_overlap_frac=min_overlap_frac
            )
        confirmed_by_date[date] = confirmed
        raw_n = 0 if gdf is None else len(gdf)
        conf_n = 0 if confirmed is None else len(confirmed)
        rows.append(
            {
                "date": date,
                "raw": raw_n,
                "confirmed": conf_n,
                "dropped": raw_n - conf_n,
                "drop_frac": round(1 - conf_n / raw_n, 4) if raw_n else 0.0,
            }
        )

    summary = pd.DataFrame(rows)
    return confirmed_by_date, summary


# ─── Gap-tolerant persistence (stateful tracking) ────────────────────────────
# The strict streak above remains a legacy archive helper. Live persistence
# uses deterministic acquisition/observation/event/contribution identities,
# exact replay no-ops, a chronological watermark, and explicit split/merge
# lineage. A track can reconnect for 180 days; confirmed tracks remain eligible.

GRACE_DAYS = 180
CONFIRMED_MIN = 15
STATE_SIMPLIFY_M = 12.0
_ST_FIRST = "first_observation"
_ST_CANDIDATE = "candidate"
_ST_CONFIRMED = "confirmed"
_STATE_SCHEMA_VERSION = "1.0.0"
_STATE_METADATA_KEY = "persistence_metadata"
_STATE_COLS = [
    "event_id",
    "status",
    "identity_kind",
    "first_observation_id",
    "parent_event_ids",
    "trigger_observation_ids",
    "n_sightings",
    "first_seen",
    "last_seen",
    "observation_ids",
    "acquisition_ids",
    "contributions",
    "incoming_lineage",
    "outgoing_lineage",
    "child_event_ids",
    "representative_geometry_sha256",
]


class PersistenceTransitionError(RuntimeError):
    """Base class for a rejected deterministic state transition."""


class LegacyPersistenceStateError(PersistenceTransitionError):
    """The input predates the Phase 2A.1 deterministic state contract."""


class OutOfOrderAcquisitionError(PersistenceTransitionError):
    """An older acquisition attempted to mutate live state."""


class SameDateAcquisitionError(PersistenceTransitionError):
    """A corrected same-date acquisition requires a new generation."""


class NonDeterministicReplayError(PersistenceTransitionError):
    """The same acquisition replay produced a different observation set."""


class AmbiguousLineageError(PersistenceTransitionError):
    """One acquisition produced an unsupported many-to-many lineage graph."""


class StateGenerationMismatchError(PersistenceTransitionError):
    """Runtime identity versions differ from the loaded state generation."""


def _state_metadata(state: gpd.GeoDataFrame) -> dict:
    metadata = state.attrs.get(_STATE_METADATA_KEY)
    if not isinstance(metadata, dict):
        if len(state):
            raise LegacyPersistenceStateError(
                "persistence state has no deterministic Phase 2A.1 metadata; "
                "rebuild it chronologically in a new generation"
            )
        metadata = {
            "schema_version": _STATE_SCHEMA_VERSION,
            "watermark": None,
            "acquisitions_by_date": {},
        }
        state.attrs[_STATE_METADATA_KEY] = metadata
    if metadata.get("schema_version") != _STATE_SCHEMA_VERSION:
        raise LegacyPersistenceStateError("unsupported persistence state schema")
    if not isinstance(metadata.get("acquisitions_by_date"), dict):
        raise LegacyPersistenceStateError("invalid acquisition registry in state")
    return metadata


def _validate_state_columns(state: gpd.GeoDataFrame) -> None:
    missing = set(_STATE_COLS) - set(state.columns)
    if len(state) and missing:
        raise LegacyPersistenceStateError(
            "persistence state lacks deterministic columns "
            f"{sorted(missing)}; rebuild it chronologically in a new generation"
        )


def _json_value(value):
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    return value


def save_persistence_state(state: gpd.GeoDataFrame, path) -> None:
    """Write deterministic GeoJSON state with top-level transition metadata."""
    from pathlib import Path

    from shapely.geometry import mapping

    from src.detection.identity import canonical_json_bytes

    _validate_state_columns(state)
    metadata = _state_metadata(state)
    state_wgs84 = state if str(state.crs) == "EPSG:4326" else state.to_crs("EPSG:4326")
    features = []
    for _, row in state_wgs84.sort_values("event_id").iterrows():
        properties = {
            column: _json_value(row[column])
            for column in _STATE_COLS
            if column in row and column != "geometry"
        }
        geometry = mapping(row.geometry)
        features.append(
            {
                "type": "Feature",
                "id": row["event_id"],
                "properties": properties,
                "geometry": geometry,
            }
        )
    payload = {
        "type": "FeatureCollection",
        _STATE_METADATA_KEY: metadata,
        "features": features,
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(payload) + b"\n")


def load_persistence_state(path) -> gpd.GeoDataFrame:
    """Load and validate deterministic state; legacy GeoJSON fails closed."""
    import json
    from pathlib import Path

    from shapely.geometry import shape

    source = Path(path)
    with source.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("type") != "FeatureCollection":
        raise LegacyPersistenceStateError("persistence state is not a FeatureCollection")
    metadata = payload.get(_STATE_METADATA_KEY)
    if not isinstance(metadata, dict):
        raise LegacyPersistenceStateError(
            "legacy persistence state requires a chronological new-generation rebuild"
        )
    records = []
    geometries = []
    for feature in payload.get("features", []):
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise LegacyPersistenceStateError("state feature has invalid properties")
        records.append(properties)
        geometries.append(shape(feature["geometry"]))
    if records:
        state = gpd.GeoDataFrame(records, geometry=geometries, crs="EPSG:4326")
    else:
        state = empty_persistence_state()
    state.attrs[_STATE_METADATA_KEY] = metadata
    _validate_state_columns(state)
    _state_metadata(state)
    return state


def persistence_tier(n: int, confirmed_min: int = CONFIRMED_MIN) -> str:
    """Map a sighting count to its persistence tier."""
    if n >= confirmed_min:
        return _ST_CONFIRMED
    if n >= 2:
        return _ST_CANDIDATE
    return _ST_FIRST


def empty_persistence_state() -> gpd.GeoDataFrame:
    """An empty deterministic event table for a new chronological generation."""
    state = gpd.GeoDataFrame(
        {column: [] for column in _STATE_COLS}, geometry=[], crs="EPSG:4326"
    )
    state.attrs[_STATE_METADATA_KEY] = {
        "schema_version": _STATE_SCHEMA_VERSION,
        "watermark": None,
        "acquisitions_by_date": {},
    }
    return state


def _days_between(a: str, b: str) -> int:
    from datetime import date as _date
    return (_date.fromisoformat(str(a)) - _date.fromisoformat(str(b))).days


def _copy_state(state: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    copied = state.reset_index(drop=True).copy(deep=True)
    copied.attrs[_STATE_METADATA_KEY] = {
        **_state_metadata(state),
        "acquisitions_by_date": dict(
            _state_metadata(state)["acquisitions_by_date"]
        ),
        "watermark": (
            dict(_state_metadata(state)["watermark"])
            if _state_metadata(state).get("watermark")
            else None
        ),
    }
    return copied


def _lineage_edge(
    *,
    relation: str,
    parent_event_ids: list[str],
    child_event_ids: list[str],
    acquisition,
    trigger_observation_ids: list[str],
    algorithm_version: str,
) -> dict:
    from src.detection.identity import lineage_id

    return {
        "lineage_id": lineage_id(
            relation=relation,
            parent_event_ids=parent_event_ids,
            child_event_ids=child_event_ids,
            acquisition_id=acquisition.acquisition_id,
            observed_on=acquisition.observed_on,
            trigger_observation_ids=trigger_observation_ids,
            algorithm_version=algorithm_version,
        ),
        "relation": relation,
        "parent_event_ids": sorted(parent_event_ids),
        "child_event_ids": sorted(child_event_ids),
        "effective_acquisition_id": acquisition.acquisition_id,
        "effective_on": acquisition.observed_on,
        "trigger_observation_ids": sorted(trigger_observation_ids),
        "algorithm_version": algorithm_version,
        "reason": {
            "continuation": "spatial_continuity",
            "split": "split_detected",
            "merge": "merge_detected",
        }[relation],
    }


def _representative_hash(geometry_metric):
    from src.detection.identity import canonical_geometry_sha256

    geometry_wgs84 = gpd.GeoSeries(
        [geometry_metric], crs=TARGET_CRS
    ).to_crs("EPSG:4326").iloc[0]
    return canonical_geometry_sha256(geometry_wgs84)[1]


def _new_event_record(
    *,
    event_id: str,
    identity_kind: str,
    first_observation_id: str | None,
    parent_event_ids: list[str],
    trigger_observation_ids: list[str],
    observation_id_value: str,
    acquisition,
    geometry_metric,
    contribution_key_value: str,
    incoming_lineage: list[dict],
) -> dict:
    return {
        "event_id": event_id,
        "status": "active",
        "identity_kind": identity_kind,
        "first_observation_id": first_observation_id,
        "parent_event_ids": sorted(parent_event_ids),
        "trigger_observation_ids": sorted(trigger_observation_ids),
        "n_sightings": 1,
        "first_seen": acquisition.observed_on,
        "last_seen": acquisition.observed_on,
        "observation_ids": [observation_id_value],
        "acquisition_ids": [acquisition.acquisition_id],
        "contributions": [
            {
                "contribution_key": contribution_key_value,
                "acquisition_id": acquisition.acquisition_id,
                "observed_on": acquisition.observed_on,
                "observation_ids": [observation_id_value],
            }
        ],
        "incoming_lineage": incoming_lineage,
        "outgoing_lineage": [],
        "child_event_ids": [],
        "representative_geometry_sha256": _representative_hash(
            geometry_metric.simplify(STATE_SIMPLIFY_M)
        ),
    }


def _annotate_replay(
    current: gpd.GeoDataFrame,
    state: gpd.GeoDataFrame,
    *,
    acquisition,
    observation_ids: list[str],
    geometry_hashes: list[str],
    confirmed_min: int,
) -> gpd.GeoDataFrame:
    by_observation: dict[str, tuple[pd.Series, dict]] = {}
    stored_for_acquisition: set[str] = set()
    for _, row in state.iterrows():
        for contribution in row["contributions"]:
            if contribution["acquisition_id"] != acquisition.acquisition_id:
                continue
            for item in contribution["observation_ids"]:
                stored_for_acquisition.add(item)
                by_observation[item] = (row, contribution)
    if stored_for_acquisition != set(observation_ids):
        raise NonDeterministicReplayError(
            "the same acquisition produced a different observation set; "
            "start a corrected chronological generation"
        )

    annotated = current.reset_index(drop=True).copy()
    event_ids = []
    keys = []
    counts = []
    first_seen = []
    for item in observation_ids:
        row, contribution = by_observation[item]
        event_ids.append(row["event_id"])
        keys.append(contribution["contribution_key"])
        counts.append(int(row["n_sightings"]))
        first_seen.append(row["first_seen"])
    annotated["acquisition_id"] = acquisition.acquisition_id
    annotated["observation_id"] = observation_ids
    annotated["canonical_geometry_sha256"] = geometry_hashes
    annotated["event_id"] = event_ids
    annotated["persistence_contribution_key"] = keys
    annotated["persistence_count"] = counts
    annotated["persistence_status"] = [
        persistence_tier(value, confirmed_min) for value in counts
    ]
    annotated["first_seen"] = first_seen
    annotated["last_seen"] = acquisition.observed_on
    annotated.attrs["persistence_transition"] = {
        "outcome": "no_op_replay",
        "state_changed": False,
        "new_contribution_count": 0,
        "duplicate_contribution_count": len(keys),
    }
    return annotated


def update_tracks(
    current: gpd.GeoDataFrame,
    state: gpd.GeoDataFrame | None,
    date: str,
    *,
    acquisition,
    algorithm_version: str,
    baseline_version: str,
    monitoring_extent_id: str,
    mode: str = "live",
    grace_days: int = GRACE_DAYS,
    confirmed_min: int = CONFIRMED_MIN,
    min_overlap_frac: float = DEFAULT_MIN_OVERLAP_FRAC,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Apply one canonical acquisition exactly once in chronological order."""
    import numpy as np
    from shapely import area as _area
    from shapely import intersection as _intersection

    from src.detection.identity import (
        canonical_geometry_sha256,
        child_event_id,
        contribution_key,
        observation_id,
        origin_event_id,
    )

    if mode not in {"live", "rebuild"}:
        raise ValueError("mode must be 'live' or 'rebuild'")
    if acquisition.observed_on != date:
        raise ValueError("acquisition observed_on differs from transition date")
    if acquisition.monitoring_extent_id != monitoring_extent_id:
        raise ValueError("acquisition monitoring extent differs from runtime extent")

    st = empty_persistence_state() if state is None else _copy_state(state)
    _validate_state_columns(st)
    metadata = _state_metadata(st)
    expected_generation = {
        "algorithm_version": algorithm_version,
        "baseline_version": baseline_version,
        "monitoring_extent_id": monitoring_extent_id,
    }
    for key, expected in expected_generation.items():
        actual = metadata.get(key)
        if actual is not None and actual != expected:
            raise StateGenerationMismatchError(
                f"state {key}={actual!r} differs from runtime {expected!r}; "
                "start a new chronological generation"
            )

    cur = current.reset_index(drop=True).copy()
    cur_wgs84 = cur if str(cur.crs) == "EPSG:4326" else cur.to_crs("EPSG:4326")
    geometry_hashes = [
        canonical_geometry_sha256(geometry)[1] for geometry in cur_wgs84.geometry
    ]
    observation_ids = [
        observation_id(
            acquisition.acquisition_id,
            geometry_hash,
            algorithm_version,
            baseline_version,
        )
        for geometry_hash in geometry_hashes
    ]
    if len(observation_ids) != len(set(observation_ids)):
        raise PersistenceTransitionError(
            "one acquisition produced duplicate canonical observation geometries"
        )

    registered = metadata["acquisitions_by_date"].get(date)
    if registered is not None:
        if registered != acquisition.acquisition_id:
            raise SameDateAcquisitionError(
                f"{date} is already bound to {registered}; corrected same-date "
                "acquisitions require a new chronological generation"
            )
        annotated = _annotate_replay(
            cur,
            st,
            acquisition=acquisition,
            observation_ids=observation_ids,
            geometry_hashes=geometry_hashes,
            confirmed_min=confirmed_min,
        )
        # Exact retry: return the original state object so callers cannot
        # accidentally alter metadata or its deterministic checksum.
        return annotated, state if state is not None else st

    watermark = metadata.get("watermark")
    if watermark and date <= watermark["observed_on"]:
        raise OutOfOrderAcquisitionError(
            f"{date} is not newer than live watermark {watermark['observed_on']}; "
            "backfills must start from empty/snapshot state in a new generation"
        )
    if cur.empty:
        cur.attrs["persistence_transition"] = {
            "outcome": "no_observations",
            "state_changed": False,
            "new_contribution_count": 0,
            "duplicate_contribution_count": 0,
        }
        return cur, st

    cur_m = _to_metric(cur)
    cur_geom = np.asarray(cur_m.geometry.values, dtype=object)
    cur_area = _area(cur_geom)
    n = len(cur)

    have_state = len(st) > 0
    if have_state:
        st_m = _to_metric(st)
        st_geom = list(st_m.geometry.values)
        st_n = (
            pd.to_numeric(st["n_sightings"], errors="raise").astype(int).to_numpy()
        )
        active = st["status"].to_numpy() == "active"
        established = st_n >= confirmed_min
        recent = np.array(
            [
                0 <= _days_between(date, last_seen) <= grace_days
                for last_seen in st["last_seen"].astype(str)
            ]
        )
        eligible = active & (established | recent)
    else:
        st_geom = []
        eligible = np.array([], dtype=bool)

    parents_by_current: dict[int, set[int]] = {index: set() for index in range(n)}
    currents_by_parent: dict[int, set[int]] = {}
    if have_state and eligible.any():
        eligible_indices = np.where(eligible)[0]
        right = gpd.GeoDataFrame(
            {"__event_index": eligible_indices},
            geometry=[st_geom[index] for index in eligible_indices],
            crs=cur_m.crs,
        )
        left = gpd.GeoDataFrame(
            {"__current_index": np.arange(n)},
            geometry=list(cur_geom),
            crs=cur_m.crs,
        )
        j = gpd.sjoin(left, right, predicate="intersects", how="inner")
        if len(j):
            current_indices = j["__current_index"].to_numpy(dtype=int)
            event_indices = j["__event_index"].to_numpy(dtype=int)
            intersections = _area(
                _intersection(
                    j.geometry.values,
                    right.geometry.values[j["index_right"].to_numpy()],
                )
            )
            fractions = np.where(
                cur_area[current_indices] > 0,
                intersections / cur_area[current_indices],
                0.0,
            )
            for current_index, event_index, fraction in zip(
                current_indices, event_indices, fractions
            ):
                if fraction < min_overlap_frac:
                    continue
                parents_by_current[int(current_index)].add(int(event_index))
                currents_by_parent.setdefault(int(event_index), set()).add(
                    int(current_index)
                )

    for current_index, parents in parents_by_current.items():
        if len(parents) > 1 and any(
            len(currents_by_parent[parent]) > 1 for parent in parents
        ):
            raise AmbiguousLineageError(
                "many-to-many split/merge component requires reviewed correction"
            )
        if len(parents) == 1:
            parent = next(iter(parents))
            siblings = currents_by_parent[parent]
            if len(siblings) > 1 and any(
                len(parents_by_current[sibling]) > 1 for sibling in siblings
            ):
                raise AmbiguousLineageError(
                    "many-to-many split/merge component requires reviewed correction"
                )

    records = st.drop(columns="geometry").to_dict("records") if len(st) else []
    geometries = list(st_m.geometry) if have_state else []
    assigned_event_ids: list[str | None] = [None] * n
    assigned_keys: list[str | None] = [None] * n
    assigned_counts = np.ones(n, dtype=int)
    assigned_first_seen = [date] * n
    processed_current: set[int] = set()

    # Deterministic splits: one parent, two or more current observations.
    for parent_index in sorted(currents_by_parent):
        children_indices = sorted(currents_by_parent[parent_index])
        if len(children_indices) < 2:
            continue
        parent_id = records[parent_index]["event_id"]
        child_ids = [
            child_event_id(
                "split", [parent_id], [observation_ids[current_index]]
            )
            for current_index in children_indices
        ]
        edge = _lineage_edge(
            relation="split",
            parent_event_ids=[parent_id],
            child_event_ids=child_ids,
            acquisition=acquisition,
            trigger_observation_ids=[
                observation_ids[current_index]
                for current_index in children_indices
            ],
            algorithm_version=algorithm_version,
        )
        records[parent_index]["status"] = "superseded"
        records[parent_index]["child_event_ids"] = child_ids
        records[parent_index]["outgoing_lineage"] = [
            *records[parent_index]["outgoing_lineage"],
            edge,
        ]
        for current_index, event_id_value in zip(children_indices, child_ids):
            key = contribution_key(event_id_value, acquisition.acquisition_id)
            records.append(
                _new_event_record(
                    event_id=event_id_value,
                    identity_kind="split",
                    first_observation_id=None,
                    parent_event_ids=[parent_id],
                    trigger_observation_ids=[observation_ids[current_index]],
                    observation_id_value=observation_ids[current_index],
                    acquisition=acquisition,
                    geometry_metric=cur_geom[current_index],
                    contribution_key_value=key,
                    incoming_lineage=[edge],
                )
            )
            geometries.append(cur_geom[current_index].simplify(STATE_SIMPLIFY_M))
            assigned_event_ids[current_index] = event_id_value
            assigned_keys[current_index] = key
            processed_current.add(current_index)

    for current_index in range(n):
        if current_index in processed_current:
            continue
        parents = sorted(parents_by_current[current_index])
        if not parents:
            event_id_value = origin_event_id(observation_ids[current_index])
            key = contribution_key(event_id_value, acquisition.acquisition_id)
            records.append(
                _new_event_record(
                    event_id=event_id_value,
                    identity_kind="origin",
                    first_observation_id=observation_ids[current_index],
                    parent_event_ids=[],
                    trigger_observation_ids=[observation_ids[current_index]],
                    observation_id_value=observation_ids[current_index],
                    acquisition=acquisition,
                    geometry_metric=cur_geom[current_index],
                    contribution_key_value=key,
                    incoming_lineage=[],
                )
            )
            geometries.append(cur_geom[current_index].simplify(STATE_SIMPLIFY_M))
            assigned_event_ids[current_index] = event_id_value
            assigned_keys[current_index] = key
            continue

        if len(parents) > 1:
            parent_ids = [records[index]["event_id"] for index in parents]
            event_id_value = child_event_id(
                "merge", parent_ids, [observation_ids[current_index]]
            )
            key = contribution_key(event_id_value, acquisition.acquisition_id)
            edge = _lineage_edge(
                relation="merge",
                parent_event_ids=parent_ids,
                child_event_ids=[event_id_value],
                acquisition=acquisition,
                trigger_observation_ids=[observation_ids[current_index]],
                algorithm_version=algorithm_version,
            )
            for parent_index in parents:
                records[parent_index]["status"] = "superseded"
                records[parent_index]["child_event_ids"] = [event_id_value]
                records[parent_index]["outgoing_lineage"] = [
                    *records[parent_index]["outgoing_lineage"],
                    edge,
                ]
            records.append(
                _new_event_record(
                    event_id=event_id_value,
                    identity_kind="merge",
                    first_observation_id=None,
                    parent_event_ids=parent_ids,
                    trigger_observation_ids=[observation_ids[current_index]],
                    observation_id_value=observation_ids[current_index],
                    acquisition=acquisition,
                    geometry_metric=cur_geom[current_index],
                    contribution_key_value=key,
                    incoming_lineage=[edge],
                )
            )
            geometries.append(cur_geom[current_index].simplify(STATE_SIMPLIFY_M))
            assigned_event_ids[current_index] = event_id_value
            assigned_keys[current_index] = key
            continue

        parent_index = parents[0]
        event_id_value = records[parent_index]["event_id"]
        key = contribution_key(event_id_value, acquisition.acquisition_id)
        edge = _lineage_edge(
            relation="continuation",
            parent_event_ids=[event_id_value],
            child_event_ids=[event_id_value],
            acquisition=acquisition,
            trigger_observation_ids=[observation_ids[current_index]],
            algorithm_version=algorithm_version,
        )
        records[parent_index]["n_sightings"] = (
            int(records[parent_index]["n_sightings"]) + 1
        )
        records[parent_index]["last_seen"] = date
        records[parent_index]["observation_ids"] = [
            *records[parent_index]["observation_ids"],
            observation_ids[current_index],
        ]
        records[parent_index]["acquisition_ids"] = [
            *records[parent_index]["acquisition_ids"],
            acquisition.acquisition_id,
        ]
        records[parent_index]["contributions"] = [
            *records[parent_index]["contributions"],
            {
                "contribution_key": key,
                "acquisition_id": acquisition.acquisition_id,
                "observed_on": date,
                "observation_ids": [observation_ids[current_index]],
            },
        ]
        records[parent_index]["incoming_lineage"] = [
            *records[parent_index]["incoming_lineage"],
            edge,
        ]
        records[parent_index]["outgoing_lineage"] = [
            *records[parent_index]["outgoing_lineage"],
            edge,
        ]
        records[parent_index]["representative_geometry_sha256"] = (
            _representative_hash(
                cur_geom[current_index].simplify(STATE_SIMPLIFY_M)
            )
        )
        geometries[parent_index] = cur_geom[current_index].simplify(
            STATE_SIMPLIFY_M
        )
        assigned_event_ids[current_index] = event_id_value
        assigned_keys[current_index] = key
        assigned_counts[current_index] = int(
            records[parent_index]["n_sightings"]
        )
        assigned_first_seen[current_index] = records[parent_index]["first_seen"]

    all_keys = [
        contribution["contribution_key"]
        for record in records
        for contribution in record["contributions"]
    ]
    if len(all_keys) != len(set(all_keys)):
        raise PersistenceTransitionError("duplicate contribution key in output state")

    keep_indices = [
        index
        for index, record in enumerate(records)
        if record["status"] == "superseded"
        or int(record["n_sightings"]) >= confirmed_min
        or 0 <= _days_between(date, record["last_seen"]) <= grace_days
    ]
    kept_records = [records[index] for index in keep_indices]
    kept_geometries = [geometries[index] for index in keep_indices]
    new_state = gpd.GeoDataFrame(
        kept_records,
        geometry=kept_geometries,
        crs=cur_m.crs,
    ).to_crs("EPSG:4326")
    metadata["acquisitions_by_date"][date] = acquisition.acquisition_id
    metadata["watermark"] = {
        "observed_on": date,
        "acquisition_id": acquisition.acquisition_id,
    }
    metadata["algorithm_version"] = algorithm_version
    metadata["baseline_version"] = baseline_version
    metadata["monitoring_extent_id"] = monitoring_extent_id
    new_state.attrs[_STATE_METADATA_KEY] = metadata

    cur["acquisition_id"] = acquisition.acquisition_id
    cur["observation_id"] = observation_ids
    cur["canonical_geometry_sha256"] = geometry_hashes
    cur["event_id"] = assigned_event_ids
    cur["persistence_contribution_key"] = assigned_keys
    cur["persistence_count"] = assigned_counts
    cur["persistence_status"] = [
        persistence_tier(int(value), confirmed_min) for value in assigned_counts
    ]
    cur["first_seen"] = assigned_first_seen
    cur["last_seen"] = date
    cur.attrs["persistence_transition"] = {
        "outcome": "applied",
        "state_changed": True,
        "new_contribution_count": n,
        "duplicate_contribution_count": 0,
    }
    return cur, new_state
