"""
MomentumBacktester
==================
A **walk-forward, point-in-time** backtest of the cross-sectional momentum
factor on the B3 universe, computed purely from the daily ``price_history``
already stored in the database — no extra network calls, no look-ahead.

Why this module exists
----------------------
The rest of the toolkit *ranks* stocks (value, quality, momentum) but has never
*validated* that any signal predicts forward returns. This closes that loop for
the one signal that can be tested honestly:

* **Fundamentals are a single current snapshot** — there is no point-in-time
  fundamentals history in the DB, so a value/quality backtest would silently use
  *today's* financials to "predict" the past (look-ahead bias). We deliberately
  do **not** do that.
* **Momentum is pure price history**, so it *can* be reconstructed at every past
  date with zero look-ahead. That makes it the only factor we can defensibly
  backtest, and it directly validates the 20%-weight momentum pillar added to
  the Claude Screen.

Method (deliberately conservative)
----------------------------------
1. Build a wide close-price panel (date × ticker) from ``price_history``.
2. Walk forward in **non-overlapping** holding periods (default ~1 month).
3. At each formation date *t*, rank the cross-section by the same 12-1 momentum
   used live: ``close[t-21] / close[t-252-21] - 1`` (skip the last month to dodge
   short-term reversal). Only names with enough history **and** a trailing
   liquidity floor at *t* are eligible — no microcap mirage.
4. Sort eligible names into quantile baskets, equal-weighted.
5. Forward return over the *next* holding period is ``close[t+h] / close[t] - 1``.
6. Chain period returns into equity curves and report CAGR, annualised vol,
   Sharpe, max drawdown and hit-rate for every basket, the equal-weight universe
   benchmark, and the long-short (top-minus-bottom) spread.

Survivorship note: the panel is whatever the DB holds today, so delisted names
may be under-represented. Treat absolute numbers as indicative and the
*top-vs-bottom spread* as the real evidence the factor carries information.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from brazil_stocks.storage.database import DatabaseManager

logger = logging.getLogger(__name__)

# Trading-day windows (≈ 21 trading days per calendar month).
_DAYS_1M = 21
_DAYS_12M = 252


@dataclass
class BacktestResult:
    """Container for a momentum backtest run."""

    equity_curves: pd.DataFrame      # date-indexed, one column per basket + Universe + LongShort
    period_returns: pd.DataFrame     # per-rebalance returns, same columns
    summary: pd.DataFrame            # one row per basket: CAGR, Vol, Sharpe, MaxDD, HitRate, Periods
    params: dict                     # the run configuration (for reproducibility)

    @property
    def top_label(self) -> str:
        """Column name of the highest-momentum basket (e.g. ``'Q5'``)."""
        return f"Q{self.params['n_quantiles']}"

    def headline(self) -> str:
        """One-line human summary of the long-short spread and top-basket Sharpe."""
        s = self.summary
        ls = s.loc["LongShort"] if "LongShort" in s.index else None
        top = s.loc[self.top_label]
        uni = s.loc["Universe"]
        msg = (
            f"Top basket {self.top_label}: CAGR {top['CAGR']:.1%}, "
            f"Sharpe {top['Sharpe']:.2f} vs Universe CAGR {uni['CAGR']:.1%}, "
            f"Sharpe {uni['Sharpe']:.2f}."
        )
        if ls is not None:
            msg += f" Long-short spread: CAGR {ls['CAGR']:.1%}, Sharpe {ls['Sharpe']:.2f}."
        return msg


class MomentumBacktester:
    """
    Walk-forward backtest of cross-sectional 12-1 momentum on stored prices.

    Parameters
    ----------
    db : DatabaseManager
        Open database manager used to read ``price_history``.
    lookback : int
        Total momentum look-back in trading days (default 252 ≈ 12 months).
    skip : int
        Most-recent days skipped to avoid short-term reversal (default 21 ≈ 1 month).
    hold : int
        Holding period in trading days between non-overlapping rebalances
        (default 21 ≈ 1 month).
    n_quantiles : int
        Number of equal-count baskets to sort the cross-section into (default 5).
    min_names : int
        Minimum eligible names required at a formation date to trade it.
    min_price : float
        Drop penny stocks priced below this at formation (default R$1).
    min_dollar_vol : float
        Trailing-median daily traded value (price × volume) floor at formation
        (default R$1M/day) so the backtest only trades liquid names.
    liquidity_window : int
        Trailing window (trading days) for the median dollar-volume estimate.
    """

    def __init__(
        self,
        db: DatabaseManager,
        lookback: int = _DAYS_12M,
        skip: int = _DAYS_1M,
        hold: int = _DAYS_1M,
        n_quantiles: int = 5,
        min_names: int = 20,
        min_price: float = 1.0,
        min_dollar_vol: float = 1_000_000.0,
        liquidity_window: int = _DAYS_1M,
    ) -> None:
        self.db = db
        self.lookback = lookback
        self.skip = skip
        self.hold = hold
        self.n_quantiles = n_quantiles
        self.min_names = min_names
        self.min_price = min_price
        self.min_dollar_vol = min_dollar_vol
        self.liquidity_window = liquidity_window

    # ------------------------------------------------------------------ #
    # Data loading                                                       #
    # ------------------------------------------------------------------ #
    def _load_panels(
        self, tickers: Optional[List[str]] = None
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Return ``(close, dollar_vol)`` wide panels indexed by date with one
        column per ticker. ``dollar_vol`` is the daily traded value (close ×
        volume) used for the liquidity gate.
        """
        sql = "SELECT ticker, date, close, volume FROM price_history"
        params: list = []
        if tickers:
            placeholders = ",".join("?" for _ in tickers)
            sql += f" WHERE ticker IN ({placeholders})"
            params = list(tickers)
        sql += " ORDER BY date"
        raw = self.db.query(sql, params)
        if raw.empty:
            return pd.DataFrame(), pd.DataFrame()

        raw["date"] = pd.to_datetime(raw["date"])
        raw["dollar_vol"] = raw["close"] * raw["volume"]
        close = raw.pivot_table(index="date", columns="ticker", values="close")
        dvol = raw.pivot_table(index="date", columns="ticker", values="dollar_vol")
        close = close.sort_index()
        dvol = dvol.sort_index()
        return close, dvol

    # ------------------------------------------------------------------ #
    # Core walk-forward loop                                             #
    # ------------------------------------------------------------------ #
    def run(
        self,
        tickers: Optional[List[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Optional[BacktestResult]:
        """
        Execute the backtest. Returns ``None`` if there is not enough history to
        form a single rebalance.
        """
        close, dvol = self._load_panels(tickers)
        if close.empty:
            logger.warning("No price history available for backtest.")
            return None

        if start:
            close = close.loc[close.index >= pd.to_datetime(start)]
            dvol = dvol.loc[dvol.index >= pd.to_datetime(start)]
        if end:
            close = close.loc[close.index <= pd.to_datetime(end)]
            dvol = dvol.loc[dvol.index <= pd.to_datetime(end)]

        dates = close.index
        first_form = self.lookback + self.skip   # need this much history to score momentum
        if len(dates) <= first_form + self.hold:
            logger.warning("Not enough history for a single rebalance.")
            return None

        q_labels = [f"Q{i}" for i in range(1, self.n_quantiles + 1)]
        period_rows: list[dict] = []
        period_dates: list[pd.Timestamp] = []

        i = first_form
        last_i = len(dates) - self.hold - 1
        while i <= last_i:
            form_date = dates[i]

            # 12-1 momentum at the formation date (no look-ahead).
            p_recent = close.iloc[i - self.skip]
            p_old = close.iloc[i - self.skip - self.lookback]
            momentum = p_recent / p_old - 1.0

            # Liquidity & price gates at formation.
            window = dvol.iloc[max(0, i - self.liquidity_window) : i]
            med_dvol = window.median()
            price_now = close.iloc[i]
            eligible = (
                momentum.notna()
                & price_now.notna()
                & (price_now >= self.min_price)
                & (med_dvol >= self.min_dollar_vol)
            )

            # Forward return must exist over the whole holding period.
            fwd = close.iloc[i + self.hold] / close.iloc[i] - 1.0
            eligible &= fwd.notna()

            names = momentum.index[eligible]
            if len(names) < self.min_names:
                i += self.hold
                continue

            mom = momentum[names]
            ret = fwd[names]

            # Equal-count quantile baskets (1 = lowest momentum … N = highest).
            try:
                buckets = pd.qcut(mom, self.n_quantiles, labels=q_labels)
            except ValueError:
                # Ties collapse the bins — fall back to rank-based slicing.
                ranks = mom.rank(method="first")
                buckets = pd.qcut(ranks, self.n_quantiles, labels=q_labels)

            row: dict = {}
            for q in q_labels:
                members = buckets.index[buckets == q]
                row[q] = float(ret[members].mean()) if len(members) else np.nan
            row["Universe"] = float(ret.mean())
            row["LongShort"] = row[q_labels[-1]] - row[q_labels[0]]

            period_rows.append(row)
            period_dates.append(dates[i + self.hold])
            i += self.hold

        if not period_rows:
            logger.warning("No tradable rebalances produced.")
            return None

        cols = q_labels + ["Universe", "LongShort"]
        period_returns = pd.DataFrame(period_rows, index=pd.Index(period_dates, name="date"))[cols]

        # Equity curves start at 1.0 one period before the first realised return.
        equity = (1.0 + period_returns).cumprod()

        periods_per_year = _DAYS_12M / self.hold
        summary = self._summarise(period_returns, equity, periods_per_year)

        params = {
            "lookback": self.lookback,
            "skip": self.skip,
            "hold": self.hold,
            "n_quantiles": self.n_quantiles,
            "min_names": self.min_names,
            "min_price": self.min_price,
            "min_dollar_vol": self.min_dollar_vol,
            "liquidity_window": self.liquidity_window,
            "n_periods": len(period_returns),
            "start": str(period_returns.index.min().date()),
            "end": str(period_returns.index.max().date()),
            "universe_size": close.shape[1],
        }
        return BacktestResult(
            equity_curves=equity,
            period_returns=period_returns,
            summary=summary,
            params=params,
        )

    # ------------------------------------------------------------------ #
    # Performance statistics                                             #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _summarise(
        period_returns: pd.DataFrame,
        equity: pd.DataFrame,
        periods_per_year: float,
    ) -> pd.DataFrame:
        rows = {}
        for col in period_returns.columns:
            r = period_returns[col].dropna()
            curve = equity[col].dropna()
            if r.empty or curve.empty:
                continue
            n = len(r)
            total_growth = float(curve.iloc[-1])
            years = n / periods_per_year
            cagr = total_growth ** (1.0 / years) - 1.0 if years > 0 and total_growth > 0 else np.nan
            vol = float(r.std(ddof=1) * np.sqrt(periods_per_year)) if n > 1 else np.nan
            mean_ann = float(r.mean() * periods_per_year)
            sharpe = mean_ann / vol if vol and not np.isnan(vol) and vol > 0 else np.nan
            # Max drawdown on the equity curve.
            running_max = curve.cummax()
            drawdown = curve / running_max - 1.0
            max_dd = float(drawdown.min())
            hit_rate = float((r > 0).mean())
            rows[col] = {
                "CAGR": cagr,
                "Vol": vol,
                "Sharpe": sharpe,
                "MaxDD": max_dd,
                "HitRate": hit_rate,
                "Periods": n,
            }
        return pd.DataFrame(rows).T[["CAGR", "Vol", "Sharpe", "MaxDD", "HitRate", "Periods"]]
