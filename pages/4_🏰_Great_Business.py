"""Quality & Moat scorecard page."""
from __future__ import annotations

import streamlit as st

from app import charts
from app import data as appdata
from app import ui

st.set_page_config(page_title="Quality & Moat · Brazil Stocks", page_icon="🛡️", layout="wide")

ui.page_header(
    "🛡️ Great business? — Quality & Moat",
    "How good and how durable each business is — measured by how much profit it "
    "earns on its capital, its margins and how little debt it carries.",
)
ui.approach_banner(
    "Is this a genuinely great, durable business worth owning for the long run?",
    "Warren Buffett & Bruce Greenwald",
    "'Quality' captures how efficiently a company turns money into profit. 'Moat' "
    "is its durable competitive edge. The best businesses score high on both "
    "(top-right of the chart).",
)
ui.learn_link()

st.sidebar.header("Filters")
top_n = st.sidebar.slider("Show top N", 10, 80, 30, step=5)
exclude_fin = st.sidebar.checkbox("Exclude financials", value=True)
min_liq = ui.liquidity_slider(20.0)

df = appdata.quality_table(exclude_financials=exclude_fin, min_liquidity=min_liq)

if df.empty:
    st.info("No quality scores available.")
    st.stop()

top = df.head(top_n)
ui.color_legend("quality")
ui.chart_caption("Top-right = high quality AND a wide moat — the best businesses. Brighter colour = higher returns on capital.")
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
ui.styled_table(appdata.attach_overall_score(ui.add_verdict(top[cols])))
