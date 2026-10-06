"""Land-cover annotation, with the configured default rasters.

Everything lives in ``src.detection.landcover_core``; this module re-exports it
unchanged for the blue callers and adds the one thing the core refuses to do —
read the default rasters from ``config.settings``.  A green script imports
``landcover_core`` instead, because ``config.settings`` loads the production
``.env`` at import (``tests/test_assemble_green_run.py``, transitive guard).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from src.detection import landcover_core as _core
from src.detection.landcover_core import *  # noqa: F401,F403  (the public API, unchanged)
from src.detection.landcover_core import (  # noqa: F401  (private names tests and scripts read)
    _GROUP_OF_CLASS_10M,
    _GROUP_OF_CLASS_30M,
    _NATURAL,
    _TABLES,
    _class_label,
    _collection_suffix,
    _resolve_table,
)


def annotate_alerts_all_collections(
    alerts_gdf: gpd.GeoDataFrame,
    rasters: dict[str, str | Path] | None = None,
    all_touched: bool = True,
    default_collection: str = _core.DEFAULT_COLLECTION,
) -> gpd.GeoDataFrame:
    """``landcover_core.annotate_alerts_all_collections``, defaulting ``rasters``
    to ``config.settings.LANDCOVER_RASTERS`` as this function always has."""

    if rasters is None:
        from config.settings import LANDCOVER_RASTERS

        rasters = LANDCOVER_RASTERS
    return _core.annotate_alerts_all_collections(
        alerts_gdf, rasters=rasters, all_touched=all_touched,
        default_collection=default_collection,
    )
