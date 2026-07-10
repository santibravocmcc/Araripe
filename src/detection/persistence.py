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
