"""Interactive map creation using Leafmap and Folium."""

from __future__ import annotations

import json
from typing import Optional

import folium
import geopandas as gpd
import leafmap.foliumap as leafmap
from branca.element import MacroElement, Template
from loguru import logger

from config.settings import DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM, MAP_HEIGHT

# ─── Alert confidence color scheme ───────────────────────────────────────────
# Maximally distinct hues: red, blue, amber/yellow
CONFIDENCE_COLORS = {
    1: "#FFD600",  # Low: vivid amber-yellow
    2: "#2979FF",  # Medium: vivid blue
    3: "#FF1744",  # High: vivid red
}

CONFIDENCE_BORDER_COLORS = {
    1: "#F9A825",  # Low: darker amber
    2: "#0D47A1",  # Medium: darker blue
    3: "#B71C1C",  # High: darker red
}

CONFIDENCE_LABELS = {
    1: "Low",
    2: "Medium",
    3: "High",
}


def _build_legend_html(
    title: str = "Alert Confidence",
    labels: dict[int, str] | None = None,
) -> str:
    """Return HTML for a compact, styled map legend.

    Parameters
    ----------
    title : str
        Legend heading.
    labels : dict
        Mapping ``{confidence_int: display_label}``.
    """
    if labels is None:
        labels = CONFIDENCE_LABELS

    items = ""
    for conf_val in (3, 2, 1):  # high → low
        color = CONFIDENCE_COLORS[conf_val]
        border = CONFIDENCE_BORDER_COLORS[conf_val]
        label = labels.get(conf_val, CONFIDENCE_LABELS[conf_val])
        items += (
            f'<li style="margin:4px 0;display:flex;align-items:center;">'
            f'<span style="display:inline-block;width:18px;height:18px;'
            f"background:{color};border:2px solid {border};border-radius:3px;"
            f'margin-right:8px;flex-shrink:0;"></span>'
            f'<span style="font-size:13px;">{label}</span>'
            f"</li>"
        )

    return f"""
    <div id="map-legend" style="
        position:absolute;bottom:30px;right:10px;z-index:1000;
        background:rgba(255,255,255,0.92);padding:10px 14px;
        border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.25);
        font-family:Arial,sans-serif;max-width:180px;">
        <div style="font-weight:700;font-size:13px;margin-bottom:6px;
                    color:#333;">{title}</div>
        <ul style="list-style:none;margin:0;padding:0;">
            {items}
        </ul>
    </div>
    """


class _LegendControl(MacroElement):
    """Inject a custom HTML legend into a Folium/Leafmap map."""

    _template = Template("")

    def __init__(self, html: str):
        super().__init__()
        self._template = Template(
            "{% macro html(this, kwargs) %}" + html + "{% endmacro %}"
        )


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
    legend_labels: dict[int, str] | None = None,
    legend_title: str = "Alert Confidence",
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
    legend_labels : dict, optional
        Custom legend labels per confidence level.
    legend_title : str
        Legend heading text.

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
            "fillColor": CONFIDENCE_COLORS.get(conf, "#00E676"),
            "color": CONFIDENCE_BORDER_COLORS.get(conf, "#000000"),
            "weight": 1.5,
            "fillOpacity": 0.6,
        }

    def highlight_function(feature):
        return {
            "fillOpacity": 0.85,
            "weight": 3,
        }

    # Convert to plain Python types to avoid JSON serialization failures.
    alerts_gdf = alerts_gdf.copy()
    for col in alerts_gdf.columns:
        if col == "geometry":
            continue
        if alerts_gdf[col].dtype.kind == "M":  # datetime64
            alerts_gdf[col] = alerts_gdf[col].dt.strftime("%Y-%m-%d")
        elif alerts_gdf[col].dtype.kind == "m":  # timedelta
            alerts_gdf[col] = alerts_gdf[col].astype(str)
    geojson_data = json.loads(alerts_gdf.to_json())

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

    # Add custom HTML legend
    legend_html = _build_legend_html(
        title=legend_title, labels=legend_labels
    )
    legend = _LegendControl(legend_html)
    m.get_root().html.add_child(legend)

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


def create_export_map(
    alerts_gdf: gpd.GeoDataFrame,
    legend_labels: dict[int, str] | None = None,
    legend_title: str = "Alert Confidence",
) -> folium.Map:
    """Create a Folium map with drawing tools for export selection.

    This map uses plain Folium (not Leafmap) so it works with
    ``streamlit-folium``'s ``st_folium`` which returns drawn shapes.

    Parameters
    ----------
    alerts_gdf : gpd.GeoDataFrame
        Alert polygons already filtered by the user.
    legend_labels : dict, optional
        Custom confidence labels.
    legend_title : str
        Legend heading.

    Returns
    -------
    folium.Map
        Folium map with Draw plugin and alert layer.
    """
    from folium.plugins import Draw

    # Determine bounds for initial view
    if alerts_gdf is not None and not alerts_gdf.empty:
        if alerts_gdf.crs and str(alerts_gdf.crs) != "EPSG:4326":
            alerts_gdf = alerts_gdf.to_crs("EPSG:4326")
        bounds = alerts_gdf.total_bounds  # [minx, miny, maxx, maxy]
        center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
    else:
        center = DEFAULT_MAP_CENTER

    m = folium.Map(location=center, zoom_start=DEFAULT_MAP_ZOOM, tiles=None)

    # Basemaps
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri Satellite",
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)

    # Draw plugin — only rectangle and polygon
    Draw(
        export=False,
        draw_options={
            "polyline": False,
            "circle": False,
            "circlemarker": False,
            "marker": False,
            "polygon": {"allowIntersection": False, "shapeOptions": {"color": "#00BCD4", "weight": 3}},
            "rectangle": {"shapeOptions": {"color": "#00BCD4", "weight": 3}},
        },
        edit_options={"edit": False},
    ).add_to(m)

    # Add alert polygons
    if alerts_gdf is not None and not alerts_gdf.empty:
        def style_fn(feature):
            conf = feature["properties"].get("confidence", 1)
            return {
                "fillColor": CONFIDENCE_COLORS.get(conf, "#00E676"),
                "color": CONFIDENCE_BORDER_COLORS.get(conf, "#000000"),
                "weight": 1.5,
                "fillOpacity": 0.6,
            }

        alerts_clean = alerts_gdf.copy()
        for col in alerts_clean.columns:
            if col == "geometry":
                continue
            if alerts_clean[col].dtype.kind == "M":
                alerts_clean[col] = alerts_clean[col].dt.strftime("%Y-%m-%d")
            elif alerts_clean[col].dtype.kind == "m":
                alerts_clean[col] = alerts_clean[col].astype(str)
        geojson_data = json.loads(alerts_clean.to_json())

        folium.GeoJson(
            geojson_data,
            name="Alerts",
            style_function=style_fn,
            tooltip=folium.GeoJsonTooltip(
                fields=["area_ha", "confidence_label", "detection_date"],
                aliases=["Area (ha):", "Confidence:", "Date:"],
                style="font-size: 12px;",
            ),
        ).add_to(m)

        # Fit bounds
        m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]], padding=[30, 30])

    # Legend
    legend_html = _build_legend_html(title=legend_title, labels=legend_labels)
    legend_ctrl = _LegendControl(legend_html)
    m.get_root().html.add_child(legend_ctrl)

    folium.LayerControl().add_to(m)
    return m


def add_legend(m: leafmap.Map) -> leafmap.Map:
    """Add a deforestation alert confidence legend to the map."""
    legend_dict = {
        "High Confidence": CONFIDENCE_COLORS[3],
        "Medium Confidence": CONFIDENCE_COLORS[2],
        "Low Confidence": CONFIDENCE_COLORS[1],
        "Study Area": "#2196F3",
    }
    m.add_legend(title="Alert Confidence", legend_dict=legend_dict)
    return m
