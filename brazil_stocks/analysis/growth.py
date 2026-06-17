"""
GrowthAnalyzer
==============
Quantifies earnings/revenue growth quality.

Inputs (all stored by other modules):
- ``fundamental_snapshots.eps_ttm`` / ``revenue_ttm`` — trailing-12-month series
  reconstructed by :class:`MetricsCalculator` from quarterly financials.
- ``fundamental_snapshots.revenue_growth_5y`` — 5-year revenue CAGR pulled
  directly from Fundamentus (already reported by the source).

Sub-metrics (per ticker, all may be None depending on data availability):

- ``eps_qoq``           : latest TTM EPS / previous TTM EPS - 1
- ``revenue_qoq``       : same for TTM revenue
- ``eps_yoy``           : 4-step (or earliest-to-latest if <5 points) growth
- ``eps_slope``         : OLS slope of TTM EPS, normalised by mean(|EPS|)
- ``positive_qtr_ratio``: share of TTM-EPS observations where the series rose
- ``revenue_growth_5y`` : passthrough of Fundamentus' 5-year revenue CAGR

The composite ``growth_score`` is the equally-weighted mean of the
cross-sectional Z-scores of whichever sub-metrics are available for each
ticker (skipna). Higher = stronger growth.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from brazil_stocks.models.schemas import ZScoreResult
from brazil_stocks.storage.database import DatabaseManager

logger = logging.getLogger(__name__)


GROWTH_METRICS = [
    "eps_qoq",
    "revenue_qoq",
    "eps_yoy",
    "eps_slope",
    "positive_qtr_ratio",
    "revenue_growth_5y",
]
COMPOSITE_METRIC = "growth_score"


class GrowthAnalyzer:
    """
    Parameters
    ----------
    db : DatabaseManager
    min_ttm_points : int
        Minimum distinct TTM change points required to compute any TTM-based
        sub-metric (default 2 — one QoQ comparison).
    lookback_points : int
        Window for slope & consistency calculations (default 8).
    winsorize_pct : float
        Tail clipping used when computing the cross-sectional Z-score.
    zscore_cap : float
        Hard cap on the magnitude of every Z-score.
    """

    def __init__(
        self,
        db: DatabaseManager,
        min_ttm_points: int = 2,
        lookback_points: int = 8,
        winsorize_pct: float = 0.05,
        zscore_cap: float = 5.0,
        min_metrics_for_composite: int = 4,
    ) -> None:
        self.db = db
        self.min_ttm_points = min_ttm_points
        self.lookback_points = lookback_points
        self.winsorize_pct = winsorize_pct
        self.zscore_cap = zscore_cap
        self.min_metrics_for_composite = min_metrics_for_composite

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_growth_metrics(self, tickers: List[str]) -> pd.DataFrame:
        rows: list[dict] = []
        for t in tickers:
            r = self._per_ticker(t)
            if r is not None:
                rows.append(r)
        if not rows:
            logger.warning("GrowthAnalyzer: no tickers had usable growth data")
            return pd.DataFrame(columns=["ticker", "snapshot_date", *GROWTH_METRICS])
        return pd.DataFrame(rows)

    def compute_and_store(
        self, tickers: List[str], snapshot_date: Optional[date] = None
    ) -> pd.DataFrame:
        raw = self.compute_growth_metrics(tickers)
        if raw.empty:
            return raw

        snap = snapshot_date or raw["snapshot_date"].max()

        zs: Dict[str, pd.Series] = {
            m: self._cross_sectional_z(raw[m]) for m in GROWTH_METRICS
        }
        merged = raw.copy()
        for m, s in zs.items():
            merged[f"{m}_z"] = s.values

        z_block = pd.concat([zs[m] for m in GROWTH_METRICS], axis=1)
        composite = z_block.mean(axis=1, skipna=True).clip(-self.zscore_cap, self.zscore_cap)
        non_null_counts = z_block.notna().sum(axis=1)
        composite = composite.where(non_null_counts >= self.min_metrics_for_composite, np.nan)
        merged[COMPOSITE_METRIC] = composite.values

        results: list[ZScoreResult] = []
        for _, row in merged.iterrows():
            for m in GROWTH_METRICS:
                results.append(
                    ZScoreResult(
                        ticker=row["ticker"],
                        snapshot_date=snap,
                        metric=m,
                        time_series_zscore=None,
                        cross_sectional_zscore=_to_opt_float(row[f"{m}_z"]),
                    )
                )
            results.append(
                ZScoreResult(
                    ticker=row["ticker"],
                    snapshot_date=snap,
                    metric=COMPOSITE_METRIC,
                    time_series_zscore=None,
                    cross_sectional_zscore=_to_opt_float(row[COMPOSITE_METRIC]),
                )
            )
        self.db.upsert_zscore_results(results)
        logger.info(
            "GrowthAnalyzer: stored %d growth z-score rows (%d tickers, snap=%s)",
            len(results), len(merged), snap,
        )
        return merged

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _per_ticker(self, ticker: str) -> Optional[dict]:
        df = self.db.query(
            """
            SELECT snapshot_date, eps_ttm, revenue_ttm, revenue_growth_5y
            FROM fundamental_snapshots
            WHERE ticker = ?
            ORDER BY snapshot_date
            """,
            [ticker],
        )
        if df.empty:
            return None

        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
        df = df.set_index("snapshot_date").sort_index()

        rev5y_series = df["revenue_growth_5y"].dropna()
        rev5y = float(rev5y_series.iloc[-1]) if not rev5y_series.empty else None

        ttm = df[["eps_ttm", "revenue_ttm"]].dropna(how="all").astype(float)

        if ttm.empty:
            if rev5y is None:
                return None
            return {
                "ticker": ticker,
                "snapshot_date": df.index[-1].date(),
                "eps_qoq": None, "revenue_qoq": None, "eps_yoy": None,
                "eps_slope": None, "positive_qtr_ratio": None,
                "revenue_growth_5y": rev5y,
            }

        sig = ttm.round(6)
        change_mask = (sig != sig.shift()).any(axis=1)
        q = ttm[change_mask]
        if len(q) < self.min_ttm_points and rev5y is None:
            return None

        eps = q["eps_ttm"].dropna()
        rev = q["revenue_ttm"].dropna()

        return {
            "ticker": ticker,
            "snapshot_date": q.index[-1].date(),
            "eps_qoq": _qoq(eps),
            "revenue_qoq": _qoq(rev),
            "eps_yoy": _yoy(eps),
            "eps_slope": _norm_slope(eps.tail(self.lookback_points)),
            "positive_qtr_ratio": _positive_qtr_ratio(eps.tail(self.lookback_points)),
            "revenue_growth_5y": rev5y,
        }

    def _cross_sectional_z(self, series: pd.Series) -> pd.Series:
        s = series.astype(float).copy()
        if s.dropna().empty:
            return pd.Series(np.nan, index=s.index)
        lo = s.quantile(self.winsorize_pct)
        hi = s.quantile(1.0 - self.winsorize_pct)
        sw = s.clip(lo, hi)
        mu, sd = sw.mean(), sw.std()
        if not sd or np.isnan(sd):
            return pd.Series(np.nan, index=s.index)
        z = (sw - mu) / sd
        return z.clip(-self.zscore_cap, self.zscore_cap)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _qoq(series: pd.Series) -> Optional[float]:
    s = series.dropna()
    if len(s) < 2:
        return None
    cur, prev = float(s.iloc[-1]), float(s.iloc[-2])
    if prev == 0 or np.isnan(prev):
        return None
    return cur / prev - 1.0


def _yoy(series: pd.Series) -> Optional[float]:
    s = series.dropna()
    if len(s) < 2:
        return None
    idx = -5 if len(s) >= 5 else 0
    cur, prev = float(s.iloc[-1]), float(s.iloc[idx])
    if prev == 0 or np.isnan(prev):
        return None
    return cur / prev - 1.0


def _norm_slope(series: pd.Series) -> Optional[float]:
    s = series.dropna()
    if len(s) < 3:
        return None
    x = np.arange(len(s), dtype=float)
    y = s.values.astype(float)
    try:
        slope = float(np.polyfit(x, y, 1)[0])
    except (np.linalg.LinAlgError, ValueError):
        return None
    scale = float(np.nanmean(np.abs(y)))
    if scale == 0 or np.isnan(scale):
        return None
    return slope / scale


def _positive_qtr_ratio(series: pd.Series) -> Optional[float]:
    s = series.dropna()
    if len(s) < 3:
        return None
    diffs = s.diff().dropna()
    if diffs.empty:
        return None
    return float((diffs > 0).sum() / len(diffs))


def _to_opt_float(v) -> Optional[float]:
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None
