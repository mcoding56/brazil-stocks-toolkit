"""Shared UI constants and small helpers for the dashboard pages."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import data as appdata

METRIC_LABELS: dict[str, str] = {
    "pl": "P/L (P/E)",
    "pvp": "P/VP (P/B)",
    "ev_ebitda": "EV/EBITDA",
    "ev_ebit": "EV/EBIT",
    "p_ebit": "P/EBIT",
    "ps": "P/S",
    "dy": "Dividend yield",
    "roe": "ROE",
    "roic": "ROIC",
    "gross_margin": "Gross margin",
    "ebit_margin": "EBIT margin",
    "net_margin": "Net margin",
    "debt_equity": "Net debt / equity",
    "current_ratio": "Current ratio",
}

# Metrics where a *lower* reading is cheaper/better (used to set sort direction).
LOWER_IS_CHEAPER = frozenset(
    ["pl", "pvp", "ev_ebitda", "ev_ebit", "p_ebit", "ps", "debt_equity"]
)

# Plain-language definition + formula for every metric surfaced in the dashboard.
# Each entry is (formula, what-it-means). Used by `metric_explainer` (inline,
# next to a metric picker) and by `metric_glossary` (the full expandable table).
METRIC_INFO: dict[str, tuple[str, str]] = {
    # --- Valuation multiples (lower is cheaper) ---
    "pl": (
        "Price ÷ earnings per share (trailing 12 months)",
        "What you pay for R$1 of annual profit. Lower is cheaper. Loss-making "
        "names (negative P/E) are excluded — a negative multiple is undefined, "
        "not cheap.",
    ),
    "pvp": (
        "Price ÷ book value per share",
        "Price relative to accounting net worth. Below 1.0 means the market "
        "values the company under its book equity.",
    ),
    "ev_ebitda": (
        "Enterprise value ÷ EBITDA   (EV = market cap + net debt)",
        "Capital-structure-neutral cash-earnings multiple. Comparable across "
        "companies with different leverage.",
    ),
    "ev_ebit": (
        "Enterprise value ÷ EBIT",
        "Like EV/EBITDA but charges for depreciation — a stricter view of "
        "operating earnings.",
    ),
    "p_ebit": (
        "Price ÷ EBIT",
        "Equity price against operating profit.",
    ),
    "ps": (
        "Price ÷ sales per share",
        "Revenue multiple. Useful when earnings are temporarily depressed or "
        "noisy.",
    ),
    "dy": (
        "Trailing dividends ÷ price (%)",
        "Cash yield paid to shareholders. Higher means more income, but an "
        "unusually high yield can signal a stressed or shrinking business.",
    ),
    # --- Profitability / quality ---
    "roe": (
        "Net income ÷ shareholders' equity (%)",
        "Profit generated per R$1 of equity. A core return-on-capital signal.",
    ),
    "roic": (
        "NOPAT ÷ invested capital (%)",
        "Return on all capital employed (debt + equity). The central "
        "Buffett/Greenwald quality measure — durable franchises earn high ROIC.",
    ),
    "gross_margin": (
        "Gross profit ÷ revenue (%)",
        "Pricing power before operating costs. Wide, stable gross margins hint "
        "at a moat.",
    ),
    "ebit_margin": (
        "EBIT ÷ revenue (%)",
        "Operating efficiency — profit after running costs but before interest "
        "and tax.",
    ),
    "net_margin": (
        "Net income ÷ revenue (%)",
        "Bottom-line profitability after all costs, interest and tax.",
    ),
    # --- Balance-sheet safety ---
    "debt_equity": (
        "Net debt ÷ equity",
        "Leverage. Lower is safer; a negative value means net cash (more cash "
        "than debt).",
    ),
    "current_ratio": (
        "Current assets ÷ current liabilities",
        "Short-term liquidity. Above 1.0 means near-term assets cover near-term "
        "bills.",
    ),
    # --- Growth ---
    "eps_yoy": (
        "Year-over-year growth of TTM earnings per share",
        "Four-quarter change in trailing-twelve-month EPS.",
    ),
    "eps_slope": (
        "OLS slope of TTM EPS over time ÷ mean |EPS|",
        "Trend strength of earnings, normalised so it is comparable across "
        "companies of different size.",
    ),
    "positive_qtr_ratio": (
        "Share of quarters where TTM EPS rose (0–1)",
        "Consistency of earnings growth — how often the trend was up.",
    ),
    "revenue_growth_5y": (
        "5-year revenue CAGR (Fundamentus)",
        "Compound annual revenue growth over the last five years.",
    ),
    "growth_score": (
        "Average of the cross-sectional z-scores of the four growth signals",
        "Composite growth rank: blends EPS YoY, EPS trend, consistency and "
        "5-year revenue CAGR. Higher = faster, steadier grower vs. peers.",
    ),
    # --- Price factors ---
    "momentum_12_1": (
        "12-month return skipping the last month:  P[t−21] ÷ P[t−252] − 1",
        "Classic price momentum. The most robust standalone anomaly; the "
        "skipped month avoids short-term reversal.",
    ),
    "momentum_6_1": (
        "6-month return skipping the last month",
        "Shorter-horizon momentum.",
    ),
    "volatility_6m": (
        "Annualised standard deviation of daily log returns (trailing 6 months)",
        "Realised risk. Lower-volatility names tend to deliver better "
        "risk-adjusted returns (the low-volatility anomaly).",
    ),
    "dist_52w_high": (
        "Latest price ÷ trailing 52-week high",
        "Proximity to the one-year high (1.0 = sitting at the high).",
    ),
    # --- Composite scores ---
    "quality_score": (
        "Weighted % rank of ROIC (25), net margin (15), ROE (15), gross "
        "margin (15), EBIT margin (10), low net-debt/equity (12), current "
        "ratio (8)",
        "Overall business quality on a 0–1 scale (percentile-rank based, so it "
        "is robust to how the source reports each figure).",
    ),
    "moat_score": (
        "Weighted % rank of ROIC (40), gross margin (30), low leverage (30)",
        "A narrower 0–1 proxy for a durable competitive advantage — pricing "
        "power and capital efficiency.",
    ),
    "margin_of_safety": (
        "1 − price ÷ intrinsic value",
        "Discount to DCF fair value. A 20% margin of safety means the price is "
        "20% below the model's estimate of intrinsic worth.",
    ),
    "intrinsic_value": (
        "Per-share DCF: discounted projected free cash flow + terminal value, "
        "÷ shares outstanding",
        "Estimated fair value from a discounted-cash-flow model. Banks are "
        "excluded because the FCFF model does not apply to them.",
    ),
    # --- Z-score conventions ---
    "time_series_zscore": (
        "(current − mean of the metric's own 5-year history) ÷ its std. dev.",
        "How cheap/extreme a name is versus its own past. −2 means two standard "
        "deviations below its typical level.",
    ),
    "cross_sectional_zscore": (
        "(current − peer mean) ÷ peer std. dev.",
        "How cheap/extreme a name is versus its peers right now.",
    ),
}

# Ordered groups for the full glossary so related metrics sit together.
METRIC_GROUPS: list[tuple[str, list[str]]] = [
    ("Valuation multiples (lower is cheaper)",
     ["pl", "pvp", "ev_ebitda", "ev_ebit", "p_ebit", "ps", "dy"]),
    ("Profitability & quality",
     ["roe", "roic", "gross_margin", "ebit_margin", "net_margin"]),
    ("Balance-sheet safety",
     ["debt_equity", "current_ratio"]),
    ("Growth",
     ["eps_yoy", "eps_slope", "positive_qtr_ratio", "revenue_growth_5y",
      "growth_score"]),
    ("Price factors (momentum & risk)",
     ["momentum_12_1", "momentum_6_1", "volatility_6m", "dist_52w_high"]),
    ("Composite scores & valuation",
     ["quality_score", "moat_score", "margin_of_safety", "intrinsic_value"]),
    ("Z-score conventions",
     ["time_series_zscore", "cross_sectional_zscore"]),
]

PERCENT_COLS = frozenset(
    ["margin_of_safety", "roic", "roe", "gross_margin", "ebit_margin",
     "net_margin", "dy", "quality_score", "moat_score"]
)


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    snap = appdata.latest_snapshot_date()
    src = "slim read-only DB" if appdata.using_slim_db() else "full local DB"
    st.caption(f"Data as of **{snap or 'n/a'}** · source: {src}")


def liquidity_slider(default_millions: float = 20.0) -> float | None:
    millions = st.sidebar.slider(
        "Min. liquidity (R$ millions/day)",
        min_value=0.0,
        max_value=200.0,
        value=default_millions,
        step=5.0,
        help="2-month average daily traded volume. Filters out thin microcaps.",
    )
    return millions * 1_000_000 if millions > 0 else None


def styled_table(df: pd.DataFrame, percent_cols: set[str] | None = None) -> None:
    """Render a DataFrame with sensible numeric formatting."""
    if df.empty:
        st.info("No rows match the current filters.")
        return
    pct = (percent_cols or set()) | {c for c in df.columns if c in PERCENT_COLS}
    fmt: dict[str, str] = {}
    for col in df.select_dtypes("number").columns:
        # Quality/moat/margin-of-safety are 0–1 fractions → show as %.
        if col in {"margin_of_safety", "quality_score", "moat_score"}:
            fmt[col] = "{:.1%}"
        elif col in pct:
            fmt[col] = "{:.1f}"
        elif col in {"liquidity_2m"}:
            fmt[col] = "{:,.0f}"
        else:
            fmt[col] = "{:.2f}"
    st.dataframe(df.style.format(fmt, na_rep="—"), use_container_width=True)


def metric_label(metric: str) -> str:
    """Human-readable label for a metric key, falling back to the key itself."""
    return METRIC_LABELS.get(metric, metric.replace("_", " ").title())


def metric_explainer(metric: str) -> None:
    """Render an inline formula + plain-language note for a single metric.

    Useful right next to a metric picker (e.g. the Z-Score Explorer) so the
    user always sees how the selected metric is defined.
    """
    info = METRIC_INFO.get(metric)
    if not info:
        return
    formula, desc = info
    st.caption(f"**{metric_label(metric)}** — `{formula}`")
    st.caption(desc)


def metric_glossary(expanded: bool = False) -> None:
    """Render the full, grouped metric glossary inside an expander."""
    with st.expander("📖 Metric glossary — what each number means & how it's calculated",
                     expanded=expanded):
        st.caption(
            "All figures come from public data (Fundamentus + Yahoo Finance) and "
            "are model estimates. Valuation multiples use trailing-twelve-month "
            "fundamentals; price factors use the stored daily history."
        )
        for group_title, metrics in METRIC_GROUPS:
            rows = []
            for m in metrics:
                info = METRIC_INFO.get(m)
                if not info:
                    continue
                formula, desc = info
                rows.append({
                    "Metric": metric_label(m),
                    "Formula": formula,
                    "What it tells you": desc,
                })
            if not rows:
                continue
            st.markdown(f"**{group_title}**")
            st.dataframe(
                pd.DataFrame(rows).set_index("Metric"),
                use_container_width=True,
            )
