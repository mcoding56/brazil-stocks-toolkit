"""
FactorAnalyzer
==============
Price-based **factor** signals computed purely from the daily ``price_history``
already stored in the database — no extra network calls.

Why this module exists
----------------------
The rest of the toolkit is a *value + quality* engine (Graham/Buffett/Damodaran).
Decades of cross-market evidence (Jegadeesh-Titman 1993; Asness, Moskowitz &
Pedersen "Value and Momentum Everywhere", 2013; Frazzini-Pedersen "Betting
Against Beta", 2014) show that two price-based factors add return *on top of*
value and quality, and — crucially — are **negatively correlated with value**,
so combining them raises risk-adjusted returns far more than any single sleeve:

* **Momentum** — the 12-month return skipping the most recent month
  (``momentum_12_1``). The single most robust standalone anomaly; the skipped
  month avoids the well-documented short-term reversal.
* **Low volatility** — trailing realised volatility (``volatility_6m``). Low-vol
  stocks deliver higher risk-adjusted returns (the "low-volatility anomaly").

We also surface ``dist_52w_high`` (price ÷ trailing 52-week high), a simple,
powerful momentum proxy (George-Hwang 2004).

All signals are derived from data the system already owns, so this is the
highest-leverage upgrade available without any new data source.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import List, Optional

import numpy as np
import pandas as pd

from brazil_stocks.models.schemas import FundamentalSnapshot
from brazil_stocks.storage.database import DatabaseManager

logger = logging.getLogger(__name__)

# Trading-day windows (≈ 21 trading days per calendar month).
_DAYS_1M = 21
_DAYS_6M = 126
_DAYS_12M = 252
_DAYS_52W = 252

# Minimum bars required before a factor is trustworthy.
_MIN_BARS_MOMENTUM = 200   # need ~10 months for a 12-1 momentum read
_MIN_BARS_VOL = 60         # need ~3 months for a stable vol estimate


class FactorAnalyzer:
    """
    Compute price-based factor signals (momentum, low-volatility) from stored
    daily price history.

    Parameters
    ----------
    db : DatabaseManager
        Open database manager used to read ``price_history`` and write the
        computed factors back onto the latest ``fundamental_snapshots`` row.
    trading_days_year : int
        Trading days per year used to annualise volatility. Default 252.
    """

    def __init__(self, db: DatabaseManager, trading_days_year: int = 252) -> None:
        self.db = db
        self.trading_days_year = trading_days_year

    # ------------------------------------------------------------------ #
    # Core computation (per ticker)                                      #
    # ------------------------------------------------------------------ #
    def compute_factors(self, ticker: str) -> dict:
        """
        Return a dict of price-based factors for *ticker*, using whatever price
        history is available. Missing/insufficient data yields ``None`` values
        rather than raising.
        """
        out: dict = {
            "ticker": ticker,
            "momentum_12_1": None,
            "momentum_6_1": None,
            "volatility_6m": None,
            "dist_52w_high": None,
        }
        prices = self.db.get_price_history(ticker)
        if prices.empty or "close" not in prices.columns:
            return out

        close = pd.to_numeric(prices["close"], errors="coerce").dropna()
        if close.empty:
            return out
        close = close.reset_index(drop=True)
        n = len(close)
        last = float(close.iloc[-1])
        if last <= 0:
            return out

        # --- Momentum: total return over a window, skipping the last month ---
        if n >= _MIN_BARS_MOMENTUM and n > _DAYS_12M:
            p_start = float(close.iloc[-(_DAYS_12M + 1)])
            p_skip = float(close.iloc[-(_DAYS_1M + 1)])
            if p_start > 0:
                out["momentum_12_1"] = p_skip / p_start - 1.0
        if n > _DAYS_6M + _DAYS_1M:
            p_start6 = float(close.iloc[-(_DAYS_6M + 1)])
            p_skip = float(close.iloc[-(_DAYS_1M + 1)])
            if p_start6 > 0:
                out["momentum_6_1"] = p_skip / p_start6 - 1.0

        # --- Low-volatility: annualised std of daily log returns (trailing 6m) ---
        if n >= _MIN_BARS_VOL:
            window = close.iloc[-_DAYS_6M:] if n > _DAYS_6M else close
            rets = np.log(window / window.shift(1)).dropna()
            if len(rets) >= 20:
                out["volatility_6m"] = float(rets.std() * np.sqrt(self.trading_days_year))

        # --- Distance from the trailing 52-week high (1.0 = at the high) ---
        window52 = close.iloc[-_DAYS_52W:] if n > _DAYS_52W else close
        high52 = float(window52.max())
        if high52 > 0:
            out["dist_52w_high"] = last / high52

        return out

    # ------------------------------------------------------------------ #
    # Batch                                                              #
    # ------------------------------------------------------------------ #
    def compute_all(self, tickers: Optional[List[str]] = None) -> pd.DataFrame:
        """Compute factors for *tickers* (default: all in the DB). Never raises
        for an individual ticker."""
        if tickers is None:
            tickers = self.db.get_all_tickers()
        rows = []
        for tkr in tickers:
            try:
                rows.append(self.compute_factors(tkr))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Factor computation failed for %s: %s", tkr, exc)
                rows.append({"ticker": tkr})
        return pd.DataFrame(rows)

    def compute_and_store(
        self,
        tickers: Optional[List[str]] = None,
        snapshot_date: Optional[date] = None,
    ) -> int:
        """
        Compute price factors and persist them onto the latest fundamental
        snapshot for each ticker. Returns the number of tickers with at least
        one non-null factor stored.
        """
        df = self.compute_all(tickers)
        if df.empty:
            return 0

        if snapshot_date is None:
            snap = self.db.query(
                "SELECT MAX(snapshot_date) AS m FROM fundamental_snapshots"
            )
            snap_str = None if snap.empty else snap.iloc[0, 0]
            if snap_str is None:
                return 0
            snapshot_date = date.fromisoformat(snap_str)

        factor_cols = ["momentum_12_1", "momentum_6_1", "volatility_6m", "dist_52w_high"]
        snapshots: List[FundamentalSnapshot] = []
        for _, r in df.iterrows():
            values = {c: _clean(r.get(c)) for c in factor_cols}
            if all(v is None for v in values.values()):
                continue
            snapshots.append(
                FundamentalSnapshot(
                    ticker=r["ticker"], snapshot_date=snapshot_date, **values
                )
            )
        if not snapshots:
            return 0
        self.db.upsert_fundamental_snapshots(snapshots)
        logger.info("Stored price factors for %d tickers", len(snapshots))
        return len(snapshots)


def _clean(value) -> Optional[float]:
    """Coerce to float, returning None for missing/NaN/inf."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(f) or np.isinf(f):
        return None
    return f
