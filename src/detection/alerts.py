"""Vectorize detected changes into alert polygons and manage alert storage."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import rasterio.features
import xarray as xr
from loguru import logger
from shapely.geometry import shape

from config.settings import ALERTS_DIR, MIN_ALERT_AREA_HA, TARGET_CRS


def vectorize_alerts(
    confidence: xr.DataArray,
    min_confidence: int = 1,
    min_area_ha: float = MIN_ALERT_AREA_HA,
) -> gpd.GeoDataFrame:
    """Convert raster confidence map to vector alert polygons.

    Groups connected pixels into polygons, filters by minimum area,
    and assigns confidence based on the maximum confidence in each polygon.

    Parameters
    ----------
    confidence : xr.DataArray
        Integer confidence raster (0=none, 1=low, 2=medium, 3=high).
    min_confidence : int
        Minimum confidence level to include.
    min_area_ha : float
        Minimum polygon area in hectares.

    Returns
    -------
    gpd.GeoDataFrame
        Alert polygons with columns: geometry, confidence, area_ha.
    """
    # Binary mask of alert pixels
    alert_mask = (confidence >= min_confidence).values.astype(np.uint8)

    if alert_mask.sum() == 0:
        logger.info("No alerts detected")
        return gpd.GeoDataFrame(
            columns=["geometry", "confidence", "area_ha"],
            crs=TARGET_CRS,
        )

    # Get the affine transform from the DataArray
    transform = confidence.rio.transform()

    # Vectorize connected components
    shapes_gen = rasterio.features.shapes(
        alert_mask,
        mask=alert_mask > 0,
        transform=transform,
    )

    records = []
    for geom, value in shapes_gen:
        polygon = shape(geom)

        # Compute area in hectares (assuming projected CRS in meters)
        area_ha = polygon.area / 10_000

        if area_ha < min_area_ha:
            continue

        # Get maximum confidence within this polygon
        # Use the confidence raster values within the polygon bounds
        records.append(
            {
                "geometry": polygon,
                "area_ha": round(area_ha, 2),
            }
        )

    if not records:
        logger.info("No alerts above minimum area threshold ({} ha)", min_area_ha)
        return gpd.GeoDataFrame(
            columns=["geometry", "confidence", "area_ha"],
            crs=TARGET_CRS,
        )

    gdf = gpd.GeoDataFrame(records, crs=TARGET_CRS)

    # Sample max confidence per polygon using zonal stats
    gdf["confidence"] = _assign_polygon_confidence(gdf, confidence)

    logger.info(
        "Vectorized {} alert polygons (total {:.1f} ha)",
        len(gdf),
        gdf["area_ha"].sum(),
    )
    return gdf


def _assign_polygon_confidence(
    gdf: gpd.GeoDataFrame,
    confidence: xr.DataArray,
) -> list[int]:
    """Assign max confidence value to each polygon via rasterization."""
    from rasterio.features import rasterize

    confidences = []
    conf_values = confidence.values

    transform = confidence.rio.transform()
    inv_transform = ~transform

    for _, row in gdf.iterrows():
        bounds = row.geometry.bounds  # minx, miny, maxx, maxy

        # Convert bounds to pixel coordinates
        col_min, row_min = inv_transform * (bounds[0], bounds[3])
        col_max, row_max = inv_transform * (bounds[2], bounds[1])

        r0 = max(0, int(row_min))
        r1 = min(conf_values.shape[0], int(row_max) + 1)
        c0 = max(0, int(col_min))
        c1 = min(conf_values.shape[1], int(col_max) + 1)

        if r0 >= r1 or c0 >= c1:
            confidences.append(1)
            continue

        window = conf_values[r0:r1, c0:c1]
        max_conf = int(np.nanmax(window)) if window.size > 0 else 1
        confidences.append(max_conf)

    return confidences


def save_alerts(
    gdf: gpd.GeoDataFrame,
    detection_date: str,
    alerts_dir: Path = ALERTS_DIR,
) -> Path:
    """Save alert polygons as a GeoJSON file.

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        Alert polygons.
    detection_date : str
        Date string for the filename (YYYY-MM-DD).
    alerts_dir : Path
        Output directory.

    Returns
    -------
    Path
        Path to the saved GeoJSON.
    """
    alerts_dir.mkdir(parents=True, exist_ok=True)

    # Convert to WGS84 for GeoJSON standard
    gdf_wgs84 = gdf.to_crs("EPSG:4326")

    # Add metadata
    gdf_wgs84["detection_date"] = detection_date
    gdf_wgs84["created_at"] = datetime.utcnow().isoformat()

    confidence_labels = {1: "low", 2: "medium", 3: "high"}
    gdf_wgs84["confidence_label"] = gdf_wgs84["confidence"].map(confidence_labels)

    filename = f"alerts_{detection_date}.geojson"
    path = alerts_dir / filename

    gdf_wgs84.to_file(str(path), driver="GeoJSON")
    logger.info("Saved {} alerts to {}", len(gdf_wgs84), path)
    return path


def load_alerts(
    date: Optional[str] = None,
    alerts_dir: Path = ALERTS_DIR,
) -> gpd.GeoDataFrame:
    """Load alert GeoJSON files.

    Parameters
    ----------
    date : str, optional
        Specific date to load (YYYY-MM-DD). If None, loads all alerts.
    alerts_dir : Path
        Directory containing alert GeoJSONs.

    Returns
    -------
    gpd.GeoDataFrame
        Combined alert polygons.
    """
    if date:
        path = alerts_dir / f"alerts_{date}.geojson"
        if not path.exists():
            raise FileNotFoundError(f"No alerts found for {date}")
        return gpd.read_file(str(path))

    # Load all alert files
    geojson_files = sorted(alerts_dir.glob("alerts_*.geojson"))
    if not geojson_files:
        return gpd.GeoDataFrame(
            columns=["geometry", "confidence", "area_ha", "detection_date"],
            crs="EPSG:4326",
        )

    gdfs = [gpd.read_file(str(f)) for f in geojson_files]
    combined = gpd.pd.concat(gdfs, ignore_index=True)
    logger.info("Loaded {} total alerts from {} files", len(combined), len(geojson_files))
    return gpd.GeoDataFrame(combined, crs="EPSG:4326")


def summarize_alerts(gdf: gpd.GeoDataFrame) -> dict:
    """Generate summary statistics from alert polygons.

    Returns
    -------
    dict
        Summary with total_alerts, total_area_ha, by_confidence counts.
    """
    if gdf.empty:
        return {
            "total_alerts": 0,
            "total_area_ha": 0.0,
            "by_confidence": {"high": 0, "medium": 0, "low": 0},
        }

    return {
        "total_alerts": len(gdf),
        "total_area_ha": round(gdf["area_ha"].sum(), 2),
        "by_confidence": {
            "high": int((gdf["confidence"] == 3).sum()),
            "medium": int((gdf["confidence"] == 2).sum()),
            "low": int((gdf["confidence"] == 1).sum()),
        },
    }
