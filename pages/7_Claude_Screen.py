"""The Claude Screen — an opinionated, reliability-weighted composite."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app import charts
from app import data as appdata
from app import ui
from brazil_stocks.orchestrator import CLAUDE_WEIGHTS

st.set_page_config(page_title="Claude Screen · Brazil Stocks", page_icon="🧠", layout="wide")

ui.page_header(
    "🧠 The Claude Screen",
    "An opinionated rebuild of the master screen. Every pillar is percentile-ranked "
    "to 0–1 *within the surviving cohort* before weighting, so the weights below are "
    "literally each pillar's maximum contribution.",
)

with st.expander("Why this differs from the Graham-Buffett screen", expanded=False):
    st.markdown(
        """
The classic `master_score` simply **adds** margin of safety, quality, moat, growth and
value together. Those columns live on different scales (a 0–1 fraction vs a Z-score), so
whichever has the widest range quietly dominates — the weighting was an *accident of
scale*, not a decision. It also **triple-counts return on capital** (it appears in
quality, in moat, and on its own) and gives the **noisiest** input — a single-point DCF
margin of safety — full, uncapped weight.

**The Claude Screen fixes four things:**

1. **Intentional weighting.** Each pillar is percentile-ranked to 0–1 first, so the
   weights are the literal maximum contribution.
2. **The DCF is demoted.** Margin of safety is winsorised and sits at 40% *inside* the
   valuation pillar, behind robust peer multiples (60%).
3. **Quality and moat are de-correlated.** Moat keeps a deliberately small 15% weight.
4. **Leverage is a graded penalty, not a gate** — its own 20% safety pillar.

Growth is **conditioned on ROIC clearing its hurdle**: growth without returns above the
cost of capital destroys value, so it only earns full credit when the business out-earns
its capital.
        """
    )

# ── Sidebar: weights & gates ────────────────────────────────────────────────
st.sidebar.header("Pillar weights")
st.sidebar.caption("Defaults reflect *reliability × durability*. They are re-normalised to 100%.")
w_quality = st.sidebar.slider("Quality (ROIC, margins)", 0.0, 0.50, CLAUDE_WEIGHTS["quality"], 0.05)
w_safety = st.sidebar.slider("Safety (low leverage)", 0.0, 0.50, CLAUDE_WEIGHTS["safety"], 0.05)
w_valuation = st.sidebar.slider("Valuation (multiples + DCF)", 0.0, 0.50, CLAUDE_WEIGHTS["valuation"], 0.05)
w_moat = st.sidebar.slider("Moat (durability)", 0.0, 0.50, CLAUDE_WEIGHTS["moat"], 0.05)
w_growth = st.sidebar.slider("Growth (ROIC-conditioned)", 0.0, 0.50, CLAUDE_WEIGHTS["growth"], 0.05)

weights = {
    "quality": w_quality,
    "safety": w_safety,
    "valuation": w_valuation,
    "moat": w_moat,
    "growth": w_growth,
}

st.sidebar.header("Gates")
top_n = st.sidebar.slider("Show top N", 5, 60, 20, step=5)
roic_hurdle = st.sidebar.slider(
    "ROIC hurdle (%)", 0.0, 25.0, 10.0, step=1.0,
    help="Growth is damped toward zero below this ROIC (the cost-of-capital proxy).",
)
exclude_fin = st.sidebar.checkbox("Exclude financials", value=True)
min_liq = ui.liquidity_slider(20.0)

total_w = sum(weights.values())
if total_w <= 0:
    st.warning("All pillar weights are zero — give at least one pillar some weight.")
    st.stop()

# Show the normalised weight mix.
norm = {k: v / total_w for k, v in weights.items()}
wcols = st.columns(5)
for col, (name, val) in zip(wcols, norm.items()):
    col.metric(name.title(), f"{val:.0%}")

df = appdata.claude_screen(
    weights=weights,
    roic_hurdle=roic_hurdle,
    exclude_financials=exclude_fin,
    min_liquidity=min_liq,
    top_n=top_n,
)

if df.empty:
    st.info("No rows match the current filters. Try loosening the gates.")
    st.stop()

st.plotly_chart(
    charts.hbar_ranking(
        df, value_col="claude_score", label_col="ticker",
        color_col="claude_score", title="Claude score by ticker",
        value_title="Claude score (0–1)",
    ),
    use_container_width=True,
)

# ── Stacked pillar-contribution chart (shows *why* each name ranks) ──────────
pillar_cols = ["quality_pillar", "safety_pillar", "valuation_pillar", "moat_pillar", "growth_pillar"]
pillar_labels = {
    "quality_pillar": "Quality",
    "safety_pillar": "Safety",
    "valuation_pillar": "Valuation",
    "moat_pillar": "Moat",
    "growth_pillar": "Growth",
}
if all(c in df.columns for c in pillar_cols):
    d = df.sort_values("claude_score", ascending=True)
    fig = go.Figure()
    for col in pillar_cols:
        weighted = d[col].fillna(0) * norm[col.replace("_pillar", "")]
        fig.add_trace(
            go.Bar(
                y=d["ticker"], x=weighted, name=pillar_labels[col],
                orientation="h",
            )
        )
    fig.update_layout(
        barmode="stack",
        height=max(360, 24 * len(d)),
        margin=dict(l=10, r=10, t=50, b=10),
        title="Weighted pillar contributions",
        xaxis_title="Contribution to Claude score",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

cols = [c for c in [
    "ticker", "sector", "price", "roic", "debt_equity",
    "intrinsic_value", "margin_of_safety",
    "quality_pillar", "safety_pillar", "valuation_pillar",
    "moat_pillar", "growth_pillar", "claude_score",
] if c in df.columns]
ui.styled_table(df[cols])
