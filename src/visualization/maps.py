"""Interactive map creation using Leafmap and Folium."""

from __future__ import annotations

from typing import Optional

import folium
import geopandas as gpd
import leafmap.foliumap as leafmap
from loguru import logger

from config.settings import DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM, MAP_HEIGHT

# ─── Alert confidence color scheme ───────────────────────────────────────────
CONFIDENCE_COLORS = {
    1: "#FFC107",  # Low: amber
    2: "#FF9800",  # Medium: orange
    3: "#F44336",  # High: red
}

CONFIDENCE_LABELS = {
    1: "Low",
    2: "Medium",
    3: "High",
}


def create_base_map(
    center: list[float] = DEFAULT_MAP_CENTER,
    zoom: int = DEFAULT_MAP_ZOOM,
    basemap: str = "Esri.WorldImagery",
) -> leafmap.Map:
    """Create a base Leafmap instance with satellite imagery basemap.

    Parameters
    ----------
    center : list[float]
        Map center [lat, lon].
    zoom : int
        Initial zoom level.
    basemap : str
        Basemap name from leafmap/leaflet providers.

    Returns
    -------
    leafmap.Map
        Configured map instance.
    """
    m = leafmap.Map(
        center=center,
        zoom=zoom,
        height=f"{MAP_HEIGHT}px",
    )
    m.add_basemap(basemap)
    m.add_basemap("OpenStreetMap")
    return m


def add_alert_layer(
    m: leafmap.Map,
    alerts_gdf: gpd.GeoDataFrame,
    layer_name: str = "Deforestation Alerts",
) -> leafmap.Map:
    """Add alert polygons to the map with confidence-based styling.

    Parameters
    ----------
    m : leafmap.Map
        Map instance.
    alerts_gdf : gpd.GeoDataFrame
        Alert polygons (must be in EPSG:4326).
    layer_name : str
        Layer name in the layer control.

    Returns
    -------
    leafmap.Map
        Map with alert layer added.
    """
    if alerts_gdf.empty:
        logger.info("No alerts to display")
        return m

    # Ensure WGS84
    if alerts_gdf.crs and str(alerts_gdf.crs) != "EPSG:4326":
        alerts_gdf = alerts_gdf.to_crs("EPSG:4326")

    def style_function(feature):
        conf = feature["properties"].get("confidence", 1)
        return {
            "fillColor": CONFIDENCE_COLORS.get(conf, "#FFC107"),
            "color": "#000000",
            "weight": 1,
            "fillOpacity": 0.6,
        }

    def highlight_function(feature):
        return {
            "fillOpacity": 0.8,
            "weight": 3,
        }

    # Build popup content
    geojson_data = alerts_gdf.__geo_interface__

    geojson_layer = folium.GeoJson(
        geojson_data,
        name=layer_name,
        style_function=style_function,
        highlight_function=highlight_function,
        tooltip=folium.GeoJsonTooltip(
            fields=["area_ha", "confidence_label", "detection_date"],
            aliases=["Area (ha):", "Confidence:", "Date:"],
            style="font-size: 12px;",
        ),
    )

    geojson_layer.add_to(m)
    return m


def add_cog_layer(
    m: leafmap.Map,
    url: str,
    name: str = "Raster Layer",
    colormap: str = "RdYlGn",
    opacity: float = 0.7,
    vmin: float = -1.0,
    vmax: float = 1.0,
) -> leafmap.Map:
    """Add a Cloud Optimized GeoTIFF layer to the map.

    Streams tiles directly from the COG URL — only downloads
    pixels visible at the current zoom level.

    Parameters
    ----------
    m : leafmap.Map
        Map instance.
    url : str
        URL of the COG file (e.g., Cloudflare R2 URL).
    name : str
        Layer name.
    colormap : str
        Matplotlib/rio-tiler colormap name.
    opacity : float
        Layer opacity (0–1).
    vmin, vmax : float
        Value range for colormap scaling.
    """
    m.add_cog_layer(
        url,
        name=name,
        colormap_name=colormap,
        opacity=opacity,
        rescale=f"{vmin},{vmax}",
    )
    return m


def create_split_map(
    left_url: str,
    right_url: str,
    left_label: str = "Before",
    right_label: str = "After",
    center: list[float] = DEFAULT_MAP_CENTER,
    zoom: int = DEFAULT_MAP_ZOOM,
) -> leafmap.Map:
    """Create a split-panel before/after comparison map.

    Parameters
    ----------
    left_url : str
        COG URL for the left (before) panel.
    right_url : str
        COG URL for the right (after) panel.
    left_label, right_label : str
        Labels for each panel.
    center : list[float]
        Map center.
    zoom : int
        Initial zoom.

    Returns
    -------
    leafmap.Map
        Split-panel map.
    """
    m = leafmap.Map(center=center, zoom=zoom)
    m.split_map(
        left_layer=left_url,
        right_layer=right_url,
    )
    return m


def add_aoi_boundary(
    m: leafmap.Map,
    aoi_path: str,
    layer_name: str = "Study Area",
) -> leafmap.Map:
    """Add the AOI boundary polygon to the map.

    Parameters
    ----------
    m : leafmap.Map
        Map instance.
    aoi_path : str
        Path to the AOI GeoJSON file.
    layer_name : str
        Layer name.
    """
    m.add_geojson(
        aoi_path,
        layer_name=layer_name,
        style={
            "fillColor": "transparent",
            "color": "#2196F3",
            "weight": 3,
            "dashArray": "5, 10",
        },
    )
    return m


def add_legend(m: leafmap.Map) -> leafmap.Map:
    """Add a deforestation alert confidence legend to the map."""
    legend_dict = {
        "High Confidence": "#F44336",
        "Medium Confidence": "#FF9800",
        "Low Confidence": "#FFC107",
        "Study Area": "#2196F3",
    }
    m.add_legend(title="Alert Confidence", legend_dict=legend_dict)
    return m
