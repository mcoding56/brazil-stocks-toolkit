"""Graham-Buffett master screen page."""
from __future__ import annotations

import streamlit as st

from app import charts
from app import data as appdata
from app import ui

st.set_page_config(page_title="Master Screen · Brazil Stocks", page_icon="🏆", layout="wide")

ui.page_header(
    "🏆 Quality-Value Screen — a good business at a fair price",
    "One overall score that rewards companies which are cheap, profitable, growing, "
    "lowly indebted and have a durable edge — all at once.",
)
ui.approach_banner(
    "Which companies tick every box: cheap, high-quality, safe and growing?",
    "Benjamin Graham & Warren Buffett",
    "We score each company on seven value priorities and blend them into a single "
    "ranking. Higher score = a better all-round value-investing candidate.",
)
ui.learn_link()

st.sidebar.header("Filters")
top_n = st.sidebar.slider("Show top N", 5, 60, 20, step=5)
min_mos = st.sidebar.slider("Min. margin of safety", -0.5, 0.9, 0.20, step=0.05)
min_quality = st.sidebar.slider("Min. quality score", 0.0, 1.0, 0.50, step=0.05)
min_growth = st.sidebar.slider(
    "Min. growth Z-score", -3.0, 3.0, -3.0, step=0.5,
    help="Cross-sectional growth Z-score. Lower = looser.",
)
use_debt_cap = st.sidebar.checkbox("Cap net debt / equity", value=False)
max_de = (
    st.sidebar.slider("Max. net debt / equity (%)", 0.0, 300.0, 150.0, step=10.0)
    if use_debt_cap else None
)
exclude_fin = st.sidebar.checkbox("Exclude financials", value=True)
min_liq = ui.liquidity_slider(20.0)

df = appdata.master_screen(
    min_margin_of_safety=min_mos,
    min_quality=min_quality,
    min_growth=min_growth,
    max_debt_equity=max_de,
    exclude_financials=exclude_fin,
    min_liquidity=min_liq,
    top_n=top_n,
)

if df.empty:
    st.info("No rows match the current filters. Try loosening the thresholds.")
    st.stop()

ui.color_legend("cheap")
ui.chart_caption("Longer bars rank higher overall — a better blend of cheap, quality, safe and growing.")
st.plotly_chart(
    charts.hbar_ranking(
        df, value_col="master_score", label_col="ticker",
        color_col="master_score", title="Master score by ticker",
        value_title="Master score",
    ),
    use_container_width=True,
)

cols = [c for c in ["ticker", "sector", "price", "pl", "pvp", "roic",
                    "debt_equity", "intrinsic_value", "margin_of_safety",
                    "quality_score", "moat_score", "growth_score",
                    "value_zscore", "price_vwap_z", "master_score"] if c in df.columns]
ui.styled_table(ui.with_overall_score(ui.add_verdict(df[cols])))
