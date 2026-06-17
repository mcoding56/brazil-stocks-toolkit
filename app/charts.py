"""Plotly chart helpers for the dashboard.

Each function takes a tidy DataFrame and returns a ``plotly.graph_objects.Figure``
ready for ``st.plotly_chart``. Kept dependency-light and theme-agnostic so the
Streamlit theme (``.streamlit/config.toml``) drives the colours.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# A green→red diverging scale: green = cheap/attractive, red = expensive/risky.
CHEAP_GREEN = "#2ca58d"
RICH_RED = "#d1495b"
ACCENT = "#3a86ff"


def hbar_ranking(
    df: pd.DataFrame,
    value_col: str,
    label_col: str = "ticker",
    title: str = "",
    color_col: Optional[str] = None,
    value_title: Optional[str] = None,
) -> go.Figure:
    """Horizontal bar chart, highest value at the top."""
    d = df.copy()
    d = d.sort_values(value_col, ascending=True)
    fig = px.bar(
        d,
        x=value_col,
        y=label_col,
        orientation="h",
        color=color_col or value_col,
        color_continuous_scale=[RICH_RED, "#f0c808", CHEAP_GREEN],
        title=title,
    )
    fig.update_layout(
        height=max(360, 22 * len(d)),
        margin=dict(l=10, r=10, t=50, b=10),
        coloraxis_showscale=color_col is not None,
        xaxis_title=value_title or value_col,
        yaxis_title="",
    )
    return fig


def scatter_quadrant(
    df: pd.DataFrame,
    x: str,
    y: str,
    label_col: str = "ticker",
    color_col: Optional[str] = None,
    x_title: str = "",
    y_title: str = "",
    title: str = "",
    x_div: float = 0.0,
    y_div: float = 0.0,
) -> go.Figure:
    """Scatter with quadrant divider lines and ticker labels."""
    fig = px.scatter(
        df,
        x=x,
        y=y,
        text=label_col,
        color=color_col,
        color_continuous_scale=[RICH_RED, "#f0c808", CHEAP_GREEN],
        title=title,
    )
    fig.update_traces(textposition="top center", marker=dict(size=10))
    fig.add_hline(y=y_div, line_dash="dot", line_color="gray", opacity=0.5)
    fig.add_vline(x=x_div, line_dash="dot", line_color="gray", opacity=0.5)
    fig.update_layout(
        height=560,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis_title=x_title or x,
        yaxis_title=y_title or y,
    )
    return fig


def heatmap(matrix: pd.DataFrame, title: str = "") -> go.Figure:
    """Z-score heatmap (rows = tickers, columns = metrics)."""
    fig = go.Figure(
        data=go.Heatmap(
            z=matrix.values,
            x=list(matrix.columns),
            y=list(matrix.index),
            colorscale=[[0, CHEAP_GREEN], [0.5, "#10131a"], [1, RICH_RED]],
            zmid=0,
            zmin=-3,
            zmax=3,
            colorbar=dict(title="Z"),
        )
    )
    fig.update_layout(
        title=title,
        height=max(420, 20 * len(matrix)),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def price_line(df: pd.DataFrame, ticker: str) -> go.Figure:
    """Closing-price line chart."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=pd.to_datetime(df["date"]),
            y=df["close"],
            mode="lines",
            line=dict(color=ACCENT, width=2),
            name="Close",
        )
    )
    fig.update_layout(
        title=f"{ticker} — closing price",
        height=380,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis_title="",
        yaxis_title="Price (BRL)",
    )
    return fig


def pl_history_line(df: pd.DataFrame, ticker: str) -> go.Figure:
    """Historical P/L line with the mean band."""
    d = df.copy()
    d["snapshot_date"] = pd.to_datetime(d["snapshot_date"])
    mean = d["pl"].mean()
    std = d["pl"].std()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=d["snapshot_date"], y=d["pl"], mode="lines+markers",
            line=dict(color=ACCENT, width=2), name="P/L",
        )
    )
    if pd.notna(mean):
        fig.add_hline(y=mean, line_dash="dash", line_color="gray",
                      annotation_text="mean")
        if pd.notna(std):
            fig.add_hline(y=mean + std, line_dash="dot", line_color="#888", opacity=0.5)
            fig.add_hline(y=mean - std, line_dash="dot", line_color="#888", opacity=0.5)
    fig.update_layout(
        title=f"{ticker} — P/L history",
        height=380,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis_title="",
        yaxis_title="P/L",
    )
    return fig
