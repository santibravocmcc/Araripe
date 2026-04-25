"""Streamlit dashboard layout components."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from config.settings import ALERTS_DIR, AOI_GEOJSON
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

    # ── Latest scan info + quick-filter button ─────────────────────────
    # Derive latest detection date from alert filenames
    alert_files = sorted(ALERTS_DIR.glob("alerts_*.geojson"))
    latest_image_date: str | None = None
    latest_run_date: str | None = None
    if alert_files:
        latest_image_date = alert_files[-1].stem.replace("alerts_", "")
        # Try to get created_at from the most recent file
        try:
            import json as _json

            with open(alert_files[-1]) as _f:
                _feats = _json.load(_f).get("features", [])
            if _feats:
                _ca = _feats[0].get("properties", {}).get("created_at", "")
                latest_run_date = _ca[:10] if _ca else None
        except Exception:
            pass

    if latest_image_date:
        st.sidebar.caption(
            t("latest_scan_info").format(
                run_date=latest_run_date or "—",
                image_date=latest_image_date,
            )
        )

    latest_scan_clicked = False
    if latest_image_date:
        latest_scan_clicked = st.sidebar.button(
            t("latest_scan_btn"),
            use_container_width=True,
            help=t("latest_scan_help"),
            key="btn_latest_scan",
        )

    st.sidebar.markdown("---")

    # ── Alert confidence (multiselect, default High only) ──────────────
    st.sidebar.subheader(t("alert_confidence"))

    conf_options = [t("high"), t("medium"), t("low")]
    conf_defaults = [t("high")]
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

    # ── Recent activity ────────────────────────────────────────────────
    # Detection runs every Monday & Thursday → 4 runs ≈ 2 weeks
    st.sidebar.subheader(t("recent_section"))
    recent_n = int(st.sidebar.number_input(
        t("recent_n_label"),
        min_value=1,
        max_value=20,
        value=4,
        step=1,
        help=t("recent_n_help"),
    ))
    recent_only = st.sidebar.checkbox(
        t("recent_only_label"),
        value=False,
        help=t("recent_only_help"),
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

    # Compute the set of detection-date strings that count as "recent".
    recent_dates: set[str] = set()
    if alert_files:
        recent_files = alert_files[-recent_n:]
        recent_dates = {p.stem.replace("alerts_", "") for p in recent_files}

    # If "Latest Scan Only" was clicked, keep only the very last run.
    if latest_scan_clicked and latest_image_date:
        recent_dates = {latest_image_date}
        recent_only = True

    return {
        # Wide internal range — date filter UI removed; full history shown.
        "start_date": "2020-01-01",
        "end_date": "2099-12-31",
        "confidence_values": selected_confidence_values,
        "recent_n": recent_n,
        "recent_only": recent_only,
        "recent_dates": recent_dates,
        "view_on_map": view_on_map or latest_scan_clicked,
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
