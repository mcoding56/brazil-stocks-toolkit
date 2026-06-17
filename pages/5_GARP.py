"""GARP (Growth at a Reasonable Price) screen page."""
from __future__ import annotations

import streamlit as st

from app import charts
from app import data as appdata
from app import ui

st.set_page_config(page_title="GARP · Brazil Stocks", page_icon="🌱", layout="wide")

ui.page_header(
    "🌱 GARP — Growth at a Reasonable Price",
    "Names that are statistically cheap *and* growing. The bottom-right "
    "quadrant (cheap value Z, high growth) is the GARP sweet spot.",
)
ui.metric_glossary()

st.sidebar.header("Thresholds")
score_type = st.sidebar.radio(
    "Z-score type",
    ["cross_sectional_zscore", "time_series_zscore"],
    format_func=lambda s: "Cross-sectional (vs. peers)"
    if s == "cross_sectional_zscore" else "Time-series (vs. own history)",
)
value_threshold = st.sidebar.slider(
    "Max. value Z-score (cheapness)", -3.0, 1.0, -0.5, step=0.25,
    help="Lower = cheaper. Only names at or below this are highlighted.",
)
growth_threshold = st.sidebar.slider(
    "Min. growth Z-score", -2.0, 3.0, 0.5, step=0.25,
)

df = appdata.garp_screen(
    value_threshold=value_threshold,
    growth_threshold=growth_threshold,
    score_type=score_type,
)

if df.empty or "value_zscore" not in df.columns or "growth_score" not in df.columns:
    st.info("No GARP data available for the current settings.")
    st.stop()

plot_df = df.dropna(subset=["value_zscore", "growth_score"]).copy()
color_col = "alpha_score" if "alpha_score" in plot_df.columns else None
st.plotly_chart(
    charts.scatter_quadrant(
        plot_df, x="value_zscore", y="growth_score", label_col="ticker",
        color_col=color_col, x_title="Value Z-score (cheap →)",
        y_title="Growth Z-score (→ growing)",
        title="Value × Growth", x_div=value_threshold, y_div=growth_threshold,
    ),
    use_container_width=True,
)

garp = plot_df[
    (plot_df["value_zscore"] <= value_threshold)
    & (plot_df["growth_score"] >= growth_threshold)
]
st.subheader(f"GARP candidates ({len(garp)})")
sort_col = "alpha_score" if "alpha_score" in garp.columns else "growth_score"
ui.styled_table(garp.sort_values(sort_col, ascending=False).reset_index(drop=True))
