"""Land-cover context for deforestation alerts (MapBiomas integration).

The detection pipeline is purely spectral (NDMI/NBR/EVI2 anomalies) and, on its
own, cannot tell *what was there before*. A large share of z-score alerts fall
on land that is already anthropic (pasture, agriculture, urban) where a moisture
drop is management, not new clearing. This module adds a land-cover *context*
layer — from any MapBiomas classification raster (30 m Collection 10 or the
cropped 10 m Collection 2 beta, data/landcover/) — so alerts can be:

  * annotated with their dominant land-cover class / group and the fraction of
    natural vegetation they overlap, and
  * optionally filtered to those that intersect natural vegetation (the alerts
    most consistent with genuine deforestation/degradation).

This keeps land cover as an interpretation/stratification aid, not a detection
input — a deliberate, conservative form of integration (see AUDITORIA_TECNICA.md,
Task 4).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from loguru import logger
from rasterio.mask import mask as rio_mask

# ─── Per-collection reclassification tables ──────────────────────────────────
# MapBiomas class code → coarse group. The class *taxonomies differ between
# collections* (verified against the two ATBDs), so each collection needs its
# own table — do NOT assume the numeric codes coincide:
#   * Collection 2 (10 m, beta, 2016–2023, Sentinel-2) follows the Collection 9
#     level-3 legend: 21 classes, agriculture is 18/19/36 with NO crop-level
#     subdivisions, and there is no photovoltaic (75) class.
#   * Collection 10.1 (30 m, 1985–2024, Landsat) subdivides crops to level 4
#     (39 Soybean, 20 Sugar cane, 40 Rice, 62 Cotton, 41 Other Temporary,
#     46 Coffee, 47 Citrus, 35 Palm Oil, 48 Other Perennial) and adds 75
#     (Photovoltaic Power Plant).
# Codes not listed fall through to "other" at the call site.

# Collection 2 beta (10 m) — Sentinel-2
_GROUP_OF_CLASS_10M = {
    # natural vegetation (forest + natural herbaceous/shrub)
    3: "natural", 4: "natural", 5: "natural", 6: "natural", 11: "natural",
    12: "natural", 49: "natural", 50: "natural",
    # farming: pasture, agriculture (18/19/36), forest plantation, mosaic
    9: "farming", 15: "farming", 18: "farming", 19: "farming", 21: "farming",
    36: "farming",
    # urban / mining
    24: "urban", 30: "urban",
    # other non-vegetated (beach/dune, other non-veg, rocky outcrop, tidal flat)
    23: "other", 25: "other", 29: "other", 32: "other",
    # water
    26: "water", 31: "water", 33: "water",
    # no-data
    0: "nodata", 27: "nodata",
}

# Collection 10.1 (30 m) — Landsat (with level-4 crop + photovoltaic codes)
_GROUP_OF_CLASS_30M = {
    3: "natural", 4: "natural", 5: "natural", 6: "natural", 11: "natural",
    12: "natural", 49: "natural", 50: "natural",
    # farming incl. crop subdivisions unique to Collection 10
    9: "farming", 15: "farming", 18: "farming", 19: "farming", 20: "farming",
    21: "farming", 35: "farming", 36: "farming", 39: "farming", 40: "farming",
    41: "farming", 46: "farming", 47: "farming", 48: "farming", 62: "farming",
    # urban / mining / photovoltaic (75 is Collection 10 only)
    24: "urban", 30: "urban", 75: "urban",
    23: "other", 25: "other", 29: "other", 32: "other",
    26: "water", 31: "water", 33: "water",
    0: "nodata", 27: "nodata",
}

_TABLES = {
    "mapbiomas10m": _GROUP_OF_CLASS_10M,
    "mapbiomas30m": _GROUP_OF_CLASS_30M,
}
_NATURAL = {k: {c for c, g in t.items() if g == "natural"} for k, t in _TABLES.items()}

DEFAULT_COLLECTION = "mapbiomas10m"

# Backward-compatible module aliases (default = 10 m collection).
GROUP_OF_CLASS = _GROUP_OF_CLASS_10M
NATURAL_CLASSES = _NATURAL[DEFAULT_COLLECTION]


def _resolve_table(collection: str) -> tuple[dict[int, str], set[int]]:
    if collection not in _TABLES:
        raise ValueError(
            f"Unknown land-cover collection {collection!r}; "
            f"expected one of {sorted(_TABLES)}"
        )
    return _TABLES[collection], _NATURAL[collection]


def _class_label(code: int) -> str:
    from scripts.mapbiomas10m_crop import label  # reuse the legend
    try:
        return label(code)
    except Exception:
        return f"class {code}"


def annotate_alerts_with_landcover(
    alerts_gdf: gpd.GeoDataFrame,
    landcover_path: str | Path,
    all_touched: bool = True,
    collection: str = DEFAULT_COLLECTION,
    col_suffix: str = "",
) -> gpd.GeoDataFrame:
    """Add land-cover context columns to an alerts GeoDataFrame.

    For each alert polygon, reads the underlying MapBiomas pixels and adds
    (``col_suffix`` is appended to each column name, e.g. ``"_10m"``):
      - ``lc_class{suffix}``        : dominant (modal) MapBiomas class code
      - ``lc_group{suffix}``        : dominant coarse group (natural/farming/…)
      - ``lc_natural_frac{suffix}`` : fraction of alert pixels that are natural veg

    The alerts are reprojected to the raster CRS for the zonal read; the returned
    GeoDataFrame keeps the input CRS and geometry.

    Parameters
    ----------
    alerts_gdf : GeoDataFrame
        Alert polygons (any CRS).
    landcover_path : str | Path
        Path to a single-band MapBiomas classification GeoTIFF.
    all_touched : bool
        Passed to rasterio.mask — include pixels touched by tiny polygons.
    collection : str
        Which MapBiomas taxonomy to reclassify against: ``"mapbiomas10m"``
        (Collection 2 beta) or ``"mapbiomas30m"`` (Collection 10.1). The two
        legends differ (crop subdivisions, photovoltaic class), so pass the one
        matching ``landcover_path``.
    col_suffix : str
        Suffix appended to the output column names so several collections can be
        annotated side by side (e.g. ``"_10m"`` and ``"_30m"``).
    """
    table, natural = _resolve_table(collection)
    if alerts_gdf.empty:
        return alerts_gdf.copy()

    out = alerts_gdf.copy()
    with rasterio.open(str(landcover_path)) as src:
        gdf_r = out.to_crs(src.crs)
        classes, groups, nat_fracs = [], [], []
        for geom in gdf_r.geometry:
            try:
                arr, _ = rio_mask(src, [geom.__geo_interface__], crop=True,
                                  all_touched=all_touched, filled=True, nodata=0)
                vals = arr[0].ravel()
                vals = vals[vals != 0]  # drop nodata / outside
            except Exception:
                vals = np.array([], dtype="uint8")
            if vals.size == 0:
                classes.append(None); groups.append(None); nat_fracs.append(np.nan)
                continue
            codes, counts = np.unique(vals, return_counts=True)
            dom = int(codes[counts.argmax()])
            classes.append(dom)
            groups.append(table.get(dom, "other"))
            nat_fracs.append(round(float(np.isin(vals, list(natural)).mean()), 3))

    out[f"lc_class{col_suffix}"] = classes
    out[f"lc_group{col_suffix}"] = groups
    out[f"lc_natural_frac{col_suffix}"] = nat_fracs
    logger.info(
        "Annotated {} alerts with land cover from {} [{}] "
        "(natural-vegetation median frac={:.2f})",
        len(out), Path(landcover_path).name, collection,
        float(np.nanmedian([f for f in nat_fracs if f == f]) if any(f == f for f in nat_fracs) else float("nan")),
    )
    return out


def _collection_suffix(collection: str) -> str:
    """'mapbiomas10m' -> '_10m', 'mapbiomas30m' -> '_30m'."""
    return "_" + collection.replace("mapbiomas", "")


def annotate_alerts_all_collections(
    alerts_gdf: gpd.GeoDataFrame,
    rasters: dict[str, str | Path] | None = None,
    all_touched: bool = True,
    default_collection: str = DEFAULT_COLLECTION,
) -> gpd.GeoDataFrame:
    """Annotate alerts with EVERY available MapBiomas collection, side by side.

    Each collection gets its own suffixed columns (``lc_group_10m`` /
    ``lc_natural_frac_10m`` and ``lc_group_30m`` / …), so the front-end can let
    the user pick which collection to characterise/filter alerts by — without
    losing the other. The ``default_collection`` is also copied to the unsuffixed
    ``lc_class``/``lc_group``/``lc_natural_frac`` columns for backward
    compatibility with existing consumers.

    ``rasters`` maps collection key -> raster path (defaults to config
    ``LANDCOVER_RASTERS``); collections whose file is missing are skipped.
    """
    if rasters is None:
        from config.settings import LANDCOVER_RASTERS
        rasters = LANDCOVER_RASTERS
    if alerts_gdf.empty:
        return alerts_gdf.copy()

    out = alerts_gdf
    annotated_any = []
    for collection, path in rasters.items():
        if collection not in _TABLES:
            logger.warning("Skipping unknown land-cover collection {!r}", collection)
            continue
        if not Path(path).exists():
            logger.warning("Land-cover raster for {} missing ({}); skipping", collection, path)
            continue
        out = annotate_alerts_with_landcover(
            out, path, all_touched=all_touched, collection=collection,
            col_suffix=_collection_suffix(collection),
        )
        annotated_any.append(collection)

    # Mirror the default collection into the unsuffixed legacy columns.
    if default_collection in annotated_any:
        sfx = _collection_suffix(default_collection)
        for base in ("lc_class", "lc_group", "lc_natural_frac"):
            out[base] = out[f"{base}{sfx}"]
    if not annotated_any:
        logger.warning("No land-cover collections annotated (no rasters found).")
    return out


def filter_alerts_by_natural_vegetation(
    alerts_gdf: gpd.GeoDataFrame,
    landcover_path: str | Path,
    min_natural_frac: float = 0.5,
    collection: str = DEFAULT_COLLECTION,
    all_touched: bool = True,
) -> gpd.GeoDataFrame:
    """Keep only alerts whose natural-vegetation overlap fraction >= threshold.

    Alerts that already sit on pasture/agriculture/urban land are unlikely to be
    *new* clearing; dropping them is a simple, transparent false-positive filter.
    Returns the annotated + filtered GeoDataFrame.
    """
    annotated = annotate_alerts_with_landcover(
        alerts_gdf, landcover_path, all_touched=all_touched, collection=collection
    )
    if annotated.empty:
        return annotated
    kept = annotated[annotated["lc_natural_frac"].fillna(0) >= min_natural_frac].copy()
    logger.info("Natural-vegetation filter [{}]: kept {}/{} alerts (>= {:.0%} natural)",
                collection, len(kept), len(annotated), min_natural_frac)
    return kept
