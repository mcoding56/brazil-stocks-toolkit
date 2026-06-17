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
    "🇧🇷 Brazil Stocks — find good companies at good prices",
    "A beginner-friendly way to spot quality Brazilian (B3) companies trading "
    "below their true worth — using the methods of history's great value investors.",
)

summary = appdata.db_summary()
col1, col2, col3, col4 = st.columns(4)
col1.metric("Companies analysed", f"{summary.get('stocks', 0):,}")
col2.metric("Financial snapshots", f"{summary.get('fundamental_snapshots', 0):,}")
col3.metric("Cheapness readings", f"{summary.get('zscore_results', 0):,}")
col4.metric("Daily price bars", f"{summary.get('price_history', 0):,}")

st.divider()

st.subheader("🧭 Start here — pick your question")
st.caption(
    "Each page answers one plain-English question using the playbook of a famous "
    "value investor. Click one to jump in."
)


def _q(page: str, label: str, approach: str) -> None:
    try:
        st.page_link(page, label=label)
    except Exception:
        st.markdown(f"**{label}**")
    st.caption(approach)


qcol1, qcol2 = st.columns(2)
with qcol1:
    _q("pages/1_Intrinsic_Value.py",
       "💰  Is a stock cheaper than it's worth?", "Fair Value · Buffett & Damodaran")
    _q("pages/2_Master_Screen.py",
       "🏆  A good business at a fair price?", "Quality-Value Screen · Graham & Buffett")
    _q("pages/4_Quality_Moat.py",
       "🛡️  Is it a great, durable business?", "Quality & Moat · Buffett & Greenwald")
    _q("pages/8_Learn.py",
       "📚  New here? Read the plain-English guide", "Learn the terms in 2 minutes")
with qcol2:
    _q("pages/5_GARP.py",
       "🌱  Is it cheap AND growing fast?", "GARP · Peter Lynch")
    _q("pages/3_ZScore_Explorer.py",
       "📊  Cheap vs. its own past & its peers?", "Z-Score Explorer · statistics")
    _q("pages/7_Claude_Screen.py",
       "🧠  Blend every signal — what wins?", "All-In-One Ranking · multi-factor")
    _q("pages/6_Stock_Profile.py",
       "🔎  Tell me everything about one stock", "One-Stock Deep Dive")

st.divider()

left, right = st.columns([3, 2])

with left:
    st.subheader("💎 Today's best value picks")
    st.caption(
        "Stocks trading furthest below our estimate of their true worth — at "
        "least 20% cheaper than fair value, excluding banks, only liquid names."
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
    ui.color_legend("cheap")
    ui.styled_table(ui.add_verdict(picks[cols]) if not picks.empty else picks)

with right:
    st.subheader("🎓 Meet the investors")
    st.markdown(
        """
This dashboard turns the ideas of five investing legends into screens you can run:

- **Benjamin Graham** — never overpay; demand a *margin of safety*.
- **Warren Buffett** — wonderful businesses with a *moat*, at a fair price.
- **Aswath Damodaran** — value a company by its future *cash flow* (DCF).
- **Bruce Greenwald** — a real moat shows up as high returns on capital.
- **Peter Lynch** — *growth at a reasonable price* (GARP).

New to these ideas? The **📚 Learn** page explains every term in plain English.
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
