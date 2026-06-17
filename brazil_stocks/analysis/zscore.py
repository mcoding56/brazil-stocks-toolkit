"""
ZScoreAnalyzer
==============
Computes two flavours of Z-scores on fundamental metrics stored in the database.

Time-series Z-score
-------------------
    z = (current_value - mean_over_window) / std_over_window

Answers: *Is this stock cheap relative to its own history?*
A negative Z-score means the metric (e.g. P/L) is lower than its own
historical average — the stock is trading at a relative discount.

Cross-sectional Z-score
-----------------------
    z = (stock_value - group_mean) / group_std

where *group* is either the entire market or the stock's sector.
Answers: *Is this stock cheap relative to peers right now?*
A negative Z-score means the stock is cheaper than the peer group median.

Both methods handle NaN values gracefully — stocks with insufficient
history are assigned NaN for the time-series score.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from brazil_stocks.models.schemas import ZScoreResult
from brazil_stocks.storage.database import DatabaseManager

logger = logging.getLogger(__name__)

# Metrics we will compute Z-scores for
FUNDAMENTAL_METRICS = [
    "pl", "pvp", "ev_ebitda", "ev_ebit", "p_ebit", "ps", "dy",
    "roe", "roic", "gross_margin", "ebit_margin", "net_margin",
    "debt_equity", "current_ratio",
]

# Valuation ratios that are only meaningful when positive.
# Negative P/E (loss-making) or negative EV/EBITDA distort the distribution;
# we filter to positive values before computing the reference distribution.
_POSITIVE_ONLY_METRICS = frozenset(["pl", "pvp", "ev_ebitda", "ev_ebit", "p_ebit", "ps", "dy"])


class ZScoreAnalyzer:
    """
    Compute and persist Z-scores for fundamental metrics.

    Parameters
    ----------
    db : DatabaseManager
    window_years : int
        Rolling window for time-series Z-score (default 5 years).
    min_observations : int
        Minimum number of distinct snapshot dates required before computing a
        time-series Z-score (default 4).
    """

    def __init__(
        self,
        db: DatabaseManager,
        window_years: int = 5,
        min_observations: int = 20,
        winsorize_pct: float = 0.05,
        zscore_cap: float = 5.0,
    ) -> None:
        self.db = db
        self.window_years = window_years
        self.min_observations = min_observations
        self.winsorize_pct = winsorize_pct   # clip to [p, 1-p] before computing stats
        self.zscore_cap = zscore_cap         # hard cap on final |z|

    # ------------------------------------------------------------------
    # High-level pipeline
    # ------------------------------------------------------------------

    def compute_all(
        self,
        snapshot_date: Optional[date] = None,
        metrics: Optional[List[str]] = None,
        group_by_sector: bool = False,
    ) -> List[ZScoreResult]:
        """
        Compute both time-series and cross-sectional Z-scores for all tickers
        on *snapshot_date* (defaults to the most recent available date).

        Parameters
        ----------
        snapshot_date   : date to compute scores for (default = latest in DB)
        metrics         : list of metric column names (default = all)
        group_by_sector : if True, cross-sectional z-score is within sector

        Returns a list of ZScoreResult objects which are also persisted to DB.
        """
        metrics = metrics or FUNDAMENTAL_METRICS
        snapshot_date = snapshot_date or self._latest_snapshot_date()
        if snapshot_date is None:
            logger.warning("ZScoreAnalyzer: no fundamental snapshots found in DB.")
            return []

        # --- Load data -------------------------------------------------
        snap_df = self._load_snapshot(snapshot_date)
        if snap_df.empty:
            logger.warning(
                "ZScoreAnalyzer: no data for snapshot_date=%s", snapshot_date
            )
            return []

        ts_scores = self._compute_time_series_scores(snap_df, metrics)
        cs_scores = self._compute_cross_sectional_scores(
            snap_df, metrics, group_by_sector=group_by_sector
        )

        # --- Merge results --------------------------------------------
        results = self._merge_scores(
            snap_df, ts_scores, cs_scores, snapshot_date, metrics
        )

        # --- Persist --------------------------------------------------
        self.db.upsert_zscore_results(results)
        logger.info(
            "ZScoreAnalyzer: computed %d Z-score results for %s",
            len(results),
            snapshot_date,
        )
        return results

    # ------------------------------------------------------------------
    # Time-series Z-scores
    # ------------------------------------------------------------------

    def time_series_zscore(
        self, ticker: str, metric: str, as_of: Optional[date] = None
    ) -> Optional[float]:
        """
        Return the time-series Z-score for a single ticker/metric pair.

        Parameters
        ----------
        ticker  : B3 ticker (plain, without .SA)
        metric  : column name, e.g. ``"pl"``
        as_of   : reference date (default = today)
        """
        as_of = as_of or date.today()
        start = as_of - timedelta(days=int(self.window_years * 365.25))

        df = self.db.get_fundamental_snapshots(
            ticker=ticker,
            end_date=as_of.isoformat(),
            start_date=start.isoformat(),
        )
        if df.empty or metric not in df.columns:
            return None
        series = df[metric].dropna()
        if len(series) < self.min_observations:
            return None
        current = series.iloc[-1]
        return _zscore(current, series.mean(), series.std())

    # ------------------------------------------------------------------
    # Cross-sectional Z-scores
    # ------------------------------------------------------------------

    def cross_sectional_zscore(
        self,
        ticker: str,
        metric: str,
        snapshot_date: Optional[date] = None,
        sector_df: Optional[pd.DataFrame] = None,
    ) -> Optional[float]:
        """
        Return the cross-sectional Z-score for a ticker/metric on a given date.

        Parameters
        ----------
        ticker        : B3 ticker
        metric        : column name, e.g. ``"ev_ebitda"``
        snapshot_date : date (default = most recent in DB)
        sector_df     : optional pre-loaded snapshot DataFrame to avoid a DB round-trip
        """
        snap_date = snapshot_date or self._latest_snapshot_date()
        if snap_date is None:
            return None
        df = sector_df if sector_df is not None else self._load_snapshot(snap_date)
        if df.empty or metric not in df.columns:
            return None

        series = df[metric].dropna()
        row = df[df["ticker"] == ticker]
        if row.empty or pd.isna(row.iloc[0][metric]):
            return None
        current = row.iloc[0][metric]
        return _zscore(current, series.mean(), series.std())

    # ------------------------------------------------------------------
    # Scoring summary / ranking helpers
    # ------------------------------------------------------------------

    def get_ranking(
        self,
        metric: str,
        snapshot_date: Optional[str] = None,
        score_type: str = "time_series_zscore",
        ascending: bool = True,
    ) -> pd.DataFrame:
        """
        Return a DataFrame of tickers ranked by a Z-score for a given metric.

        Parameters
        ----------
        metric        : e.g. ``"pl"``
        snapshot_date : ISO date string (default = latest in DB)
        score_type    : ``"time_series_zscore"`` or ``"cross_sectional_zscore"``
        ascending     : True = cheapest first (most negative Z first)
        """
        snap_date = snapshot_date or (
            self._latest_snapshot_date().isoformat()
            if self._latest_snapshot_date()
            else None
        )
        df = self.db.get_zscore_results(snapshot_date=snap_date, metric=metric)
        if df.empty:
            return df
        return (
            df[["ticker", "metric", score_type]]
            .dropna(subset=[score_type])
            .sort_values(score_type, ascending=ascending)
            .reset_index(drop=True)
        )

    def get_composite_score(
        self,
        snapshot_date: Optional[str] = None,
        metrics: Optional[List[str]] = None,
        score_type: str = "time_series_zscore",
    ) -> pd.DataFrame:
        """
        Compute a composite Z-score per ticker by averaging individual metric Z-scores.

        Returns a DataFrame sorted by composite score ascending (cheapest first).
        """
        metrics = metrics or ["pl", "pvp", "ev_ebitda"]
        snap_date = snapshot_date or (
            self._latest_snapshot_date().isoformat()
            if self._latest_snapshot_date()
            else None
        )
        df = self.db.get_zscore_results(snapshot_date=snap_date)
        if df.empty:
            return df

        df = df[df["metric"].isin(metrics)][["ticker", "metric", score_type]]
        pivot = df.pivot_table(
            index="ticker", columns="metric", values=score_type, aggfunc="first"
        )
        pivot["composite_zscore"] = pivot.mean(axis=1)
        return pivot.sort_values("composite_zscore").reset_index()

    def get_zscore_heatmap_data(
        self,
        snapshot_date: Optional[str] = None,
        metrics: Optional[List[str]] = None,
        score_type: str = "time_series_zscore",
        top_n: int = 50,
    ) -> pd.DataFrame:
        """
        Return a pivot table (tickers × metrics) of Z-scores, suitable for heatmap plotting.

        Rows are sorted by composite Z-score ascending (cheapest overall first).
        """
        metrics = metrics or FUNDAMENTAL_METRICS
        snap_date = snapshot_date or (
            self._latest_snapshot_date().isoformat()
            if self._latest_snapshot_date()
            else None
        )
        df = self.db.get_zscore_results(snapshot_date=snap_date)
        if df.empty:
            return df

        df = df[df["metric"].isin(metrics)][["ticker", "metric", score_type]]
        pivot = df.pivot_table(
            index="ticker", columns="metric", values=score_type, aggfunc="first"
        )
        # Sort by composite score
        pivot["_composite"] = pivot.mean(axis=1)
        pivot = pivot.sort_values("_composite").drop(columns=["_composite"])

        return pivot.head(top_n)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _latest_snapshot_date(self) -> Optional[date]:
        df = self.db.query(
            "SELECT MAX(snapshot_date) AS latest FROM fundamental_snapshots"
        )
        val = df.iloc[0]["latest"]
        if val is None:
            return None
        return date.fromisoformat(val)

    def _load_snapshot(self, snapshot_date: date) -> pd.DataFrame:
        """Load the fundamental snapshot for *snapshot_date* (or nearest earlier date)."""
        iso = snapshot_date.isoformat() if isinstance(snapshot_date, date) else snapshot_date
        df = self.db.get_fundamental_snapshots(end_date=iso)
        if df.empty:
            return df
        # Keep only the latest record per ticker up to snapshot_date
        df = df.sort_values("snapshot_date")
        df = df.groupby("ticker", as_index=False).last()
        return df

    def _compute_time_series_scores(
        self, snap_df: pd.DataFrame, metrics: List[str]
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """
        Returns {metric: {ticker: zscore}} for time-series method.
        """
        result: Dict[str, Dict[str, Optional[float]]] = {m: {} for m in metrics}
        tickers = snap_df["ticker"].tolist()

        start_date = (
            date.today() - timedelta(days=int(self.window_years * 365.25))
        ).isoformat()
        end_date = date.today().isoformat()

        # Bulk load all snapshots for the window (more efficient than per-ticker queries)
        history = self.db.get_fundamental_snapshots(
            start_date=start_date, end_date=end_date
        )
        if history.empty:
            return result

        for metric in metrics:
            if metric not in history.columns:
                continue
            grouped = history[["ticker", metric]].dropna(subset=[metric]).groupby("ticker")
            for ticker in tickers:
                if ticker not in grouped.groups:
                    result[metric][ticker] = None
                    continue
                series = grouped.get_group(ticker)[metric]

                # Valuation ratios are only meaningful when positive
                if metric in _POSITIVE_ONLY_METRICS:
                    series = series[series > 0]

                if len(series) < self.min_observations:
                    result[metric][ticker] = None
                    continue

                current_row = snap_df[snap_df["ticker"] == ticker]
                if current_row.empty or pd.isna(current_row.iloc[0].get(metric)):
                    result[metric][ticker] = None
                    continue
                current = current_row.iloc[0][metric]

                # Winsorize the reference distribution to suppress historical outliers
                lo = series.quantile(self.winsorize_pct)
                hi = series.quantile(1.0 - self.winsorize_pct)
                series_w = series.clip(lo, hi)
                z = _zscore(current, series_w.mean(), series_w.std())
                if z is not None:
                    z = max(-self.zscore_cap, min(self.zscore_cap, z))
                result[metric][ticker] = z
        return result

    def _compute_cross_sectional_scores(
        self,
        snap_df: pd.DataFrame,
        metrics: List[str],
        group_by_sector: bool = False,
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """
        Returns {metric: {ticker: zscore}} for cross-sectional method.
        """
        result: Dict[str, Dict[str, Optional[float]]] = {m: {} for m in metrics}
        tickers = snap_df["ticker"].tolist()

        for metric in metrics:
            if metric not in snap_df.columns:
                continue
            col = snap_df[[" ticker" if " ticker" in snap_df.columns else "ticker", metric]].copy()
            col.columns = ["ticker", "value"]
            col = col.dropna(subset=["value"])

            # Valuation ratios: only use positive values for the reference distribution
            if metric in _POSITIVE_ONLY_METRICS:
                col = col[col["value"] > 0]

            if group_by_sector and "sector" in snap_df.columns:
                # Merge sector info
                col = col.merge(snap_df[["ticker", "sector"]], on="ticker", how="left")
                for ticker in tickers:
                    row = snap_df[snap_df["ticker"] == ticker]
                    if row.empty or pd.isna(row.iloc[0].get(metric)):
                        result[metric][ticker] = None
                        continue
                    sector = row.iloc[0].get("sector", "")
                    group_vals = col[col["sector"] == sector]["value"] if sector else col["value"]
                    lo = group_vals.quantile(self.winsorize_pct)
                    hi = group_vals.quantile(1.0 - self.winsorize_pct)
                    group_w = group_vals.clip(lo, hi)
                    current = row.iloc[0][metric]
                    z = _zscore(current, group_w.mean(), group_w.std())
                    if z is not None:
                        z = max(-self.zscore_cap, min(self.zscore_cap, z))
                    result[metric][ticker] = z
            else:
                lo = col["value"].quantile(self.winsorize_pct)
                hi = col["value"].quantile(1.0 - self.winsorize_pct)
                col_w = col["value"].clip(lo, hi)
                mu = col_w.mean()
                sigma = col_w.std()
                for ticker in tickers:
                    row = snap_df[snap_df["ticker"] == ticker]
                    if row.empty or pd.isna(row.iloc[0].get(metric)):
                        result[metric][ticker] = None
                        continue
                    current = row.iloc[0][metric]
                    z = _zscore(current, mu, sigma)
                    if z is not None:
                        z = max(-self.zscore_cap, min(self.zscore_cap, z))
                    result[metric][ticker] = z
        return result

    def _merge_scores(
        self,
        snap_df: pd.DataFrame,
        ts_scores: Dict,
        cs_scores: Dict,
        snapshot_date: date,
        metrics: List[str],
    ) -> List[ZScoreResult]:
        results = []
        for metric in metrics:
            ts = ts_scores.get(metric, {})
            cs = cs_scores.get(metric, {})
            all_tickers = set(ts.keys()) | set(cs.keys())
            for ticker in all_tickers:
                results.append(
                    ZScoreResult(
                        ticker=ticker,
                        snapshot_date=snapshot_date,
                        metric=metric,
                        time_series_zscore=ts.get(ticker),
                        cross_sectional_zscore=cs.get(ticker),
                        window_years=self.window_years,
                    )
                )
        return results


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def _zscore(value: float, mu: float, sigma: float) -> Optional[float]:
    """Return (value - mu) / sigma, or None if sigma is ~zero."""
    if sigma is None or np.isnan(sigma) or sigma < 1e-10:
        return None
    if value is None or np.isnan(value):
        return None
    if mu is None or np.isnan(mu):
        return None
    return float((value - mu) / sigma)
