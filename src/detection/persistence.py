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
# The strict streak above resets on ANY missed observation (a passing cloud
# demotes a genuine clearing back to "candidate"). This gap-tolerant model
# instead chains each alert to a running *track* by spatial overlap, tolerating
# gaps up to ``grace_days`` (a full rainy season). A track that reaches the top
# tier (``confirmed``) becomes permanent (infinite tolerance). Decision + the
# empirical calibration are recorded in the project memo (2026-07-17):
#   first_observation : n_sightings == 1        (visto uma vez)
#   candidate         : 2 <= n_sightings < 15   (reapareceu, ainda avaliando)
#   confirmed         : n_sightings >= 15        (clareira estabelecida; permanente)

GRACE_DAYS = 180        # tolerância a buracos: reconecta se reapareceu em <= 180d
CONFIRMED_MIN = 15      # n_sightings >= isto -> "confirmed" (topo, permanente)
# O estado só serve para CASAR sobreposição na próxima detecção — não é o que o
# site desenha. Guardar a geometria de ~100k+ tracks em resolução cheia infla o
# arquivo (o CI o busca/envia a cada run). Simplificar ~12 m e limitar a precisão
# de coordenada encolhe o arquivo ~5-10x sem mudar o casamento (limiar 5%, alertas
# >= 1 ha), sem qualquer efeito visual no site.
STATE_SIMPLIFY_M = 12.0    # tolerância de simplificação da geometria (metros)
STATE_COORD_PRECISION = 6  # casas decimais ao salvar em WGS84 (~0.1 m)
_ST_FIRST = "first_observation"
_ST_CANDIDATE = "candidate"
_ST_CONFIRMED = "confirmed"
_STATE_COLS = ["n_sightings", "first_seen", "last_seen"]


def save_persistence_state(state: gpd.GeoDataFrame, path) -> None:
    """Salva o estado de tracks em GeoJSON compacto (precisão de coordenada
    limitada) — mantém o arquivo pequeno para o CI buscar/enviar a cada run."""
    try:
        state.to_file(str(path), driver="GeoJSON", COORDINATE_PRECISION=STATE_COORD_PRECISION)
    except TypeError:  # engine antiga sem a opção — salva sem limitar precisão
        state.to_file(str(path), driver="GeoJSON")


def persistence_tier(n: int, confirmed_min: int = CONFIRMED_MIN) -> str:
    """Map a sighting count to its persistence tier."""
    if n >= confirmed_min:
        return _ST_CONFIRMED
    if n >= 2:
        return _ST_CANDIDATE
    return _ST_FIRST


def empty_persistence_state() -> gpd.GeoDataFrame:
    """An empty track table (WGS84) for the first-ever observation."""
    return gpd.GeoDataFrame(
        {c: [] for c in _STATE_COLS}, geometry=[], crs="EPSG:4326"
    )


def _days_between(a: str, b: str) -> int:
    from datetime import date as _date
    return (_date.fromisoformat(str(a)) - _date.fromisoformat(str(b))).days


def update_tracks(
    current: gpd.GeoDataFrame,
    state: gpd.GeoDataFrame | None,
    date: str,
    *,
    grace_days: int = GRACE_DAYS,
    confirmed_min: int = CONFIRMED_MIN,
    min_overlap_frac: float = DEFAULT_MIN_OVERLAP_FRAC,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Chain this date's alerts to a running track state (gap-tolerant).

    Parameters
    ----------
    current : GeoDataFrame
        This date's alert polygons (any CRS).
    state : GeoDataFrame | None
        Running track table from the previous call (cols ``n_sightings``,
        ``first_seen``, ``last_seen``, geometry, WGS84) — ``None``/empty for the
        first date.
    date : str
        ``YYYY-MM-DD`` of ``current``.

    Returns
    -------
    (annotated_current, new_state)
        ``annotated_current`` (input CRS/order preserved) gains
        ``persistence_count`` (n_sightings), ``persistence_status``
        (first_observation/candidate/confirmed), ``first_seen`` and
        ``last_seen``. ``new_state`` (WGS84) is the pruned track table to pass to
        the next call (established tracks kept forever; others expire after
        ``grace_days``).
    """
    import numpy as np
    from shapely import area as _area
    from shapely import intersection as _intersection

    cur = current.reset_index(drop=True).copy()
    if cur.empty:
        return cur, (state if state is not None and len(state) else empty_persistence_state())

    cur_m = _to_metric(cur)
    cur_geom = np.asarray(cur_m.geometry.values, dtype=object)
    cur_area = _area(cur_geom)
    n = len(cur)

    have_state = state is not None and len(state) > 0
    if have_state:
        st = state.reset_index(drop=True).copy()
        st_m = _to_metric(st)
        st_geom = list(st_m.geometry.values)
        st_n = pd.to_numeric(st["n_sightings"], errors="coerce").fillna(1).astype(int).to_numpy()
        st_first = st["first_seen"].astype(str).tolist()
        st_last = st["last_seen"].astype(str).tolist()
        estab = st_n >= confirmed_min
        elig = estab | np.array([_days_between(date, ls) <= grace_days for ls in st_last])
    else:
        st_geom, st_n, st_first, st_last = [], np.array([], dtype=int), [], []
        elig = np.array([], dtype=bool)

    matched = np.full(n, -1, dtype=int)   # cur row -> state row index (or -1)
    if have_state and elig.any():
        eidx = np.where(elig)[0]
        right = gpd.GeoDataFrame({"__ti": eidx}, geometry=[st_geom[i] for i in eidx], crs=cur_m.crs)
        left = gpd.GeoDataFrame({"__ci": np.arange(n)}, geometry=list(cur_geom), crs=cur_m.crs)
        j = gpd.sjoin(left, right, predicate="intersects", how="inner")
        if len(j):
            cg = j.geometry.values
            pg = right.geometry.values[j["index_right"].to_numpy()]
            inter = _area(_intersection(cg, pg))
            ci = j["__ci"].to_numpy()
            frac = np.where(cur_area[ci] > 0, inter / cur_area[ci], 0.0)
            keep = frac >= min_overlap_frac
            best = (
                pd.DataFrame({"ci": ci[keep], "ti": j["__ti"].to_numpy()[keep], "frac": frac[keep]})
                .sort_values("frac", ascending=False).drop_duplicates("ci")
            )
            for c_, t_ in zip(best["ci"].astype(int), best["ti"].astype(int)):
                matched[c_] = t_

    # working copies of state (extend with new tracks)
    w_n = list(st_n.tolist())
    w_first = list(st_first)
    w_last = list(st_last)
    w_geom = list(st_geom)

    n_now = np.ones(n, dtype=int)
    first_seen = [date] * n

    by_track: dict[int, list[int]] = {}
    for c in range(n):
        if matched[c] >= 0:
            by_track.setdefault(int(matched[c]), []).append(c)
    for t, cis in by_track.items():
        w_n[t] += 1
        w_last[t] = date
        largest = cis[int(np.argmax(cur_area[cis]))]
        w_geom[t] = cur_geom[largest].simplify(STATE_SIMPLIFY_M)  # estado enxuto
        for c in cis:
            n_now[c] = w_n[t]
            first_seen[c] = w_first[t]
    for c in range(n):
        if matched[c] < 0:
            w_n.append(1); w_first.append(date); w_last.append(date)
            w_geom.append(cur_geom[c].simplify(STATE_SIMPLIFY_M))
            n_now[c] = 1; first_seen[c] = date

    # prune: keep established (permanent) or seen within grace_days
    keep = [
        i for i in range(len(w_n))
        if w_n[i] >= confirmed_min or _days_between(date, w_last[i]) <= grace_days
    ]
    new_state = gpd.GeoDataFrame(
        {"n_sightings": [int(w_n[i]) for i in keep],
         "first_seen": [w_first[i] for i in keep],
         "last_seen": [w_last[i] for i in keep]},
        geometry=[w_geom[i] for i in keep], crs=cur_m.crs,
    ).to_crs("EPSG:4326")

    cur["persistence_count"] = n_now
    cur["persistence_status"] = [persistence_tier(int(x), confirmed_min) for x in n_now]
    cur["first_seen"] = first_seen
    cur["last_seen"] = date
    return cur, new_state
