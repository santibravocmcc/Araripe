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
    seasonal_decomposition_chart,
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
    add_aoi_boundary,
    add_legend,
    create_base_map,
)

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Araripe Deforestation Monitor",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="expanded",
)

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


# ─── Main content ─────────────────────────────────────────────────────────────
st.title("Araripe Deforestation Monitor")
st.caption("Satellite-based deforestation monitoring for Chapada do Araripe")

# Load data
alerts_gdf = get_alerts()
alert_ts = get_alert_timeseries(filters["start_date"], filters["end_date"])

# Metrics row
if alerts_gdf is not None and not alerts_gdf.empty:
    # Filter by confidence
    filtered_alerts = alerts_gdf[
        alerts_gdf["confidence"] >= filters["min_confidence"]
    ]
    summary = summarize_alerts(filtered_alerts)
    render_metrics(summary)
else:
    st.info(
        "No alert data available yet. Run the detection pipeline first: "
        "`python scripts/run_detection.py`"
    )
    summary = {"total_alerts": 0, "total_area_ha": 0, "by_confidence": {"high": 0, "medium": 0, "low": 0}}
    render_metrics(summary)

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_map, tab_timeseries, tab_alerts, tab_about = st.tabs(
    ["Map", "Time Series", "Alert History", "About"]
)

# ─── Tab 1: Interactive Map ───────────────────────────────────────────────────
with tab_map:
    st.subheader("Deforestation Alert Map")

    m = create_base_map()

    # Add AOI boundary
    if AOI_GEOJSON.exists():
        add_aoi_boundary(m, str(AOI_GEOJSON))

    # Add alerts
    if alerts_gdf is not None and not alerts_gdf.empty:
        filtered = alerts_gdf[alerts_gdf["confidence"] >= filters["min_confidence"]]
        if not filtered.empty:
            add_alert_layer(m, filtered)

    add_legend(m)

    # Render map
    try:
        from streamlit_folium import st_folium

        st_folium(m, width=None, height=600, returned_objects=[])
    except ImportError:
        st.warning(
            "Install `streamlit-folium` for interactive maps: "
            "`pip install streamlit-folium`"
        )

# ─── Tab 2: Time Series ──────────────────────────────────────────────────────
with tab_timeseries:
    st.subheader("Vegetation Index Time Series")

    selected_indices = filters["selected_indices"]

    if not selected_indices:
        st.info("Select at least one index from the sidebar.")
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

        # Alert data table
        st.markdown("---")
        st.subheader("Alert Records")
        if alerts_gdf is not None and not alerts_gdf.empty:
            display_df = alerts_gdf.drop(columns=["geometry"], errors="ignore")
            st.dataframe(display_df, use_container_width=True)
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
    - Fire vs. mechanical: dNBR + BSI classification
    - Drought adjustment: SPI-based threshold widening

    **Technical Stack:**
    - Satellite data: Element84 STAC, Planetary Computer, NASA HLS
    - Processing: rasterio, xarray, dask, scipy
    - Visualization: Streamlit, Leafmap, Folium, Plotly
    - Hosting: Hugging Face Spaces (free tier)
    - Storage: Cloudflare R2 (10 GB free, zero egress)
    """)

    st.markdown("---")
    st.caption(
        "Araripe Deforestation Monitor | "
        "Open source | "
        "Data: ESA Sentinel-2, USGS Landsat, NASA HLS"
    )
