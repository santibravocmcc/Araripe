"""Streamlit dashboard layout components."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from config.settings import AOI_GEOJSON


def render_sidebar() -> dict:
    """Render the sidebar with filter controls.

    All filters immediately affect the table, metrics, and charts.
    The map only updates when the user presses **View on Map**.

    Returns
    -------
    dict
        Filter values including ``view_on_map`` (bool) flag.
    """
    st.sidebar.title("Araripe Monitor")
    st.sidebar.markdown("Deforestation monitoring for Chapada do Araripe")

    st.sidebar.markdown("---")

    # ── Date range (default: last 90 days) ─────────────────────────────
    st.sidebar.subheader("Date Range")
    default_start = pd.Timestamp.now() - pd.Timedelta(days=90)
    col1, col2 = st.sidebar.columns(2)
    with col1:
        start_date = st.date_input("Start", value=default_start)
    with col2:
        end_date = st.date_input("End", value=pd.Timestamp.now())

    st.sidebar.markdown("---")

    # ── Alert confidence (multiselect, default Medium + High) ──────────
    st.sidebar.subheader("Alert Confidence")
    confidence_selection = st.sidebar.multiselect(
        "Select confidence levels",
        options=["High", "Medium", "Low"],
        default=["High", "Medium"],
        help="Choose which confidence levels to include.",
    )
    # Map labels to numeric values used in the data
    confidence_map = {"Low": 1, "Medium": 2, "High": 3}
    selected_confidence_values = [
        confidence_map[c] for c in confidence_selection
    ]

    st.sidebar.markdown("---")

    # ── Minimum area ───────────────────────────────────────────────────
    st.sidebar.subheader("Minimum Area")
    min_area = st.sidebar.number_input(
        "Min area (ha)",
        min_value=0.0,
        value=0.0,
        step=1.0,
        help="Exclude alerts smaller than this area.",
    )

    st.sidebar.markdown("---")

    # ── View on Map button ─────────────────────────────────────────────
    view_on_map = st.sidebar.button(
        "View on Map",
        type="primary",
        use_container_width=True,
        help="Apply current filters to the map and zoom to fit.",
    )

    st.sidebar.caption(
        "Filters update the table and metrics instantly. "
        "Press **View on Map** to refresh the map."
    )

    return {
        "start_date": str(start_date),
        "end_date": str(end_date),
        "confidence_values": selected_confidence_values,
        "min_area": min_area,
        "view_on_map": view_on_map,
    }


def render_metrics(summary: dict) -> None:
    """Render key metric cards at the top of the dashboard.

    Parameters
    ----------
    summary : dict
        Alert summary from alerts.summarize_alerts().
    """
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            label="Total Alerts",
            value=summary.get("total_alerts", 0),
        )

    with col2:
        st.metric(
            label="Total Area (ha)",
            value=f"{summary.get('total_area_ha', 0):,.1f}",
        )

    by_conf = summary.get("by_confidence", {})

    with col3:
        st.metric(
            label="High Confidence",
            value=by_conf.get("high", 0),
        )

    with col4:
        st.metric(
            label="Medium Confidence",
            value=by_conf.get("medium", 0),
        )

    with col5:
        st.metric(
            label="Low Confidence",
            value=by_conf.get("low", 0),
        )


def render_trend_indicator(trend_result: dict) -> None:
    """Render a trend direction indicator.

    Parameters
    ----------
    trend_result : dict
        Output of trends.analyze_trend().
    """
    summary = trend_result.get("summary", {})
    trend = summary.get("trend", "no_trend")
    slope = summary.get("slope_per_year", 0)
    significant = summary.get("significant", False)

    if trend == "decreasing":
        delta_color = "inverse"
        icon = "Decreasing"
    elif trend == "increasing":
        delta_color = "normal"
        icon = "Increasing"
    else:
        delta_color = "off"
        icon = "No trend"

    sig_text = " (significant)" if significant else " (not significant)"

    st.metric(
        label="Vegetation Trend",
        value=icon,
        delta=f"{slope:+.4f}/year{sig_text}",
        delta_color=delta_color,
    )


def render_info_expander() -> None:
    """Render an expandable section with methodology information."""
    with st.expander("About this monitoring system", expanded=True):
        st.markdown("""
        **Araripe Deforestation Monitor** detects vegetation loss across
        Chapada do Araripe using satellite imagery from Sentinel-2 and Landsat.

        **Key features:**
        - Weekly automated processing via GitHub Actions
        - Moisture-based indices (NDMI, NBR) for reliable detection in
          seasonally deciduous Caatinga/Cerrado vegetation
        - Z-score anomaly detection against monthly baselines
        - Multi-index confirmation for confidence classification
        - Drought-adjusted thresholds using SPI rainfall data

        **Data sources:**
        - Sentinel-2 L2A (10–20m resolution, 5-day revisit)
        - Landsat 8/9 Collection 2 (30m resolution)
        - NASA HLS (harmonized 30m, 2–3 day revisit)

        **Coverage:** ~7–8°S, 39–40°W (Chapada do Araripe, CE/PE/PI, Brazil)
        """)
