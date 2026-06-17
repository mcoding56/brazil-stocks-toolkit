"""Intrinsic Value (DCF) ranking page."""
from __future__ import annotations

import streamlit as st

from app import charts
from app import data as appdata
from app import ui

st.set_page_config(page_title="Intrinsic Value · Brazil Stocks", page_icon="💰", layout="wide")

ui.page_header(
    "💰 Intrinsic Value (DCF)",
    "Names ranked by margin of safety vs. a two-stage discounted-cash-flow "
    "estimate of intrinsic value.",
)
ui.metric_glossary()

st.sidebar.header("Filters")
top_n = st.sidebar.slider("Show top N", 5, 60, 20, step=5)
min_mos = st.sidebar.slider(
    "Min. margin of safety", -0.5, 0.9, 0.0, step=0.05,
    help="(intrinsic value − price) / intrinsic value",
)
exclude_fin = st.sidebar.checkbox(
    "Exclude financials", value=True,
    help="Banks/insurers — the FCFF DCF does not apply to them.",
)
min_liq = ui.liquidity_slider(20.0)

df = appdata.intrinsic_value_ranking(
    top_n=top_n,
    min_margin_of_safety=min_mos,
    exclude_financials=exclude_fin,
    min_liquidity=min_liq,
)

if df.empty:
    st.info("No rows match the current filters.")
    st.stop()

st.plotly_chart(
    charts.hbar_ranking(
        df, value_col="margin_of_safety", label_col="ticker",
        title="Margin of safety by ticker", value_title="Margin of safety",
    ),
    use_container_width=True,
)

cols = [c for c in ["ticker", "sector", "price", "intrinsic_value",
                    "margin_of_safety", "fcf_per_share", "liquidity_2m",
                    "quality_score", "moat_score"] if c in df.columns]
ui.styled_table(df[cols])

st.caption(
    "Intrinsic value uses a 13% nominal BRL discount rate and 4% terminal "
    "growth; net debt is subtracted to reach equity value per share."
)
