"""Area of Interest polygon loading and spatial operations.

Supports GeoJSON and GeoPackage formats. Falls back to the bounding box
rectangle from settings if no polygon file is found on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd
import xarray as xr
from loguru import logger
from shapely.geometry import box

from config.settings import AOI_BBOX, AOI_GEOJSON, TARGET_CRS


def load_aoi_polygon(
    path: Optional[Path] = None,
    target_crs: str = TARGET_CRS,
) -> gpd.GeoDataFrame:
    """Load the AOI polygon from a GeoJSON or GeoPackage file.

    Falls back to a rectangle built from ``AOI_BBOX`` if no polygon file is
    found on disk.

    Parameters
    ----------
    path : Path, optional
        Path to GeoJSON or GeoPackage.  If *None*, tries ``AOI_GEOPACKAGE``
        first, then ``AOI_GEOJSON`` from settings.
    target_crs : str
        Target CRS to reproject the polygon into.

    Returns
    -------
    gpd.GeoDataFrame
        GeoDataFrame with the AOI polygon(s) in *target_crs*.
    """
    if path is not None:
        candidates = [path]
    else:
        # Try GeoPackage first (more likely to be a real polygon),
        # then GeoJSON (which may be a simple bbox rectangle).
        from config.settings import AOI_DIR
        candidates = [
            AOI_DIR / "chapada_araripe.gpkg",
            AOI_GEOJSON,
        ]

    for candidate in candidates:
        if candidate.exists():
            gdf = gpd.read_file(str(candidate))
            logger.info(
                "Loaded AOI polygon from {} ({} feature(s), CRS={})",
                candidate.name,
                len(gdf),
                gdf.crs,
            )
            if gdf.crs is not None and str(gdf.crs) != target_crs:
                gdf = gdf.to_crs(target_crs)
                logger.debug("Reprojected AOI to {}", target_crs)
            return gdf

    # Fallback: build a rectangle from AOI_BBOX
    logger.warning(
        "No AOI polygon file found (tried {}), falling back to bounding box",
        [c.name for c in candidates],
    )
    west, south, east, north = AOI_BBOX
    gdf = gpd.GeoDataFrame(
        [{"geometry": box(west, south, east, north), "name": "AOI_BBOX"}],
        crs="EPSG:4326",
    )
    gdf = gdf.to_crs(target_crs)
    return gdf


def get_aoi_bbox_wgs84(path: Optional[Path] = None) -> list[float]:
    """Get the WGS84 bounding box of the AOI polygon.

    Used for STAC queries which require a ``[west, south, east, north]``
    bounding box in EPSG:4326.

    Parameters
    ----------
    path : Path, optional
        Path to polygon file.  If *None*, uses the same resolution order
        as :func:`load_aoi_polygon`.

    Returns
    -------
    list[float]
        ``[west, south, east, north]`` in WGS84.
    """
    if path is not None:
        candidates = [path]
    else:
        from config.settings import AOI_DIR
        candidates = [
            AOI_DIR / "chapada_araripe.gpkg",
            AOI_GEOJSON,
        ]

    for candidate in candidates:
        if candidate.exists():
            gdf = gpd.read_file(str(candidate))
            if gdf.crs is not None and str(gdf.crs) != "EPSG:4326":
                gdf = gdf.to_crs("EPSG:4326")
            bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
            bbox = [float(bounds[0]), float(bounds[1]),
                    float(bounds[2]), float(bounds[3])]
            logger.info(
                "AOI bbox from {}: [{:.4f}, {:.4f}, {:.4f}, {:.4f}]",
                candidate.name, *bbox,
            )
            return bbox

    logger.info("Using default AOI_BBOX from settings")
    return list(AOI_BBOX)


def clip_dataset_to_aoi(
    ds: xr.Dataset,
    aoi_gdf: Optional[gpd.GeoDataFrame] = None,
    all_touched: bool = True,
) -> xr.Dataset:
    """Clip an xarray Dataset to the AOI polygon.

    Parameters
    ----------
    ds : xr.Dataset
        Dataset with rioxarray CRS metadata (must have a CRS set).
    aoi_gdf : gpd.GeoDataFrame, optional
        AOI polygon in the **same CRS** as the dataset.  If *None*, loads
        and reprojects automatically via :func:`load_aoi_polygon`.
    all_touched : bool
        If *True*, all pixels touched by the polygon boundary are included.

    Returns
    -------
    xr.Dataset
        Clipped dataset (smaller spatial extent).
    """
    if aoi_gdf is None:
        # Infer the CRS from the dataset for reprojection
        ds_crs = None
        for var in ds.data_vars:
            if hasattr(ds[var], "rio") and ds[var].rio.crs is not None:
                ds_crs = str(ds[var].rio.crs)
                break
        aoi_gdf = load_aoi_polygon(target_crs=ds_crs or TARGET_CRS)

    # Ensure CRS is written to the dataset for rioxarray clip
    if not hasattr(ds, "rio") or ds.rio.crs is None:
        for var in ds.data_vars:
            if hasattr(ds[var], "rio") and ds[var].rio.crs is not None:
                ds = ds.rio.write_crs(ds[var].rio.crs)
                break

    geometries = aoi_gdf.geometry.values
    y_before = ds.sizes.get("y", "?")
    x_before = ds.sizes.get("x", "?")

    ds_clipped = ds.rio.clip(geometries, all_touched=all_touched)

    y_after = ds_clipped.sizes.get("y", "?")
    x_after = ds_clipped.sizes.get("x", "?")
    logger.info(
        "Clipped dataset from {}x{} to {}x{} pixels",
        y_before, x_before, y_after, x_after,
    )
    return ds_clipped
