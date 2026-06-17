"""Single-ticker drill-down page with an on-demand live DCF."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import charts
from app import data as appdata
from app import ui

st.set_page_config(page_title="Stock Profile · Brazil Stocks", page_icon="🔎", layout="wide")

ui.page_header(
    "🔎 One-stock deep dive",
    "Everything about a single company in one place: how cheap it is, how good the "
    "business is, its price history and a fresh fair-value estimate.",
)
ui.approach_banner(
    "I have a company in mind — is it cheap, and is it any good?",
    "every approach, applied to one stock",
    "Pick a ticker in the sidebar. The headline shows price vs. fair value at a "
    "glance; below you'll find the detailed numbers, charts and a live valuation.",
)
ui.learn_link()

tickers = appdata.all_tickers()
if not tickers:
    st.info("No tickers in the database.")
    st.stop()

default_idx = tickers.index("PETR4") if "PETR4" in tickers else 0
ticker = st.sidebar.selectbox("Ticker", tickers, index=default_idx)

profile = appdata.stock_profile(ticker)
fund = profile.get("latest_fundamentals", {}) or {}

# ----------------------------------------------------------------------
# Headline metrics
# ----------------------------------------------------------------------
def _num(key: str):
    v = fund.get(key)
    return v if isinstance(v, (int, float)) and pd.notna(v) else None


c0, c1, c2, c3, c4 = st.columns(5)
price = _num("price")
iv = _num("intrinsic_value")
mos = _num("margin_of_safety")
overall = appdata.overall_score_map().get(ticker)
c0.metric(
    "Overall score",
    f"{overall:.0f} / 100" if overall is not None else "—",
    help="The single 0–100 grade blending quality, momentum, value, safety, "
         "moat and growth across the whole market. ~50 is average, 70+ is rare.",
)
c1.metric("Price", f"R$ {price:,.2f}" if price is not None else "—")
c2.metric("Intrinsic value", f"R$ {iv:,.2f}" if iv is not None else "—")
c3.metric("Margin of safety", f"{mos:.1%}" if mos is not None else "—")
q = _num("quality_score")
c4.metric("Quality score", f"{q:.0%}" if q is not None else "—")

sector = fund.get("sector")
if sector:
    st.caption(f"Sector: **{sector}**")

# Plain-English one-line verdict from the headline numbers.
_verdict_df = ui.add_verdict(pd.DataFrame([{
    "margin_of_safety": mos,
    "quality_score": q,
}]))
if "Verdict" in _verdict_df.columns:
    _v = _verdict_df["Verdict"].iloc[0]
    if _v and _v != "—":
        st.markdown(f"### {_v}")

st.divider()

# ----------------------------------------------------------------------
# Fundamentals + Z-scores
# ----------------------------------------------------------------------
left, right = st.columns(2)

with left:
    st.subheader("Latest fundamentals")
    rows = []
    for key, label in ui.METRIC_LABELS.items():
        val = _num(key)
        if val is not None:
            rows.append({"Metric": label, "Value": val})
    for key in ["net_debt_ebitda", "fcf_per_share", "dividend_cagr_5y", "payout"]:
        val = _num(key)
        if val is not None:
            rows.append({"Metric": key.replace("_", " ").title(), "Value": val})
    if rows:
        st.dataframe(
            pd.DataFrame(rows).style.format({"Value": "{:.2f}"}),
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("No fundamentals stored for this ticker.")

with right:
    st.subheader("Z-scores")
    z = pd.DataFrame(profile.get("zscores", []))
    if z.empty:
        st.info("No Z-scores available.")
    else:
        keep = [c for c in ["metric", "time_series_zscore", "cross_sectional_zscore"]
                if c in z.columns]
        z = z[keep].copy()
        z["metric"] = z["metric"].map(lambda m: ui.METRIC_LABELS.get(m, m))
        st.dataframe(
            z.style.format(
                {"time_series_zscore": "{:.2f}", "cross_sectional_zscore": "{:.2f}"},
                na_rep="—",
            ),
            use_container_width=True, hide_index=True,
        )

st.divider()

# ----------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------
prices = appdata.price_history(ticker)
pl_hist = appdata.historical_pl(ticker)

cc1, cc2 = st.columns(2)
with cc1:
    if prices is not None and not prices.empty:
        st.plotly_chart(charts.price_line(prices, ticker), use_container_width=True)
    else:
        st.info("No price history stored for this ticker (slim DB keeps IBOV only).")
with cc2:
    if pl_hist is not None and len(pl_hist) > 1:
        st.plotly_chart(charts.pl_history_line(pl_hist, ticker), use_container_width=True)
    else:
        st.info("Not enough P/L history to plot.")

st.divider()

# ----------------------------------------------------------------------
# On-demand live DCF
# ----------------------------------------------------------------------
st.subheader("Live DCF (on demand)")
st.caption(
    "Fetches the latest free cash flow and share count from yfinance and "
    "recomputes intrinsic value. May take a few seconds and can fail for "
    "thinly-covered tickers."
)
if st.button(f"Run live DCF for {ticker}", type="primary"):
    with st.spinner("Fetching cash flow & valuing…"):
        try:
            res = appdata.live_dcf(ticker)
        except Exception as exc:  # noqa: BLE001 — surface any fetch failure to the UI
            st.error(f"Live DCF failed: {exc}")
            res = None
    if res:
        iv = res.get("intrinsic_value")
        mos = res.get("margin_of_safety")
        m1, m2, m3 = st.columns(3)
        m1.metric("Intrinsic value", f"R$ {iv:,.2f}" if iv else "—")
        m2.metric("Margin of safety", f"{mos:.1%}" if mos is not None else "—")
        m3.metric(
            "Assumed growth",
            f"{res['assumed_growth']:.1%}" if res.get("assumed_growth") is not None else "—",
        )
        with st.expander("DCF inputs & assumptions"):
            st.json({k: v for k, v in res.items() if k not in {"ticker"}})
        if iv is None:
            st.warning(
                "Intrinsic value could not be computed (missing FCF, negative "
                "equity value, or no share count)."
            )
