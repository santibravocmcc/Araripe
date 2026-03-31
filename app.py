"""Araripe Deforestation Monitor — Streamlit Dashboard.

Interactive dashboard for visualizing deforestation alerts and vegetation
time series across Chapada do Araripe (CE/PE/PI, Brazil).

Run locally:
    streamlit run app.py

Deploy on Hugging Face Spaces or Streamlit Community Cloud.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import ALERTS_DIR, AOI_GEOJSON, TIMESERIES_DIR
from src.detection.alerts import load_alerts, summarize_alerts
from src.timeseries.builder import load_alert_timeseries, load_timeseries
from src.visualization.charts import (
    alert_summary_chart,
    cumulative_area_chart,
    multi_index_chart,
    timeseries_chart,
)
from src.visualization.dashboard import (
    render_info_expander,
    render_metrics,
    render_sidebar,
    render_trend_indicator,
)
from src.visualization.maps import (
    add_alert_layer,
    create_base_map,
)

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Araripe Deforestation Monitor",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom theme / CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Metric cards with visible borders */
    [data-testid="stMetric"] {
        background: rgba(28, 131, 225, 0.08);
        border: 1px solid rgba(28, 131, 225, 0.25);
        border-radius: 8px;
        padding: 14px 16px;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: 700;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.9rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }
    /* Tab styling — green accent instead of red */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 10px 24px;
        font-size: 0.95rem;
        font-weight: 500;
    }
    /* Spacing between metrics and tabs */
    .stTabs {
        margin-top: 1rem;
    }
    /* Index info cards */
    .index-card {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 8px;
    }
    .index-card h4 { margin: 0 0 6px 0; font-size: 1.1rem; }
    .index-card p { margin: 0 0 4px 0; font-size: 0.85rem; opacity: 0.85; line-height: 1.4; }
    .index-card code { font-size: 0.8rem; background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 4px; }
</style>
""", unsafe_allow_html=True)

# ─── Sidebar ──────────────────────────────────────────────────────────────────
filters = render_sidebar()


# ─── Data loading (cached) ────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_alerts():
    """Load all alert GeoJSONs."""
    try:
        return load_alerts()
    except Exception:
        return None


@st.cache_data(ttl=3600)
def get_timeseries(index_name, start_date, end_date):
    """Load time series for a given index."""
    try:
        return load_timeseries(index_name, start_date=start_date, end_date=end_date)
    except Exception:
        return None


@st.cache_data(ttl=3600)
def get_alert_timeseries(start_date, end_date):
    """Load alert statistics time series."""
    try:
        return load_alert_timeseries(start_date=start_date, end_date=end_date)
    except Exception:
        return None


# ─── Vegetation index descriptions ──────────────────────────────────────────
INDEX_INFO = {
    "ndmi": {
        "name": "NDMI",
        "full_name": "Normalized Difference Moisture Index",
        "formula": "(NIR - SWIR1) / (NIR + SWIR1)",
        "description": "Sensitive to canopy water content. Best for detecting "
                       "early-stage deforestation where trees are cut but stumps remain. "
                       "Primary index for this monitoring system.",
        "color": "#2196F3",
        "use": "Primary detection index",
    },
    "nbr": {
        "name": "NBR",
        "full_name": "Normalized Burn Ratio",
        "formula": "(NIR - SWIR2) / (NIR + SWIR2)",
        "description": "Responds to both fire damage and clearing. Strong signal for "
                       "burned areas and complete canopy removal. Confirms NDMI detections.",
        "color": "#9C27B0",
        "use": "Confirmation index (fire + clearing)",
    },
    "evi2": {
        "name": "EVI2",
        "full_name": "Enhanced Vegetation Index 2",
        "formula": "2.5 * (NIR - RED) / (NIR + 2.4 * RED + 1)",
        "description": "Measures green vegetation vigor with reduced soil background influence. "
                       "Less affected by atmospheric conditions than NDVI. "
                       "Useful for detecting gradual degradation.",
        "color": "#FF9800",
        "use": "Degradation tracking",
    },
}


# ─── Main content ─────────────────────────────────────────────────────────────
st.title("Araripe Deforestation Monitor")
st.caption(
    "Satellite-based weekly deforestation monitoring for "
    "Chapada do Araripe (CE/PE/PI, Brazil)"
)

# Load data
alerts_gdf = get_alerts()
alert_ts = get_alert_timeseries(filters["start_date"], filters["end_date"])

# ─── Filter alerts by sidebar controls (date, confidence, min area) ──────────
if alerts_gdf is not None and not alerts_gdf.empty:
    # Date filter
    if "detection_date" in alerts_gdf.columns:
        date_col = pd.to_datetime(alerts_gdf["detection_date"], errors="coerce")
        start = pd.Timestamp(filters["start_date"])
        end = pd.Timestamp(filters["end_date"])
        date_mask = (date_col >= start) & (date_col <= end)
    else:
        date_mask = pd.Series(True, index=alerts_gdf.index)

    # Confidence filter (multiselect → list of ints)
    conf_mask = alerts_gdf["confidence"].isin(filters["confidence_values"])

    # Min area filter
    area_mask = pd.Series(True, index=alerts_gdf.index)
    if "area_ha" in alerts_gdf.columns and filters["min_area"] > 0:
        area_mask = alerts_gdf["area_ha"] >= filters["min_area"]

    filtered_alerts = alerts_gdf[date_mask & conf_mask & area_mask]
    summary = summarize_alerts(filtered_alerts)
else:
    filtered_alerts = None
    summary = {
        "total_alerts": 0,
        "total_area_ha": 0,
        "by_confidence": {"high": 0, "medium": 0, "low": 0},
    }

# ─── Handle "View on Map" button ─────────────────────────────────────────────
# When pressed, snapshot the current filtered alert indices for the map.
# The map only re-renders with new data when this button is pressed.
if filters["view_on_map"] and filtered_alerts is not None and not filtered_alerts.empty:
    st.session_state["map_alert_idx"] = filtered_alerts.index.tolist()
elif "map_alert_idx" not in st.session_state:
    # First load — show all filtered alerts on map
    if filtered_alerts is not None and not filtered_alerts.empty:
        st.session_state["map_alert_idx"] = filtered_alerts.index.tolist()

# Metrics row
render_metrics(summary)

if alerts_gdf is None or alerts_gdf.empty:
    st.info(
        "No alert data available yet. Run the detection pipeline first: "
        "`python scripts/run_detection.py`"
    )

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_map, tab_timeseries, tab_alerts, tab_about = st.tabs(
    ["Map", "Time Series", "Alert History", "About"]
)

# ─── Tab 1: Interactive Map + Alert Explorer ─────────────────────────────────
with tab_map:
    # ─── Build table with IDs (needed for display) ──────────────────────
    _table_df = None
    if filtered_alerts is not None and not filtered_alerts.empty:
        _display_df = filtered_alerts.copy()
        if _display_df.crs and str(_display_df.crs) != "EPSG:4326":
            _display_df = _display_df.to_crs("EPSG:4326")
        centroids = _display_df.geometry.centroid
        _display_df["latitude"] = centroids.y.round(5)
        _display_df["longitude"] = centroids.x.round(5)
        if "detection_date" in _display_df.columns:
            _display_df["detection_date"] = pd.to_datetime(
                _display_df["detection_date"], errors="coerce"
            ).dt.strftime("%Y-%m-%d")
        _display_df = _display_df.sort_values(
            "area_ha", ascending=False
        ).reset_index(drop=True)
        _display_df["alert_id"] = range(1, len(_display_df) + 1)

        show_cols = [
            "alert_id", "detection_date", "confidence_label", "area_ha",
            "latitude", "longitude",
        ]
        show_cols = [c for c in show_cols if c in _display_df.columns]
        _table_df = _display_df[show_cols].rename(columns={
            "alert_id": "ID",
            "detection_date": "Date",
            "confidence_label": "Confidence",
            "area_ha": "Area (ha)",
            "latitude": "Lat",
            "longitude": "Lon",
        })

    # ─── Map ────────────────────────────────────────────────────────────
    st.subheader("Deforestation Alert Map")

    # Resolve which alerts to render on map (from session_state snapshot)
    map_idx = st.session_state.get("map_alert_idx")
    if map_idx is not None and alerts_gdf is not None:
        map_alerts_gdf = alerts_gdf.loc[
            alerts_gdf.index.isin(map_idx)
        ]
        if map_alerts_gdf.crs and str(map_alerts_gdf.crs) != "EPSG:4326":
            map_alerts_gdf = map_alerts_gdf.to_crs("EPSG:4326")
        n_map = len(map_alerts_gdf)
        st.caption(
            f"Showing **{n_map}** alert{'s' if n_map != 1 else ''} on map. "
            f"Change filters in the sidebar and press **View on Map** to update."
        )
    else:
        map_alerts_gdf = None

    # Compute bounds for zoom-to-fit
    _map_bounds = None
    if map_alerts_gdf is not None and not map_alerts_gdf.empty:
        bounds = map_alerts_gdf.total_bounds  # [minx, miny, maxx, maxy]
        _map_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]

    m = create_base_map()

    if map_alerts_gdf is not None and not map_alerts_gdf.empty:
        add_alert_layer(m, map_alerts_gdf)

    if _map_bounds is not None:
        m.fit_bounds(_map_bounds, padding=[30, 30])

    try:
        from streamlit_folium import st_folium

        st_folium(m, width=None, height=600, returned_objects=[])
    except ImportError:
        st.warning(
            "Install `streamlit-folium` for interactive maps: "
            "`pip install streamlit-folium`"
        )

    # ─── Alert Explorer (table — filters are in the sidebar) ──────────
    if _table_df is not None and not _table_df.empty:
        st.markdown("---")
        st.subheader("Alert Explorer")
        st.caption(
            f"Showing **{len(_table_df)}** alerts matching current filters. "
            f"Adjust filters in the sidebar, then press **View on Map** to "
            f"update the map."
        )

        st.dataframe(
            _table_df,
            use_container_width=True,
            height=400,
            column_config={
                "ID": st.column_config.NumberColumn("ID", width="small"),
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Confidence": st.column_config.TextColumn(
                    "Confidence", width="small"
                ),
                "Area (ha)": st.column_config.NumberColumn(
                    "Area (ha)", format="%.2f", width="small"
                ),
                "Lat": st.column_config.NumberColumn(
                    "Lat", format="%.5f", width="small"
                ),
                "Lon": st.column_config.NumberColumn(
                    "Lon", format="%.5f", width="small"
                ),
            },
        )

        st.caption(
            f"Total area: {_table_df['Area (ha)'].sum():,.1f} ha"
        )

# ─── Tab 2: Time Series ──────────────────────────────────────────────────────
with tab_timeseries:
    st.subheader("Vegetation Index Time Series")

    # ─── Index explanation ───────────────────────────────────────────────
    with st.expander("What are these indices? Which should I use?", expanded=False):
        st.markdown(
            "These spectral indices are computed from satellite bands and measure "
            "different vegetation properties. **For deforestation monitoring, enable "
            "all three** — they complement each other:"
        )
        cols = st.columns(3)
        for i, idx_key in enumerate(["ndmi", "nbr", "evi2"]):
            info = INDEX_INFO[idx_key]
            with cols[i]:
                st.markdown(
                    f'<div class="index-card">'
                    f'<h4 style="color:{info["color"]}">{info["name"]}</h4>'
                    f'<p><b>{info["full_name"]}</b></p>'
                    f'<p><code>{info["formula"]}</code></p>'
                    f'<p>{info["description"]}</p>'
                    f'<p><b>Role:</b> {info["use"]}</p>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # Index selector — lives in this tab since it only affects time series
    selected_indices = st.multiselect(
        "Select indices to display",
        options=["NDMI", "NBR", "EVI2"],
        default=["NDMI", "NBR", "EVI2"],
        help="These are the three indices computed by the detection pipeline.",
    )
    selected_indices = [idx.lower() for idx in selected_indices]

    if not selected_indices:
        st.info("Select at least one index above.")
    else:
        # Load time series for each selected index
        ts_data = {}
        for idx_name in selected_indices:
            df = get_timeseries(idx_name, filters["start_date"], filters["end_date"])
            if df is not None and not df.empty:
                ts_data[idx_name] = df

        if ts_data:
            # Multi-index comparison chart
            fig = multi_index_chart(ts_data)
            st.plotly_chart(fig, use_container_width=True)

            # Individual index charts with confidence bands
            st.markdown("---")
            st.subheader("Individual Index Details")

            for idx_name, df in ts_data.items():
                fig = timeseries_chart(df, idx_name)
                st.plotly_chart(fig, use_container_width=True)

                # Trend analysis
                if len(df) >= 10:
                    from src.timeseries.trends import analyze_trend

                    trend = analyze_trend(df)
                    render_trend_indicator(trend)
        else:
            st.info(
                "No time series data available. Run the detection pipeline to "
                "build up observation history."
            )

# ─── Tab 3: Alert History ────────────────────────────────────────────────────
with tab_alerts:
    st.subheader("Alert Statistics Over Time")

    if alert_ts is not None and not alert_ts.empty:
        col1, col2 = st.columns(2)

        with col1:
            fig = alert_summary_chart(alert_ts)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig = cumulative_area_chart(alert_ts)
            st.plotly_chart(fig, use_container_width=True)

        # Full alert records table — formatted consistently with Map tab
        st.markdown("---")
        st.subheader("All Alert Records")
        st.caption(
            f"Showing all {len(alerts_gdf)} alerts across all dates "
            f"(sidebar date filter applies to charts above, not this table)"
        )
        if alerts_gdf is not None and not alerts_gdf.empty:
            full_display = alerts_gdf.copy()
            # Convert datetime columns
            for col in full_display.columns:
                if full_display[col].dtype.kind == "M":
                    full_display[col] = full_display[col].dt.strftime("%Y-%m-%d")
            # Drop redundant/internal columns
            drop_cols = ["geometry", "confidence", "created_at"]
            full_display = full_display.drop(
                columns=[c for c in drop_cols if c in full_display.columns]
            )
            full_display = full_display.rename(columns={
                "detection_date": "Date",
                "confidence_label": "Confidence",
                "area_ha": "Area (ha)",
            })
            st.dataframe(
                full_display.sort_values("Area (ha)", ascending=False).reset_index(drop=True),
                use_container_width=True,
                height=400,
            )
    else:
        st.info("No alert history data available yet.")

# ─── Tab 4: About ────────────────────────────────────────────────────────────
with tab_about:
    render_info_expander()

    st.markdown("---")
    st.subheader("System Architecture")
    st.markdown("""
**Data Pipeline:**
1. Weekly GitHub Actions cron job queries Sentinel-2 imagery
2. Cloud masking via SCL band removes clouds, shadows, cirrus
3. NDMI, NBR, EVI2 indices computed from reflectance bands
4. Z-score comparison against monthly baselines (3-5yr history)
5. Anomalous pixels vectorized into alert polygons
6. Results committed to GitHub and COGs uploaded to Cloudflare R2

**Detection Method:**
- Primary: NDMI z-score < -2.0 AND delta < -0.15
- Confirmation: Multi-index agreement (NDMI + NBR)
- Drought adjustment: SPI-based threshold widening
- Confidence levels: High (z < -3.0), Medium (z < -2.5), Low (z < -2.0)

**Technical Stack:**
- Satellite data: Element84 STAC, Planetary Computer, NASA HLS
- Processing: rasterio, xarray, dask, scipy
- Visualization: Streamlit, Leafmap, Folium, Plotly
- Hosting: Hugging Face Spaces (free tier)
- Storage: Cloudflare R2 (10 GB free, zero egress)
- Automation: GitHub Actions (weekly cron)
    """)

    # Show last data update
    alert_files = sorted(ALERTS_DIR.glob("alerts_*.geojson"))
    if alert_files:
        last_file = alert_files[-1].stem.replace("alerts_", "")
        st.info(f"Last detection run: **{last_file}** | {len(alert_files)} detection files")

    st.markdown("---")
    st.caption(
        "Araripe Deforestation Monitor | "
        "[GitHub](https://github.com/santibravocmcc/Araripe) | "
        "Open source | "
        "Data: ESA Sentinel-2, USGS Landsat, NASA HLS"
    )
