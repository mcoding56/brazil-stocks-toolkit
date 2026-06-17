"""GARP (Growth at a Reasonable Price) screen page."""
from __future__ import annotations

import streamlit as st

from app import charts
from app import data as appdata
from app import ui

st.set_page_config(page_title="GARP · Brazil Stocks", page_icon="🌱", layout="wide")

ui.page_header(
    "🌱 Cheap AND growing — GARP",
    "Companies that are both reasonably priced and growing fast — the rare "
    "combination Peter Lynch hunted for.",
)
ui.approach_banner(
    "Which fast-growing companies can I still buy at a sensible price?",
    "Peter Lynch",
    "GARP = 'Growth At a Reasonable Price'. The sweet spot is the bottom-right of "
    "the chart: cheap on the left axis, fast-growing on the up axis.",
)
ui.learn_link()

st.sidebar.header("Thresholds")
score_type = st.sidebar.radio(
    "Compare against…",
    ["cross_sectional_zscore", "time_series_zscore"],
    format_func=lambda s: "Its peers (right now)"
    if s == "cross_sectional_zscore" else "Its own history (over time)",
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
ui.color_legend("growth")
ui.chart_caption("Look bottom-right: cheap (left) and growing (up). That quadrant is the GARP sweet spot.")
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
ui.styled_table(
    ui.with_overall_score(
        ui.add_verdict(garp.sort_values(sort_col, ascending=False).reset_index(drop=True))
    )
)
