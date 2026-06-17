"""
MetricsCalculator
=================
Reconstructs **historical** fundamental metrics from yfinance quarterly financials
+ daily price history already stored in the database.

Primary output
--------------
`compute_historical_metrics(ticker)` returns a DataFrame with columns:

    date, ticker, trailing_pl, trailing_ps

where:
- `trailing_pl`  = adjusted close price / trailing twelve-month (TTM) EPS
- `trailing_ps`  = market capitalisation per share / TTM revenue per share

These are stored back as FundamentalSnapshot rows with daily granularity so the
ZScoreAnalyzer can compute rolling time-series Z-scores.

Methodology
-----------
1. Fetch quarterly income statement from yfinance (net income, revenue, shares).
2. Build a TTM earnings series by summing the last 4 quarters at each date.
3. Compute EPS_ttm = TTM net income / shares outstanding.
4. Join with daily close price on a date index → P/E = price / EPS_ttm.
5. Similarly for P/S using TTM revenue per share.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import List, Optional

import numpy as np
import pandas as pd

from brazil_stocks.fetchers.yfinance_client import YFinanceFetcher
from brazil_stocks.models.schemas import FundamentalSnapshot
from brazil_stocks.storage.database import DatabaseManager

logger = logging.getLogger(__name__)


class MetricsCalculator:
    """
    Reconstruct historical P/L (P/E) and P/S time series.

    Parameters
    ----------
    db : DatabaseManager
        An open database manager used to read stored price history.
    yf_fetcher : YFinanceFetcher, optional
        Used to fetch quarterly financials. A default instance is created if None.
    min_quarters : int
        Minimum number of quarterly reports required to compute TTM. Default 4.
    """

    def __init__(
        self,
        db: DatabaseManager,
        yf_fetcher: Optional[YFinanceFetcher] = None,
        min_quarters: int = 4,
    ) -> None:
        self.db = db
        self.yf = yf_fetcher or YFinanceFetcher()
        self.min_quarters = min_quarters

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_historical_metrics(
        self, ticker: str
    ) -> pd.DataFrame:
        """
        Return a DataFrame of daily historical P/E and P/S for *ticker*.

        Columns: date, ticker, trailing_pl, trailing_ps

        Returns an empty DataFrame if insufficient data is available.
        """
        income, _ = self.yf.fetch_financials(ticker)
        if income.empty:
            logger.warning("%s: no quarterly income data — skipping historical metrics", ticker)
            return pd.DataFrame()

        prices = self.db.get_price_history(ticker)
        if prices.empty:
            logger.warning("%s: no price history in DB — run fetch_prices first", ticker)
            return pd.DataFrame()

        # ---- Build TTM series ----------------------------------------
        ttm_df = self._build_ttm(income)
        if ttm_df is None or ttm_df.empty:
            logger.warning("%s: insufficient quarters for TTM calculation", ticker)
            return pd.DataFrame()

        # ---- Merge with daily prices ----------------------------------
        prices["date"] = pd.to_datetime(prices["date"])
        prices = prices.set_index("date").sort_index()

        ttm_df.index = pd.to_datetime(ttm_df.index)
        ttm_df = ttm_df.sort_index()

        # Forward-fill quarterly TTM onto daily price index
        merged = prices[["close"]].join(ttm_df, how="left")
        merged[["ttm_eps", "ttm_rev_per_share"]] = merged[
            ["ttm_eps", "ttm_rev_per_share"]
        ].ffill()

        # Drop rows before the first quarterly report
        merged = merged.dropna(subset=["ttm_eps"])

        # ---- Compute ratios ------------------------------------------
        merged["trailing_pl"] = merged.apply(
            lambda r: _safe_divide(r["close"], r["ttm_eps"]), axis=1
        )
        merged["trailing_ps"] = merged.apply(
            lambda r: _safe_divide(r["close"], r["ttm_rev_per_share"]), axis=1
        )
        merged["ticker"] = ticker
        merged = merged.reset_index().rename(columns={"index": "date", "date": "date"})

        keep = ["date", "ticker", "trailing_pl", "trailing_ps", "ttm_eps", "ttm_rev_per_share"]
        result = merged[[c for c in keep if c in merged.columns]].copy()
        result["date"] = result["date"].dt.date
        logger.info(
            "%s: %d days of historical metrics computed", ticker, len(result)
        )
        return result

    def compute_and_store(self, tickers: List[str]) -> int:
        """
        Compute historical metrics for each ticker in *tickers* and persist
        back to the database as FundamentalSnapshot rows.

        Returns total number of rows stored.
        """
        total = 0
        for ticker in tickers:
            df = self.compute_historical_metrics(ticker)
            if df.empty:
                continue
            snapshots = self._df_to_snapshots(df)
            stored = self.db.upsert_fundamental_snapshots(snapshots)
            total += stored
            logger.debug("%s: stored %d historical metric rows", ticker, stored)
        logger.info("MetricsCalculator: stored %d rows total", total)
        return total

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_ttm(self, income: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        From quarterly income DataFrame (rows = periods, columns = metrics)
        compute a TTM (trailing 12-month) series at each quarterly date.

        Returns a DataFrame indexed by period date with columns:
            ttm_eps, ttm_rev_per_share
        """
        # Standardise column names (yfinance can vary between versions)
        col_map: dict = {}
        for col in income.columns:
            lc = str(col).lower()
            if "net income" in lc or "net_income" in lc:
                col_map[col] = "net_income"
            elif "total revenue" in lc or "total_revenue" in lc:
                col_map[col] = "revenue"
            elif "basic eps" in lc or "basic_eps" in lc:
                col_map[col] = "basic_eps"
            elif ("diluted eps" in lc or "diluted_eps" in lc) and "basic_eps" not in col_map.values():
                col_map[col] = "basic_eps"
            elif "shares" in lc and "basic" in lc:
                col_map[col] = "shares"

        income = income.rename(columns=col_map)
        # Drop duplicate columns that arose from the rename (keep first occurrence)
        income = income.loc[:, ~income.columns.duplicated()]
        income.index = pd.to_datetime(income.index)
        income = income.sort_index()

        has_eps = "basic_eps" in income.columns
        has_net_income = "net_income" in income.columns
        has_revenue = "revenue" in income.columns
        has_shares = "shares" in income.columns

        if not (has_eps or has_net_income) or not has_revenue:
            return None

        if len(income) < self.min_quarters:
            return None

        rows = []
        for i in range(self.min_quarters - 1, len(income)):
            window = income.iloc[i - (self.min_quarters - 1) : i + 1]
            period_date = income.index[i]

            if has_eps:
                ttm_eps = window["basic_eps"].sum()
            elif has_net_income and has_shares:
                ttm_ni = window["net_income"].sum()
                shares = window["shares"].iloc[-1]
                ttm_eps = ttm_ni / shares if shares and shares > 0 else np.nan
            elif has_net_income:
                # fallback: use net income as proxy (not per-share)
                ttm_eps = window["net_income"].sum()
            else:
                ttm_eps = np.nan

            ttm_rev = window["revenue"].sum()
            ttm_rev_per_share = (
                ttm_rev / window["shares"].iloc[-1]
                if has_shares and window["shares"].iloc[-1] > 0
                else ttm_rev  # store as absolute revenue if no shares
            )

            # Coerce to plain Python float to guard against accidental Series results
            def _to_scalar(v):
                if isinstance(v, pd.Series):
                    v = v.iloc[0] if not v.empty else np.nan
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return np.nan

            ttm_eps_scalar = _to_scalar(ttm_eps)
            ttm_rev_scalar = _to_scalar(ttm_rev_per_share)

            rows.append(
                {
                    "date": period_date,
                    "ttm_eps": ttm_eps_scalar if not np.isnan(ttm_eps_scalar) else np.nan,
                    "ttm_rev_per_share": ttm_rev_scalar,
                }
            )

        if not rows:
            return None

        df = pd.DataFrame(rows).set_index("date")
        return df

    @staticmethod
    def _df_to_snapshots(df: pd.DataFrame) -> list[FundamentalSnapshot]:
        snapshots = []
        for _, row in df.iterrows():
            pl = row.get("trailing_pl")
            ps = row.get("trailing_ps")
            eps = row.get("ttm_eps")
            rev = row.get("ttm_rev_per_share")
            # Only store if at least one metric is valid
            valid = lambda v: v is not None and not (isinstance(v, float) and np.isnan(v))
            if not any(valid(x) for x in (pl, ps, eps, rev)):
                continue
            snapshots.append(
                FundamentalSnapshot(
                    ticker=row["ticker"],
                    snapshot_date=row["date"] if isinstance(row["date"], date) else row["date"].date(),
                    pl=float(pl) if valid(pl) else None,
                    ps=float(ps) if valid(ps) else None,
                    eps_ttm=float(eps) if valid(eps) else None,
                    revenue_ttm=float(rev) if valid(rev) else None,
                )
            )
        return snapshots


def _safe_divide(numerator, denominator) -> Optional[float]:
    """Return numerator / denominator, or None on invalid/zero denominator."""
    if denominator is None or denominator == 0 or np.isnan(denominator):
        return None
    if numerator is None or np.isnan(numerator):
        return None
    result = numerator / denominator
    # Sanity: P/E > 0 and < 10000 to exclude nonsense values
    if result <= 0 or result > 10_000:
        return None
    return float(result)
