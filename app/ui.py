"""Shared UI constants and small helpers for the dashboard pages."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import data as appdata

METRIC_LABELS: dict[str, str] = {
    "overall_score": "Overall score (0–100)",
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
    "price_vwap_z": "Price vs. VWAP (cheapness)",
}

# The metric keys that have z-score results (everything in METRIC_LABELS except
# the composite ``overall_score``, which is a blended grade, not a z-scored metric).
ZSCORE_METRICS: list[str] = [k for k in METRIC_LABELS if k != "overall_score"]

# Metrics where a *lower* reading is cheaper/better (used to set sort direction).
LOWER_IS_CHEAPER = frozenset(
    ["pl", "pvp", "ev_ebitda", "ev_ebit", "p_ebit", "ps", "debt_equity",
     "price_vwap_z"]
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
    # --- Price cheapness ---
    "price_vwap_z": (
        "(recent volume-weighted price − 2-year VWAP) ÷ price std. dev.",
        "How cheap the share price is versus where it has actually traded. The "
        "reference is the volume-weighted average price (VWAP) over the trailing "
        "~2 years; the 'current' value is the VWAP of the last ~21 sessions. "
        "Negative = trading below its own VWAP (a mean-reversion cheap signal); "
        "positive = extended above it.",
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
    "overall_score": (
        "Weighted blend of six percentile-ranked pillars — quality 25, momentum "
        "20, valuation 20, safety 15, moat 10, growth 10 — rescaled to 0–100",
        "The single at-a-glance grade for a stock. It rolls the whole dashboard "
        "into one number: a good business (high returns, low debt, a moat, "
        "steady growth, positive trend) bought at a good price scores high. "
        "Ranked across the whole market, so ~50 is average and 70+ is rare.",
    ),
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
    ("Price cheapness",
     ["price_vwap_z"]),
    ("Growth",
     ["eps_yoy", "eps_slope", "positive_qtr_ratio", "revenue_growth_5y",
      "growth_score"]),
    ("Price factors (momentum & risk)",
     ["momentum_12_1", "momentum_6_1", "volatility_6m", "dist_52w_high"]),
    ("Composite scores & valuation",
     ["overall_score", "quality_score", "moat_score", "margin_of_safety", "intrinsic_value"]),
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
        elif col == "overall_score":
            fmt[col] = "{:.0f}"
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


# ---------------------------------------------------------------------------
# Beginner-friendly framing helpers
# ---------------------------------------------------------------------------

# The five value-investing legends, mapped to a one-line philosophy and the page
# that applies their idea. Reused on the home page and the Learn page.
INVESTOR_LEGENDS: list[tuple[str, str, str]] = [
    ("Benjamin Graham",
     "Buy with a margin of safety — pay clearly less than a business is worth.",
     "Quality-Value Screen"),
    ("Warren Buffett",
     "Wonderful businesses (high returns on capital, a durable moat) at a fair price.",
     "Fair Value · Great Business?"),
    ("Aswath Damodaran",
     "Value a company by the cash it will generate in the future (a DCF).",
     "Fair Value"),
    ("Bruce Greenwald",
     "A real competitive advantage shows up as high, stable returns on capital.",
     "Great Business?"),
    ("Peter Lynch",
     "Growth at a reasonable price — fast growers you don't overpay for.",
     "Cheap AND Growing"),
]


def approach_banner(question: str, investors: str, why: str) -> None:
    """Render a plain-English framing block right under the page header.

    Parameters
    ----------
    question  : the plain-English question this page answers (the headline).
    investors : the investing legend(s) whose approach this applies.
    why       : one line on why the approach works / what to take away.
    """
    st.info(f"**{question}**\n\n"
            f"🎓 *Approach of {investors}.* {why}", icon="❓")


def color_legend(kind: str = "cheap") -> None:
    """One-line caption explaining the green→red colour scale used in charts."""
    if kind == "quality":
        st.caption("🟢 strong / high-quality   ·   ⚪ average   ·   🔴 weak")
    elif kind == "growth":
        st.caption("🟢 cheap **and** growing   ·   ⚪ mixed   ·   🔴 expensive / shrinking")
    else:
        st.caption("🟢 cheap (good value)   ·   ⚪ fairly priced   ·   🔴 expensive")


def chart_caption(text: str) -> None:
    """Small 'what to look for' hint shown just above a chart."""
    st.caption(f"👀 {text}")


def learn_link() -> None:
    """Replace the bulky per-page glossary with a compact link to the Learn page."""
    try:
        st.page_link(
            "pages/8_📚_Learn.py",
            label="New to these terms? Open the plain-English guide →",
            icon="📚",
        )
    except Exception:
        # st.page_link is unavailable in very old Streamlit / some test harnesses.
        st.caption("📚 New to these terms? See the **Learn** page in the sidebar.")


def add_verdict(df: pd.DataFrame) -> pd.DataFrame:
    """Add a plain-English ``Verdict`` column derived from existing score columns.

    Combines a *cheapness* read (margin of safety, then value/price z-scores) with
    a *quality* read (quality_score) into a one-glance badge. NaN-safe: a missing
    input simply drops out of that side of the verdict. Returns a copy with the
    ``Verdict`` column inserted first; a no-op if no usable columns are present.
    """
    if df is None or df.empty:
        return df

    n = len(df)

    def _num(col: str) -> pd.Series | None:
        return pd.to_numeric(df[col], errors="coerce") if col in df.columns else None

    mos = _num("margin_of_safety")
    val_z = _num("value_zscore")
    price_z = _num("price_vwap_z")
    quality = _num("quality_score")

    # Cheapness: True = cheap, False = expensive, NaN = unknown.
    cheap = pd.Series([pd.NA] * n, index=df.index, dtype="object")
    if mos is not None:
        cheap = cheap.mask(mos >= 0.20, True).mask(mos <= 0.0, False)
    elif val_z is not None:
        cheap = cheap.mask(val_z <= -0.5, True).mask(val_z >= 0.5, False)
    elif price_z is not None:
        cheap = cheap.mask(price_z <= -0.5, True).mask(price_z >= 0.5, False)

    # Quality: True = strong, False = weak, NaN = unknown.
    strong = pd.Series([pd.NA] * n, index=df.index, dtype="object")
    if quality is not None:
        strong = strong.mask(quality >= 0.60, True).mask(quality < 0.40, False)

    if cheap.isna().all() and strong.isna().all():
        return df  # nothing to say

    def _verdict(c, s) -> str:
        if c is True and s is True:
            return "🟢 Cheap & high-quality"
        if c is True and s is False:
            return "⚠️ Cheap but weak"
        if c is True:
            return "🟢 Looks cheap"
        if c is False and s is True:
            return "🟡 Great business, pricey"
        if c is False:
            return "🔴 Looks expensive"
        if s is True:
            return "💪 High-quality"
        if s is False:
            return "⚠️ Lower-quality"
        return "—"

    verdict = [_verdict(cheap.iloc[i], strong.iloc[i]) for i in range(n)]
    out = df.copy()
    out.insert(0, "Verdict", verdict)
    return out


def with_overall_score(df: pd.DataFrame, min_liquidity: float | None = None) -> pd.DataFrame:
    """Attach the universal 0–100 ``overall_score`` column to any table by ticker.

    Looks each row's ticker up in the market-wide Overall Score and inserts the
    column right after ``Verdict`` (or first, if there is no verdict). A no-op
    when the frame has no ``ticker`` column or the score map is empty, so it is
    safe to wrap around every screen result.
    """
    if df is None or df.empty or "ticker" not in df.columns:
        return df
    scores = appdata.overall_score_map(min_liquidity)
    if not scores:
        return df
    vals = pd.to_numeric(df["ticker"].map(scores), errors="coerce")
    if vals.notna().sum() == 0:
        return df
    out = df.copy()
    if "overall_score" in out.columns:
        out = out.drop(columns=["overall_score"])
    pos = 1 if "Verdict" in out.columns else 0
    out.insert(pos, "overall_score", vals.round(0))
    return out
