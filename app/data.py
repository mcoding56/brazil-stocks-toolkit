"""Cached data access for the Streamlit dashboard.

All heavy objects (the orchestrator / SQLite connection) are created once via
``st.cache_resource``; every screen/ranking call is wrapped in ``st.cache_data``
so repeated interactions are instant. The app reads the slim, read-only
``data/brazil_stocks_slim.db`` when present, falling back to the full DB locally.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from brazil_stocks.orchestrator import StockAnalysisOrchestrator, _is_financial

SLIM_DB = "data/brazil_stocks_slim.db"
FULL_DB = "data/brazil_stocks.db"

# Fallback safety net: well-known B3 banks, insurers, exchanges and financial
# holdings. The orchestrator excludes financials by *sector*, but the slim DB
# only has sectors for the most-liquid names, so we also drop these tickers when
# the user asks to exclude financials.
KNOWN_FINANCIALS: frozenset[str] = frozenset({
    # Banks
    "ITUB3", "ITUB4", "BBDC3", "BBDC4", "BBAS3", "SANB3", "SANB4", "SANB11",
    "BPAC3", "BPAC5", "BPAC11", "BPAN4", "BMGB4", "BRSR3", "BRSR5", "BRSR6",
    "ABCB4", "BEES3", "BEES4", "PINE4", "BNBR3", "BAZA3", "BMEB3", "BMEB4",
    "BMIN4", "RPAD3", "RPAD5", "RPAD6", "BSLI3", "BSLI4",
    # Insurers
    "BBSE3", "PSSA3", "CXSE3", "IRBR3", "WIZC3", "CSAB3", "CSAB4", "APER3",
    # Exchanges / financial services / payments / holdings
    "B3SA3", "CIEL3", "CASH3", "GETT3", "GETT11", "ITSA3", "ITSA4", "MODL11",
})


def db_path() -> str:
    """Return the slim DB path if it exists, else the full DB."""
    return SLIM_DB if Path(SLIM_DB).exists() else FULL_DB


def using_slim_db() -> bool:
    return Path(SLIM_DB).exists()


@st.cache_resource(show_spinner=False)
def get_orchestrator() -> StockAnalysisOrchestrator:
    """Create (once) the orchestrator bound to the dashboard database."""
    return StockAnalysisOrchestrator(db_path=db_path())


def _drop_known_financials(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "ticker" not in df.columns:
        return df
    mask = df["ticker"].isin(KNOWN_FINANCIALS)
    if "sector" in df.columns:
        mask = mask | df["sector"].apply(_is_financial)
    return df[~mask].reset_index(drop=True)


# ----------------------------------------------------------------------
# Metadata
# ----------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def db_summary() -> dict:
    return get_orchestrator().db.summary()


@st.cache_data(show_spinner=False)
def latest_snapshot_date() -> Optional[str]:
    orc = get_orchestrator()
    df = orc.db.query("SELECT MAX(snapshot_date) AS m FROM fundamental_snapshots")
    return None if df.empty else df.iloc[0, 0]


@st.cache_data(show_spinner=False)
def all_tickers() -> list[str]:
    return get_orchestrator().db.get_all_tickers()


# ----------------------------------------------------------------------
# Screens & rankings
# ----------------------------------------------------------------------
@st.cache_data(show_spinner="Computing intrinsic-value ranking…")
def intrinsic_value_ranking(
    top_n: int,
    min_margin_of_safety: Optional[float],
    exclude_financials: bool,
    min_liquidity: Optional[float],
) -> pd.DataFrame:
    df = get_orchestrator().get_intrinsic_value_ranking(
        top_n=0,
        min_margin_of_safety=min_margin_of_safety,
        exclude_financials=exclude_financials,
        min_liquidity=min_liquidity,
    )
    if exclude_financials:
        df = _drop_known_financials(df)
    return df.head(top_n) if top_n else df


@st.cache_data(show_spinner="Running Graham-Buffett screen…")
def master_screen(
    min_margin_of_safety: float,
    min_quality: float,
    min_growth: float,
    max_debt_equity: Optional[float],
    exclude_financials: bool,
    min_liquidity: Optional[float],
    top_n: int,
) -> pd.DataFrame:
    df = get_orchestrator().screen_graham_buffett(
        min_margin_of_safety=min_margin_of_safety,
        min_quality=min_quality,
        min_growth=min_growth,
        max_debt_equity=max_debt_equity,
        exclude_financials=exclude_financials,
        min_liquidity=min_liquidity,
        top_n=0,
    )
    if exclude_financials:
        df = _drop_known_financials(df)
    return df.head(top_n) if top_n else df


@st.cache_data(show_spinner="Running the Claude Screen…")
def claude_screen(
    weights: Optional[dict],
    roic_hurdle: float,
    exclude_financials: bool,
    min_liquidity: Optional[float],
    top_n: int,
) -> pd.DataFrame:
    df = get_orchestrator().screen_claude(
        weights=weights,
        roic_hurdle=roic_hurdle,
        exclude_financials=exclude_financials,
        min_liquidity=min_liquidity,
        top_n=0,
    )
    if exclude_financials:
        df = _drop_known_financials(df)
    return df.head(top_n) if top_n else df


@st.cache_data(show_spinner="Scoring every stock…")
def overall_scores(min_liquidity: Optional[float] = None) -> pd.DataFrame:
    """Universal 0–100 Overall Score for every stock in the latest snapshot."""
    return get_orchestrator().overall_scores(min_liquidity=min_liquidity)


@st.cache_data(show_spinner=False)
def overall_score_map(min_liquidity: Optional[float] = None) -> dict[str, float]:
    """Ticker → Overall Score (0–100) lookup, for attaching to any table."""
    df = overall_scores(min_liquidity=min_liquidity)
    if df.empty or "overall_score" not in df.columns:
        return {}
    return dict(zip(df["ticker"], df["overall_score"]))


@st.cache_data(show_spinner="Backtesting momentum…")
def momentum_backtest(
    n_quantiles: int = 3, min_dollar_vol: float = 5_000_000.0
) -> dict:
    """
    Run the walk-forward momentum backtest and return a JSON-friendly dict
    (``summary`` records, ``equity`` curve, ``params``) so Streamlit can cache it.
    Returns an empty dict when there is not enough price history.

    The backtest needs *breadth* (a wide universe and a long window) to be
    meaningful, so it deliberately reads the **full** local DB when present and
    only falls back to the slim DB when that is all that ships.
    """
    from brazil_stocks.analysis.backtest import MomentumBacktester
    from brazil_stocks.storage.database import DatabaseManager

    path = FULL_DB if Path(FULL_DB).exists() else SLIM_DB
    db = DatabaseManager(path)
    # Slim DB is large-cap-only, so relax the minimum-names gate there.
    min_names = 20 if path == FULL_DB else 12
    res = MomentumBacktester(
        db, n_quantiles=n_quantiles, min_dollar_vol=min_dollar_vol, min_names=min_names
    ).run()
    if res is None:
        return {}
    return {
        "summary": res.summary.reset_index(names="basket"),
        "equity": res.equity_curves.reset_index(),
        "params": {**res.params, "source": "full DB" if path == FULL_DB else "slim DB"},
        "headline": res.headline(),
        "top_label": res.top_label,
    }


@st.cache_data(show_spinner="Ranking by Z-score…")
def zscore_ranking(
    metric: str, score_type: str, top_n: int, ascending: bool
) -> pd.DataFrame:
    return get_orchestrator().get_zscore_ranking(
        metric=metric, score_type=score_type, top_n=top_n, ascending=ascending
    )


@st.cache_data(show_spinner="Building heatmap…")
def heatmap_data(metrics: list[str], score_type: str, top_n: int) -> pd.DataFrame:
    return get_orchestrator().get_heatmap_data(
        metrics=metrics, score_type=score_type, top_n=top_n
    )


@st.cache_data(show_spinner="Computing composite ranking…")
def composite_ranking(metrics: Optional[list[str]], score_type: str) -> pd.DataFrame:
    return get_orchestrator().get_composite_ranking(
        metrics=metrics, score_type=score_type
    )


@st.cache_data(show_spinner="Running GARP screen…")
def garp_screen(
    value_threshold: float, growth_threshold: float, score_type: str
) -> pd.DataFrame:
    return get_orchestrator().screen_quality_value(
        value_threshold=value_threshold,
        growth_threshold=growth_threshold,
        score_type=score_type,
        require_growth=False,
    )


@st.cache_data(show_spinner="Loading quality scores…")
def quality_table(exclude_financials: bool, min_liquidity: Optional[float]) -> pd.DataFrame:
    orc = get_orchestrator()
    snap = latest_snapshot_date()
    df = orc.db.query(
        """
        SELECT f.ticker, s.sector, f.price, f.roic, f.roe, f.gross_margin,
               f.net_margin, f.debt_equity, f.liquidity_2m,
               f.quality_score, f.moat_score
          FROM fundamental_snapshots f
          LEFT JOIN stocks s ON s.ticker = f.ticker
         WHERE f.snapshot_date = ? AND f.quality_score IS NOT NULL
        """,
        [snap],
    )
    if exclude_financials:
        df = _drop_known_financials(df)
    if min_liquidity:
        df = df[df["liquidity_2m"].fillna(0) >= min_liquidity]
    return df.sort_values("quality_score", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------
# Single-ticker
# ----------------------------------------------------------------------
@st.cache_data(show_spinner="Loading stock profile…")
def stock_profile(ticker: str) -> dict:
    return get_orchestrator().get_stock_profile(ticker)


@st.cache_data(show_spinner="Loading price history…")
def price_history(ticker: str) -> pd.DataFrame:
    return get_orchestrator().db.get_price_history(ticker)


@st.cache_data(show_spinner="Loading historical P/L…")
def historical_pl(ticker: str) -> pd.DataFrame:
    """Daily reconstructed trailing P/L rows stored as dated snapshots."""
    orc = get_orchestrator()
    return orc.db.query(
        """
        SELECT snapshot_date, pl
          FROM fundamental_snapshots
         WHERE ticker = ? AND pl IS NOT NULL
         ORDER BY snapshot_date
        """,
        [ticker],
    )


def live_dcf(ticker: str) -> dict:
    """Run an on-demand DCF for a single ticker (fetches FCF from yfinance).

    Not cached with ``st.cache_data`` because it performs live network I/O; the
    caller is expected to gate it behind a button.
    """
    orc = get_orchestrator()
    snap = latest_snapshot_date()
    row = orc.db.query(
        """
        SELECT price, debt_equity, book_value, revenue_growth_5y
          FROM fundamental_snapshots
         WHERE ticker = ? AND snapshot_date = ?
        """,
        [ticker, snap],
    )
    price = float(row["price"].iloc[0]) if not row.empty and pd.notna(row["price"].iloc[0]) else None

    fcf_ttm = orc.yf.fetch_fcf_ttm(ticker)
    info = orc.yf.fetch_info(ticker)
    shares = info.get("shares")
    fcf_per_share = (
        fcf_ttm / shares if fcf_ttm is not None and shares not in (None, 0) else None
    )

    de = row["debt_equity"].iloc[0] if not row.empty else None
    book = row["book_value"].iloc[0] if not row.empty else None
    net_debt = (
        (float(de) / 100.0) * float(book)
        if de is not None and book is not None and pd.notna(de) and pd.notna(book)
        else None
    )
    net_debt_per_share = (
        net_debt / shares if net_debt is not None and shares not in (None, 0) else None
    )

    growth_raw = row["revenue_growth_5y"].iloc[0] if not row.empty else None
    growth = (
        float(growth_raw) / 100.0
        if growth_raw is not None and pd.notna(growth_raw)
        else None
    )

    result = orc.dcf_valuator.value_share(
        ticker,
        fcf_per_share=fcf_per_share,
        price=price,
        growth_rate=growth,
        net_debt_per_share=net_debt_per_share,
    )
    return {
        "ticker": ticker,
        "price": price,
        "fcf_ttm": fcf_ttm,
        "shares": shares,
        "fcf_per_share": fcf_per_share,
        "net_debt_per_share": net_debt_per_share,
        "assumed_growth": result.assumed_growth,
        "discount_rate": result.discount_rate,
        "terminal_growth": result.terminal_growth,
        "enterprise_value": result.enterprise_value,
        "intrinsic_value": result.intrinsic_value,
        "margin_of_safety": result.margin_of_safety,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
    }
