"""Streamlit dashboard layout components."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from config.settings import AOI_GEOJSON
from src.visualization.i18n import t


def _render_language_selector() -> None:
    """Render flag-based language selector at the bottom of the sidebar."""
    if "language" not in st.session_state:
        st.session_state["language"] = "pt"

    st.sidebar.markdown("---")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button(
            "Português",
            use_container_width=True,
            type="primary" if st.session_state["language"] == "pt" else "secondary",
            key="lang_pt",
        ):
            st.session_state["language"] = "pt"
            st.rerun()
    with col2:
        if st.button(
            "English",
            use_container_width=True,
            type="primary" if st.session_state["language"] == "en" else "secondary",
            key="lang_en",
        ):
            st.session_state["language"] = "en"
            st.rerun()


def render_sidebar() -> dict:
    """Render the sidebar with filter controls.

    All filters immediately affect the table, metrics, and charts.
    The map only updates when the user presses **View on Map**.

    Returns
    -------
    dict
        Filter values including ``view_on_map`` (bool) flag.
    """
    # Ensure language is initialised before any t() call
    if "language" not in st.session_state:
        st.session_state["language"] = "pt"

    st.sidebar.title(t("sidebar_title"))
    st.sidebar.markdown(t("sidebar_caption"))

    st.sidebar.markdown("---")

    # ── Date range (default: last 90 days) ─────────────────────────────
    st.sidebar.subheader(t("date_range"))
    default_start = pd.Timestamp.now() - pd.Timedelta(days=90)
    col1, col2 = st.sidebar.columns(2)
    with col1:
        start_date = st.date_input(t("start"), value=default_start)
    with col2:
        end_date = st.date_input(t("end"), value=pd.Timestamp.now())

    st.sidebar.markdown("---")

    # ── Alert confidence (multiselect, default Medium + High) ──────────
    st.sidebar.subheader(t("alert_confidence"))

    conf_options = [t("high"), t("medium"), t("low")]
    conf_defaults = [t("high"), t("medium")]
    confidence_selection = st.sidebar.multiselect(
        t("select_confidence"),
        options=conf_options,
        default=conf_defaults,
        help=t("confidence_help"),
    )
    label_to_val = {t("low"): 1, t("medium"): 2, t("high"): 3}
    selected_confidence_values = [
        label_to_val[c] for c in confidence_selection if c in label_to_val
    ]

    st.sidebar.markdown("---")

    # ── Minimum area ───────────────────────────────────────────────────
    st.sidebar.subheader(t("min_area_label"))
    min_area = st.sidebar.number_input(
        t("min_area_input"),
        min_value=0.0,
        value=0.0,
        step=1.0,
        help=t("min_area_help"),
    )

    st.sidebar.markdown("---")

    # ── View on Map button ─────────────────────────────────────────────
    view_on_map = st.sidebar.button(
        t("view_on_map"),
        type="primary",
        use_container_width=True,
        help=t("view_on_map_help"),
    )

    st.sidebar.caption(t("sidebar_filter_note"))

    # ── Language selector at the bottom ────────────────────────────────
    _render_language_selector()

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
            label=t("total_alerts"),
            value=summary.get("total_alerts", 0),
        )

    with col2:
        st.metric(
            label=t("total_area_ha"),
            value=f"{summary.get('total_area_ha', 0):,.1f}",
        )

    by_conf = summary.get("by_confidence", {})

    with col3:
        st.metric(
            label=t("high_confidence"),
            value=by_conf.get("high", 0),
        )

    with col4:
        st.metric(
            label=t("medium_confidence"),
            value=by_conf.get("medium", 0),
        )

    with col5:
        st.metric(
            label=t("low_confidence"),
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
        icon = t("ts_decreasing")
    elif trend == "increasing":
        delta_color = "normal"
        icon = t("ts_increasing")
    else:
        delta_color = "off"
        icon = t("ts_no_trend")

    sig_text = t("ts_significant") if significant else t("ts_not_significant")

    st.metric(
        label=t("ts_trend"),
        value=icon,
        delta=f"{slope:+.4f}/year{sig_text}",
        delta_color=delta_color,
    )


def render_info_expander() -> None:
    """Render an expandable section with methodology information."""
    with st.expander(t("about_expander"), expanded=True):
        st.markdown(t("about_body"))
