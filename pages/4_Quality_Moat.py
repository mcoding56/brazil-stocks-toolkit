"""Quality & Moat scorecard page."""
from __future__ import annotations

import streamlit as st

from app import charts
from app import data as appdata
from app import ui

st.set_page_config(page_title="Quality & Moat · Brazil Stocks", page_icon="🛡️", layout="wide")

ui.page_header(
    "🛡️ Quality & Moat",
    "Business-quality and competitive-advantage scores (0–1) built from "
    "percentile ranks of ROIC, margins and leverage.",
)

st.sidebar.header("Filters")
top_n = st.sidebar.slider("Show top N", 10, 80, 30, step=5)
exclude_fin = st.sidebar.checkbox("Exclude financials", value=True)
min_liq = ui.liquidity_slider(20.0)

df = appdata.quality_table(exclude_financials=exclude_fin, min_liquidity=min_liq)

if df.empty:
    st.info("No quality scores available.")
    st.stop()

top = df.head(top_n)
st.plotly_chart(
    charts.scatter_quadrant(
        top, x="quality_score", y="moat_score", label_col="ticker",
        color_col="roic", x_title="Quality score", y_title="Moat score",
        title="Quality vs. moat (colour = ROIC)",
        x_div=top["quality_score"].median(), y_div=top["moat_score"].median(),
    ),
    use_container_width=True,
)

cols = [c for c in ["ticker", "sector", "price", "roic", "roe", "gross_margin",
                    "net_margin", "debt_equity", "quality_score", "moat_score"]
        if c in top.columns]
ui.styled_table(top[cols])
