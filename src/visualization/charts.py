"""Interactive charts for vegetation time series and alert statistics."""

from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ─── Color palette ────────────────────────────────────────────────────────────
INDEX_COLORS = {
    "ndvi": "#4CAF50",
    "ndmi": "#2196F3",
    "nbr": "#9C27B0",
    "evi2": "#FF9800",
    "savi": "#795548",
    "bsi": "#F44336",
}

CONFIDENCE_COLORS = {
    "high": "#F44336",
    "medium": "#FF9800",
    "low": "#FFC107",
}


def timeseries_chart(
    df: pd.DataFrame,
    index_name: str,
    value_col: str = "mean",
    std_col: str = "std",
    date_col: str = "date",
    title: Optional[str] = None,
    show_confidence_bands: bool = True,
) -> go.Figure:
    """Create an interactive time series chart with confidence bands.

    Parameters
    ----------
    df : pd.DataFrame
        Time series data.
    index_name : str
        Vegetation index name (for styling).
    value_col : str
        Column with the central value.
    std_col : str
        Column with standard deviation (for bands).
    date_col : str
        Date column.
    title : str, optional
        Chart title.
    show_confidence_bands : bool
        Whether to show ±1σ and ±2σ bands.

    Returns
    -------
    go.Figure
        Plotly figure.
    """
    if title is None:
        title = f"{index_name.upper()} Time Series"

    color = INDEX_COLORS.get(index_name, "#2196F3")
    fig = go.Figure()

    if show_confidence_bands and std_col in df.columns:
        # ±2σ band
        fig.add_trace(
            go.Scatter(
                x=pd.concat([df[date_col], df[date_col][::-1]]),
                y=pd.concat([
                    df[value_col] + 2 * df[std_col],
                    (df[value_col] - 2 * df[std_col])[::-1],
                ]),
                fill="toself",
                fillcolor=f"rgba({_hex_to_rgb(color)}, 0.1)",
                line=dict(color="rgba(0,0,0,0)"),
                name="±2σ",
                showlegend=True,
            )
        )

        # ±1σ band
        fig.add_trace(
            go.Scatter(
                x=pd.concat([df[date_col], df[date_col][::-1]]),
                y=pd.concat([
                    df[value_col] + df[std_col],
                    (df[value_col] - df[std_col])[::-1],
                ]),
                fill="toself",
                fillcolor=f"rgba({_hex_to_rgb(color)}, 0.2)",
                line=dict(color="rgba(0,0,0,0)"),
                name="±1σ",
                showlegend=True,
            )
        )

    # Main line
    fig.add_trace(
        go.Scatter(
            x=df[date_col],
            y=df[value_col],
            mode="lines+markers",
            marker=dict(size=4),
            line=dict(color=color, width=2),
            name=index_name.upper(),
        )
    )

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title=index_name.upper(),
        template="plotly_white",
        hovermode="x unified",
        xaxis=dict(rangeslider=dict(visible=True)),
        height=400,
    )

    return fig


def multi_index_chart(
    dfs: dict[str, pd.DataFrame],
    value_col: str = "mean",
    date_col: str = "date",
    title: str = "Vegetation Indices Over Time",
) -> go.Figure:
    """Plot multiple vegetation indices on the same chart.

    Parameters
    ----------
    dfs : dict[str, pd.DataFrame]
        Mapping of index name → DataFrame.
    """
    fig = go.Figure()

    for idx_name, df in dfs.items():
        color = INDEX_COLORS.get(idx_name, "#607D8B")
        fig.add_trace(
            go.Scatter(
                x=df[date_col],
                y=df[value_col],
                mode="lines",
                line=dict(color=color, width=2),
                name=idx_name.upper(),
            )
        )

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Index Value",
        template="plotly_white",
        hovermode="x unified",
        xaxis=dict(rangeslider=dict(visible=True)),
        height=400,
    )

    return fig


def seasonal_decomposition_chart(
    dates: pd.Series,
    trend: pd.Series,
    seasonal: pd.Series,
    residual: pd.Series,
    original: pd.Series,
    title: str = "Seasonal Decomposition (STL)",
) -> go.Figure:
    """Plot STL decomposition results as a 4-panel chart.

    Parameters
    ----------
    dates : pd.Series
        Date values.
    trend, seasonal, residual, original : pd.Series
        Decomposition components.
    """
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        subplot_titles=["Observed", "Trend", "Seasonal", "Residual"],
        vertical_spacing=0.05,
    )

    fig.add_trace(go.Scatter(x=dates, y=original, name="Observed", line=dict(color="#2196F3")), row=1, col=1)
    fig.add_trace(go.Scatter(x=dates, y=trend, name="Trend", line=dict(color="#F44336")), row=2, col=1)
    fig.add_trace(go.Scatter(x=dates, y=seasonal, name="Seasonal", line=dict(color="#4CAF50")), row=3, col=1)
    fig.add_trace(go.Scatter(x=dates, y=residual, name="Residual", line=dict(color="#9E9E9E")), row=4, col=1)

    fig.update_layout(
        title=title,
        template="plotly_white",
        height=700,
        showlegend=False,
    )

    return fig


def alert_summary_chart(
    df: pd.DataFrame,
    title: str = "Deforestation Alerts Over Time",
) -> go.Figure:
    """Create a stacked bar chart of alerts by confidence level.

    Parameters
    ----------
    df : pd.DataFrame
        Alert statistics with columns: date, high_confidence,
        medium_confidence, low_confidence.
    """
    fig = go.Figure()

    for level, color in CONFIDENCE_COLORS.items():
        col = f"{level}_confidence"
        if col in df.columns:
            fig.add_trace(
                go.Bar(
                    x=df["date"],
                    y=df[col],
                    name=level.capitalize(),
                    marker_color=color,
                )
            )

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Number of Alerts",
        barmode="stack",
        template="plotly_white",
        height=350,
    )

    return fig


def cumulative_area_chart(
    df: pd.DataFrame,
    title: str = "Cumulative Deforested Area",
) -> go.Figure:
    """Line chart showing cumulative deforested area over time.

    Parameters
    ----------
    df : pd.DataFrame
        Alert statistics with columns: date, total_area_ha.
    """
    df = df.sort_values("date")
    df["cumulative_ha"] = df["total_area_ha"].cumsum()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["cumulative_ha"],
            fill="tozeroy",
            fillcolor="rgba(244, 67, 54, 0.2)",
            line=dict(color="#F44336", width=2),
            name="Cumulative Area (ha)",
        )
    )

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Area (hectares)",
        template="plotly_white",
        height=350,
    )

    return fig


def _hex_to_rgb(hex_color: str) -> str:
    """Convert hex color to RGB string for rgba()."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"{r}, {g}, {b}"
