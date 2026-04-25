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
from src.visualization.i18n import t
from src.visualization.maps import (
    add_alert_layer,
    create_base_map,
    create_export_map,
)

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Chapada do Araripe Deforestation Monitor",
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


# ─── Vegetation index descriptions (bilingual) ──────────────────────────────
def _get_index_info() -> dict:
    """Return index descriptions in the current language."""
    return {
        "ndmi": {
            "name": "NDMI",
            "full_name": "Normalized Difference Moisture Index",
            "formula": "(NIR - SWIR1) / (NIR + SWIR1)",
            "description": t("ndmi_desc"),
            "color": "#2196F3",
            "use": t("ndmi_use"),
        },
        "nbr": {
            "name": "NBR",
            "full_name": "Normalized Burn Ratio",
            "formula": "(NIR - SWIR2) / (NIR + SWIR2)",
            "description": t("nbr_desc"),
            "color": "#9C27B0",
            "use": t("nbr_use"),
        },
        "evi2": {
            "name": "EVI2",
            "full_name": "Enhanced Vegetation Index 2",
            "formula": "2.5 * (NIR - RED) / (NIR + 2.4 * RED + 1)",
            "description": t("evi2_desc"),
            "color": "#FF9800",
            "use": t("evi2_use"),
        },
    }


# ─── Main content ─────────────────────────────────────────────────────────────
st.title(t("main_title"))
st.caption(t("main_caption"))

# Disclaimer
st.info(t("disclaimer"))

# Confidence explanation
with st.expander(t("confidence_explanation_title"), expanded=False):
    st.markdown(t("confidence_explanation"))

# Load data
alerts_gdf = get_alerts()
alert_ts = get_alert_timeseries(filters["start_date"], filters["end_date"])

# ─── Filter alerts by sidebar controls (confidence, recent-only) ─────────────
recent_dates: set[str] = filters.get("recent_dates", set())
if alerts_gdf is not None and not alerts_gdf.empty:
    # Confidence filter (multiselect → list of ints)
    conf_mask = alerts_gdf["confidence"].isin(filters["confidence_values"])

    # Recent-only filter
    if filters.get("recent_only") and "detection_date" in alerts_gdf.columns:
        date_str = pd.to_datetime(
            alerts_gdf["detection_date"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
        recent_mask = date_str.isin(recent_dates)
    else:
        recent_mask = pd.Series(True, index=alerts_gdf.index)

    filtered_alerts = alerts_gdf[conf_mask & recent_mask]
    summary = summarize_alerts(filtered_alerts)
else:
    filtered_alerts = None
    summary = {
        "total_alerts": 0,
        "total_area_ha": 0,
        "by_confidence": {"high": 0, "medium": 0, "low": 0},
    }

# ─── Handle "View on Map" button ─────────────────────────────────────────────
if filters["view_on_map"] and filtered_alerts is not None and not filtered_alerts.empty:
    st.session_state["map_alert_idx"] = filtered_alerts.index.tolist()
elif "map_alert_idx" not in st.session_state:
    if filtered_alerts is not None and not filtered_alerts.empty:
        st.session_state["map_alert_idx"] = filtered_alerts.index.tolist()

# Metrics row
render_metrics(summary)

if alerts_gdf is None or alerts_gdf.empty:
    st.info(t("no_data"))

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_map, tab_timeseries, tab_alerts, tab_guide, tab_docs, tab_about = st.tabs(
    [t("tab_map"), t("tab_timeseries"), t("tab_alerts"), t("tab_guide"), t("tab_docs"), t("tab_about")]
)

# ─── Tab 1: Interactive Map + Alert Explorer ─────────────────────────────────
with tab_map:
    # ─── Step-by-step workflow reminder ─────────────────────────────────
    st.info(t("workflow_steps"))

    # ─── Build table with IDs ───────────────────────────────────────────
    _table_df = None
    _display_df = None
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
        # Tag rows that come from the most recent N detection runs.
        if "detection_date" in _display_df.columns and recent_dates:
            _display_df["is_recent"] = _display_df["detection_date"].isin(
                recent_dates
            )
        else:
            _display_df["is_recent"] = False
        # Recent first, then largest by area
        _display_df = _display_df.sort_values(
            ["is_recent", "area_ha"], ascending=[False, False]
        ).reset_index(drop=True)
        _display_df["alert_id"] = range(1, len(_display_df) + 1)
        _display_df["recent_badge"] = _display_df["is_recent"].map(
            {True: "🆕", False: ""}
        )

        show_cols = [
            "alert_id", "recent_badge", "detection_date", "confidence_label",
            "area_ha", "latitude", "longitude",
        ]
        show_cols = [c for c in show_cols if c in _display_df.columns]
        _table_df = _display_df[show_cols].rename(columns={
            "alert_id": t("col_id"),
            "recent_badge": t("col_recent"),
            "detection_date": t("col_date"),
            "confidence_label": t("col_confidence"),
            "area_ha": t("col_area"),
            "latitude": t("col_lat"),
            "longitude": t("col_lon"),
        })

    # ─── Export Mode toggle ─────────────────────────────────────────────
    if "export_mode" not in st.session_state:
        st.session_state["export_mode"] = False

    # Header row: title + Export Mode button
    _header_col1, _header_col2 = st.columns([3, 1])
    with _header_col1:
        st.subheader(t("map_title"))
    with _header_col2:
        if st.session_state["export_mode"]:
            if st.button(
                t("exit_export_mode"),
                type="secondary",
                use_container_width=True,
                key="btn_exit_export",
            ):
                st.session_state["export_mode"] = False
                st.rerun()
        else:
            if st.button(
                t("export_mode"),
                type="primary",
                use_container_width=True,
                key="btn_export_mode",
            ):
                st.session_state["export_mode"] = True
                st.rerun()

    # ─── EXPORT MODE ────────────────────────────────────────────────────
    if st.session_state["export_mode"]:
        st.info(t("export_mode_instructions"))

        # Get the currently-mapped alerts
        map_idx = st.session_state.get("map_alert_idx")
        if map_idx is not None and alerts_gdf is not None:
            export_gdf = alerts_gdf.loc[alerts_gdf.index.isin(map_idx)].copy()
            if export_gdf.crs and str(export_gdf.crs) != "EPSG:4326":
                export_gdf = export_gdf.to_crs("EPSG:4326")
        else:
            export_gdf = filtered_alerts

        legend_labels = {
            3: t("legend_high"),
            2: t("legend_medium"),
            1: t("legend_low"),
        }

        export_map = create_export_map(
            export_gdf,
            legend_labels=legend_labels,
            legend_title=t("legend_title"),
            recent_dates=recent_dates,
            recent_label=t("legend_recent").format(n=filters.get("recent_n", 4)),
        )

        from streamlit_folium import st_folium

        map_data = st_folium(
            export_map,
            height=620,
            width=None,
            returned_objects=["all_drawings"],
            key="export_folium_map",
        )

        # ─── Process drawn selection ───────────────────────────────────
        from shapely.geometry import shape as shapely_shape

        drawn_features = (map_data or {}).get("all_drawings") or []

        if drawn_features and export_gdf is not None and not export_gdf.empty:
            # Combine all drawn shapes into one selection area
            import geopandas as gpd
            from shapely.ops import unary_union

            drawn_geoms = []
            for feat in drawn_features:
                try:
                    geom = shapely_shape(feat["geometry"])
                    drawn_geoms.append(geom)
                except Exception:
                    continue

            if drawn_geoms:
                selection_area = unary_union(drawn_geoms)

                # Find alerts that intersect the selection
                selected_mask = export_gdf.geometry.intersects(selection_area)
                selected_alerts = export_gdf[selected_mask].copy()

                if not selected_alerts.empty:
                    st.markdown("---")
                    st.subheader(t("export_selected"))

                    n_sel = len(selected_alerts)
                    s_suffix = "s" if n_sel != 1 else ""
                    st.success(
                        t("export_n_selected").format(n=n_sel, s=s_suffix)
                    )

                    # Prepare export dataframe
                    sel_export = selected_alerts.copy()
                    centroids = sel_export.geometry.centroid
                    sel_export["latitude"] = centroids.y.round(5)
                    sel_export["longitude"] = centroids.x.round(5)
                    if "detection_date" in sel_export.columns:
                        sel_export["detection_date"] = pd.to_datetime(
                            sel_export["detection_date"], errors="coerce"
                        ).dt.strftime("%Y-%m-%d")

                    # Google Maps links
                    sel_export["google_maps_url"] = sel_export.apply(
                        lambda r: f"https://www.google.com/maps?q={r['latitude']},{r['longitude']}", axis=1
                    )

                    # Display table
                    export_show_cols = [
                        "detection_date", "confidence_label", "area_ha",
                        "latitude", "longitude", "google_maps_url",
                    ]
                    export_show_cols = [c for c in export_show_cols if c in sel_export.columns]
                    export_display = sel_export[export_show_cols].reset_index(drop=True)
                    export_display.index = range(1, len(export_display) + 1)
                    export_display = export_display.rename(columns={
                        "detection_date": t("col_date"),
                        "confidence_label": t("col_confidence"),
                        "area_ha": t("col_area"),
                        "latitude": t("col_lat"),
                        "longitude": t("col_lon"),
                        "google_maps_url": t("col_google_maps"),
                    })

                    st.dataframe(
                        export_display,
                        use_container_width=True,
                        height=min(400, 40 + 35 * len(export_display)),
                        column_config={
                            t("col_google_maps"): st.column_config.LinkColumn(
                                t("col_google_maps"),
                                display_text=t("export_google_maps"),
                            ),
                            t("col_area"): st.column_config.NumberColumn(
                                t("col_area"), format="%.2f",
                            ),
                            t("col_lat"): st.column_config.NumberColumn(
                                t("col_lat"), format="%.5f",
                            ),
                            t("col_lon"): st.column_config.NumberColumn(
                                t("col_lon"), format="%.5f",
                            ),
                        },
                    )

                    # ─── Download buttons ──────────────────────────────
                    dl_col1, dl_col2 = st.columns(2)

                    # CSV
                    csv_cols = [
                        "detection_date", "confidence_label", "area_ha",
                        "latitude", "longitude", "google_maps_url",
                    ]
                    csv_cols = [c for c in csv_cols if c in sel_export.columns]
                    csv_data = sel_export[csv_cols].to_csv(index=False)

                    with dl_col1:
                        st.download_button(
                            label=t("export_csv"),
                            data=csv_data,
                            file_name="araripe_alerts_export.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )

                    # GeoJSON
                    geojson_export = selected_alerts.copy()
                    for col in geojson_export.columns:
                        if col == "geometry":
                            continue
                        if geojson_export[col].dtype.kind == "M":
                            geojson_export[col] = geojson_export[col].dt.strftime("%Y-%m-%d")
                        elif geojson_export[col].dtype.kind == "m":
                            geojson_export[col] = geojson_export[col].astype(str)
                    geojson_data = geojson_export.to_json()

                    with dl_col2:
                        st.download_button(
                            label=t("export_geojson"),
                            data=geojson_data,
                            file_name="araripe_alerts_export.geojson",
                            mime="application/geo+json",
                            use_container_width=True,
                        )
                else:
                    st.warning(t("export_no_selection"))
            else:
                st.info(t("export_no_selection"))
        else:
            st.info(t("export_no_selection"))

    # ─── NORMAL MAP MODE ────────────────────────────────────────────────
    else:
        # Determine whether the map needs rebuilding
        _need_map_rebuild = filters["view_on_map"] or "map_html" not in st.session_state

        map_idx = st.session_state.get("map_alert_idx")

        if _need_map_rebuild:
            # Build the map from scratch
            if map_idx is not None and alerts_gdf is not None:
                map_alerts_gdf = alerts_gdf.loc[alerts_gdf.index.isin(map_idx)]
                if map_alerts_gdf.crs and str(map_alerts_gdf.crs) != "EPSG:4326":
                    map_alerts_gdf = map_alerts_gdf.to_crs("EPSG:4326")
            else:
                map_alerts_gdf = None

            _map_bounds = None
            if map_alerts_gdf is not None and not map_alerts_gdf.empty:
                bounds = map_alerts_gdf.total_bounds
                _map_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]

            m = create_base_map()

            legend_labels = {
                3: t("legend_high"),
                2: t("legend_medium"),
                1: t("legend_low"),
            }

            if map_alerts_gdf is not None and not map_alerts_gdf.empty:
                add_alert_layer(
                    m, map_alerts_gdf,
                    legend_labels=legend_labels,
                    legend_title=t("legend_title"),
                    recent_dates=recent_dates,
                    recent_label=t("legend_recent").format(
                        n=filters.get("recent_n", 4)
                    ),
                )

            if _map_bounds is not None:
                m.fit_bounds(_map_bounds, padding=[30, 30])

            # Cache the rendered HTML
            st.session_state["map_html"] = m._repr_html_()
            st.session_state["map_n_alerts"] = (
                len(map_alerts_gdf) if map_alerts_gdf is not None else 0
            )

        # Display cached map HTML (no re-serialization on filter changes)
        n_map = st.session_state.get("map_n_alerts", 0)
        if n_map > 0:
            s_suffix = "s" if n_map != 1 else ""
            st.caption(t("map_showing_n").format(n=n_map, s=s_suffix))

        import streamlit.components.v1 as components

        components.html(st.session_state["map_html"], height=620, scrolling=False)

    # ─── Alert Explorer (shown in both modes) ──────────────────────────
    if _table_df is not None and not _table_df.empty:
        st.markdown("---")
        st.subheader(t("alert_explorer"))
        st.caption(
            t("alert_explorer_caption").format(n=len(_table_df))
        )

        st.dataframe(
            _table_df,
            use_container_width=True,
            height=400,
            column_config={
                t("col_id"): st.column_config.NumberColumn(
                    t("col_id"), width="small"
                ),
                t("col_recent"): st.column_config.TextColumn(
                    t("col_recent"), width="small"
                ),
                t("col_date"): st.column_config.TextColumn(
                    t("col_date"), width="small"
                ),
                t("col_confidence"): st.column_config.TextColumn(
                    t("col_confidence"), width="small"
                ),
                t("col_area"): st.column_config.NumberColumn(
                    t("col_area"), format="%.2f", width="small"
                ),
                t("col_lat"): st.column_config.NumberColumn(
                    t("col_lat"), format="%.5f", width="small"
                ),
                t("col_lon"): st.column_config.NumberColumn(
                    t("col_lon"), format="%.5f", width="small"
                ),
            },
        )

        st.caption(
            t("total_area_caption").format(
                area=f"{_table_df[t('col_area')].sum():,.1f}"
            )
        )

# ─── Tab 2: Time Series ──────────────────────────────────────────────────────
with tab_timeseries:
    INDEX_INFO = _get_index_info()
    st.subheader(t("ts_title"))

    # ─── Index explanation ───────────────────────────────────────────────
    with st.expander(t("ts_expander"), expanded=False):
        st.markdown(t("ts_expander_intro"))
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
                    f'<p><b>{t("role_label")}:</b> {info["use"]}</p>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # Index selector
    selected_indices = st.multiselect(
        t("ts_select_indices"),
        options=["NDMI", "NBR", "EVI2"],
        default=["NDMI", "NBR", "EVI2"],
        help=t("ts_select_help"),
    )
    selected_indices = [idx.lower() for idx in selected_indices]

    if not selected_indices:
        st.info(t("ts_select_empty"))
    else:
        ts_data = {}
        for idx_name in selected_indices:
            df = get_timeseries(idx_name, filters["start_date"], filters["end_date"])
            if df is not None and not df.empty:
                ts_data[idx_name] = df

        if ts_data:
            fig = multi_index_chart(
                ts_data,
                title=t("chart_multi_title"),
                xaxis_title=t("chart_date_axis"),
                yaxis_title=t("chart_index_value"),
            )
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.subheader(t("ts_individual"))

            for idx_name, df in ts_data.items():
                fig = timeseries_chart(
                    df, idx_name,
                    title=t("chart_ts_title").format(index=idx_name.upper()),
                    xaxis_title=t("chart_date_axis"),
                )
                st.plotly_chart(fig, use_container_width=True)

                if len(df) >= 10:
                    from src.timeseries.trends import analyze_trend

                    trend = analyze_trend(df)
                    render_trend_indicator(trend)
        else:
            st.info(t("ts_no_data"))

# ─── Tab 3: Alert History ────────────────────────────────────────────────────
with tab_alerts:
    st.subheader(t("ah_title"))

    if alert_ts is not None and not alert_ts.empty:
        # Translated legend labels for confidence levels in charts
        _chart_conf_labels = {
            "high": t("high"),
            "medium": t("medium"),
            "low": t("low"),
        }

        col1, col2 = st.columns(2)

        with col1:
            fig = alert_summary_chart(
                alert_ts,
                title=t("chart_alerts_title"),
                xaxis_title=t("chart_date_axis"),
                yaxis_title=t("chart_num_alerts"),
                legend_labels=_chart_conf_labels,
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig = cumulative_area_chart(
                alert_ts,
                title=t("chart_cumulative_title"),
                xaxis_title=t("chart_date_axis"),
                yaxis_title=t("chart_area_axis"),
                legend_name=t("chart_cumulative_legend"),
            )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.subheader(t("ah_all_records"))
        st.caption(
            t("ah_caption").format(n=len(alerts_gdf))
        )
        if alerts_gdf is not None and not alerts_gdf.empty:
            full_display = alerts_gdf.copy()
            for col in full_display.columns:
                if full_display[col].dtype.kind == "M":
                    full_display[col] = full_display[col].dt.strftime("%Y-%m-%d")
            drop_cols = ["geometry", "confidence", "created_at"]
            full_display = full_display.drop(
                columns=[c for c in drop_cols if c in full_display.columns]
            )
            full_display = full_display.rename(columns={
                "detection_date": t("col_date"),
                "confidence_label": t("col_confidence"),
                "area_ha": t("col_area"),
            })
            st.dataframe(
                full_display.sort_values(
                    t("col_area"), ascending=False
                ).reset_index(drop=True),
                use_container_width=True,
                height=400,
            )
    else:
        st.info(t("ah_no_data"))

# ─── Tab 4: Guide ────────────────────────────────────────────────────────────
with tab_guide:
    st.subheader(t("guide_title"))
    st.markdown(t("guide_body"))

# ─── Tab 5: Documentation ────────────────────────────────────────────────────
with tab_docs:
    st.subheader(t("docs_title"))
    st.caption(t("docs_caption"))

    # Load the correct language markdown file
    _lang = st.session_state.get("language", "pt")
    _doc_file = (
        Path(__file__).parent / "REVISAO_TECNICA.md"
        if _lang == "pt"
        else Path(__file__).parent / "TECHNICAL_REVIEW.md"
    )

    # PDF download button (top of tab, before content) — language-aware
    _pdf_file = (
        Path(__file__).parent / "REVISAO_TECNICA.pdf"
        if _lang == "pt"
        else Path(__file__).parent / "TECHNICAL_REVIEW.pdf"
    )
    if _pdf_file.exists():
        st.download_button(
            label=t("docs_download"),
            data=_pdf_file.read_bytes(),
            file_name=_pdf_file.name,
            mime="application/pdf",
            help=t("docs_download_caption"),
        )

    st.markdown("---")

    # Render the markdown document
    if _doc_file.exists():
        _doc_text = _doc_file.read_text(encoding="utf-8")
        st.markdown(_doc_text, unsafe_allow_html=False)
    else:
        st.warning(f"Documentation file not found: {_doc_file.name}")

# ─── Tab 6: About ────────────────────────────────────────────────────────────
with tab_about:
    render_info_expander()

    st.markdown("---")
    st.subheader(t("architecture_title"))
    st.markdown(t("architecture_body"))

    alert_files = sorted(ALERTS_DIR.glob("alerts_*.geojson"))
    if alert_files:
        last_file = alert_files[-1].stem.replace("alerts_", "")
        st.info(
            t("last_detection").format(date=last_file, n=len(alert_files))
        )

    st.markdown("---")
    st.caption(t("footer"))
