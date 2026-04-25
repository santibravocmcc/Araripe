"""Interactive map creation using Leafmap and Folium."""

from __future__ import annotations

import json
from typing import Optional

import folium
import geopandas as gpd
import leafmap.foliumap as leafmap
from branca.element import MacroElement, Template
from loguru import logger

from config.settings import (
    AOI_DIR,
    DEFAULT_MAP_CENTER,
    DEFAULT_MAP_ZOOM,
    MAP_HEIGHT,
)

# ─── Basemap providers ───────────────────────────────────────────────────────
# (label, tile URL, attribution). Google hybrid is default.
BASEMAPS: list[tuple[str, str, str]] = [
    (
        "Google Satellite Hybrid",
        "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        "Google",
    ),
    (
        "Esri Satellite",
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "Esri",
    ),
    (
        "OpenStreetMap",
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "OpenStreetMap",
    ),
]

# ─── Protected-area boundaries (always added to every map) ───────────────────
PROTECTED_AREAS: list[tuple[str, str, str]] = [
    ("APA Chapada do Araripe", "APA_chapada_araripe.gpkg", "#FFD600"),
    ("FLONA Araripe-Apodi", "FLONA_araripe.gpkg", "#00E676"),
]


def _add_basemaps_folium(m: folium.Map) -> None:
    """Add the standard set of basemaps to a Folium map (first = default)."""
    for label, url, attr in BASEMAPS:
        folium.TileLayer(tiles=url, attr=attr, name=label, overlay=False, control=True).add_to(m)


def _load_protected_areas() -> list[tuple[str, gpd.GeoDataFrame, str]]:
    """Load each protected-area gpkg as a WGS84 GeoDataFrame.

    Returns
    -------
    list of (display_name, gdf_wgs84, color)
    """
    out: list[tuple[str, gpd.GeoDataFrame, str]] = []
    for name, fname, color in PROTECTED_AREAS:
        path = AOI_DIR / fname
        if not path.exists():
            continue
        try:
            gdf = gpd.read_file(str(path))
            if gdf.crs and str(gdf.crs) != "EPSG:4326":
                gdf = gdf.to_crs("EPSG:4326")
            out.append((name, gdf, color))
        except Exception as exc:
            logger.warning(f"Failed to load {fname}: {exc}")
    return out


def add_protected_areas(m) -> None:
    """Add APA and FLONA contours (no fill) to a Folium/Leafmap map."""
    for name, gdf, color in _load_protected_areas():
        # Strip non-serializable columns and ensure clean GeoJSON
        clean = gdf[["geometry"]].copy()
        gj = json.loads(clean.to_json())
        folium.GeoJson(
            gj,
            name=name,
            tooltip=name,
            style_function=lambda _f, c=color: {
                "fillColor": "transparent",
                "fillOpacity": 0,
                "color": c,
                "weight": 2.5,
            },
        ).add_to(m)

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

# Visual emphasis for alerts detected in the last few runs.
RECENT_BORDER_COLOR = "#E91E63"  # vivid magenta
RECENT_BORDER_WEIGHT = 4.0
NORMAL_BORDER_WEIGHT = 1.5


def _build_legend_html(
    title: str = "Alert Confidence",
    labels: dict[int, str] | None = None,
    recent_label: str | None = None,
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

    if recent_label:
        items += (
            f'<li style="margin:6px 0 0 0;display:flex;align-items:center;'
            f'border-top:1px solid #ddd;padding-top:6px;">'
            f'<span style="display:inline-block;width:18px;height:18px;'
            f"background:#FFD600;border:3px solid {RECENT_BORDER_COLOR};"
            f'border-radius:3px;margin-right:8px;flex-shrink:0;"></span>'
            f'<span style="font-size:13px;">{recent_label}</span>'
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
) -> leafmap.Map:
    """Create the dashboard base map.

    Default basemap is Google Satellite Hybrid; Esri Satellite and
    OpenStreetMap are also available via the layer control. The APA
    Chapada do Araripe and FLONA Araripe-Apodi contours are added
    automatically.
    """
    m = leafmap.Map(
        center=center,
        zoom=zoom,
        height=f"{MAP_HEIGHT}px",
        draw_control=False,
        measure_control=False,
        fullscreen_control=True,
        attribution_control=True,
    )

    # Remove every TileLayer leafmap added by default so our basemap order
    # (Google Hybrid first → default) is respected.
    for child_key in list(m._children):
        child = m._children[child_key]
        if isinstance(child, folium.raster_layers.TileLayer):
            del m._children[child_key]

    _add_basemaps_folium(m)
    add_protected_areas(m)
    return m


def add_alert_layer(
    m: leafmap.Map,
    alerts_gdf: gpd.GeoDataFrame,
    layer_name: str = "Deforestation Alerts",
    legend_labels: dict[int, str] | None = None,
    legend_title: str = "Alert Confidence",
    recent_dates: set[str] | None = None,
    recent_label: str | None = None,
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

    recent_dates = recent_dates or set()

    def style_function(feature):
        props = feature["properties"]
        conf = props.get("confidence", 1)
        is_recent = props.get("detection_date") in recent_dates
        return {
            "fillColor": CONFIDENCE_COLORS.get(conf, "#00E676"),
            "color": (
                RECENT_BORDER_COLOR
                if is_recent
                else CONFIDENCE_BORDER_COLORS.get(conf, "#000000")
            ),
            "weight": RECENT_BORDER_WEIGHT if is_recent else NORMAL_BORDER_WEIGHT,
            "fillOpacity": 0.6,
        }

    def highlight_function(feature):
        return {
            "fillOpacity": 0.85,
            "weight": RECENT_BORDER_WEIGHT + 1,
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
        title=legend_title, labels=legend_labels, recent_label=recent_label
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
    recent_dates: set[str] | None = None,
    recent_label: str | None = None,
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

    # Basemaps (first = default = Google Satellite Hybrid)
    _add_basemaps_folium(m)

    # Protected-area boundaries
    add_protected_areas(m)

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
    _recent = recent_dates or set()
    if alerts_gdf is not None and not alerts_gdf.empty:
        def style_fn(feature):
            props = feature["properties"]
            conf = props.get("confidence", 1)
            is_recent = props.get("detection_date") in _recent
            return {
                "fillColor": CONFIDENCE_COLORS.get(conf, "#00E676"),
                "color": (
                    RECENT_BORDER_COLOR
                    if is_recent
                    else CONFIDENCE_BORDER_COLORS.get(conf, "#000000")
                ),
                "weight": RECENT_BORDER_WEIGHT if is_recent else NORMAL_BORDER_WEIGHT,
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
    legend_html = _build_legend_html(
        title=legend_title, labels=legend_labels, recent_label=recent_label
    )
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
