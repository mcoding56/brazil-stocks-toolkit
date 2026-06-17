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
