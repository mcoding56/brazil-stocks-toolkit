"""Brazil Stocks — Value-Investing Dashboard (Streamlit entry point).

Run locally with::

    streamlit run streamlit_app.py
"""
from __future__ import annotations

import streamlit as st

from app import data as appdata
from app import ui

st.set_page_config(
    page_title="Brazil Stocks — Value Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

ui.page_header(
    "🇧🇷 Brazil Stocks — Value-Investing Dashboard",
    "Quality-at-a-reasonable-price screening for B3 equities, grounded in the "
    "Graham · Buffett · Damodaran · Greenwald framework.",
)

summary = appdata.db_summary()
col1, col2, col3, col4 = st.columns(4)
col1.metric("Companies", f"{summary.get('stocks', 0):,}")
col2.metric("Fundamental snapshots", f"{summary.get('fundamental_snapshots', 0):,}")
col3.metric("Z-score readings", f"{summary.get('zscore_results', 0):,}")
col4.metric("Price bars", f"{summary.get('price_history', 0):,}")

st.divider()

left, right = st.columns([3, 2])

with left:
    st.subheader("Top intrinsic-value picks")
    st.caption(
        "Cheapest names vs. their DCF intrinsic value (financials excluded, "
        "min. R$20M/day liquidity, margin of safety ≥ 20%)."
    )
    picks = appdata.intrinsic_value_ranking(
        top_n=10,
        min_margin_of_safety=0.20,
        exclude_financials=True,
        min_liquidity=20_000_000,
    )
    cols = [c for c in ["ticker", "sector", "price", "intrinsic_value",
                        "margin_of_safety", "quality_score", "moat_score"]
            if c in picks.columns]
    ui.styled_table(picks[cols] if not picks.empty else picks)

with right:
    st.subheader("How to read this dashboard")
    st.markdown(
        """
- **Intrinsic Value (DCF)** — discounted-cash-flow margin of safety. Banks are
  excluded because the FCFF model does not apply to them.
- **Master Screen** — the Graham-Buffett composite blending margin of safety,
  growth, ROIC, leverage, moat, quality and statistical cheapness.
- **Z-Score Explorer** — how cheap each name is vs. its own history and vs. peers.
- **Quality & Moat** — return-on-capital and margin-based business-quality scores.
- **GARP** — growth at a reasonable price (cheap *and* growing).
- **Stock Profile** — drill into one ticker, with an on-demand live DCF.
        """
    )
    st.info(
        "This is a research tool, not investment advice. Figures are model "
        "estimates from public data and can be wrong or stale.",
        icon="ℹ️",
    )

st.divider()
st.caption(
    "Use the sidebar to navigate between pages. Built on the open-source "
    "`brazil_stocks` toolkit."
)
