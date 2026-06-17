"""
QualityScorer
=============
Composite business-quality and competitive-advantage ("moat") scoring, inspired
by Warren Buffett and Bruce Greenwald: durable franchises earn high returns on
capital, defend wide and stable margins, and carry little debt.

Scores
------
quality_score (0-1)
    Overall business quality. Blends profitability (ROIC, ROE), margins
    (gross, EBIT, net), leverage (low net-debt/equity is better) and liquidity
    (current ratio).

moat_score (0-1)
    A narrower proxy for a durable competitive advantage, weighting the signals
    most associated with pricing power and capital efficiency: high ROIC, high
    and stable gross margin, and low leverage.

Method
------
Each component is converted to a cross-sectional **percentile rank** within the
chosen peer group (whole market, or sector when ``sector_neutral=True``). Percentile
ranking is scale-invariant, so it is robust to whether the source reports a metric
as a percentage (e.g. ``18.0``) or a decimal (e.g. ``0.18``). "Lower is better"
metrics (net-debt/equity) are inverted before ranking. The component ranks are
then averaged with configurable weights into the final 0-1 scores.

Stocks missing a component simply contribute fewer inputs to their own average;
a stock with too few available components receives ``None``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from brazil_stocks.storage.database import DatabaseManager

logger = logging.getLogger(__name__)

# Component weights for the overall quality score.
# "invert" → lower raw value is better (ranked after sign flip).
QUALITY_WEIGHTS: Dict[str, float] = {
    "roic": 0.25,
    "roe": 0.15,
    "gross_margin": 0.15,
    "ebit_margin": 0.10,
    "net_margin": 0.15,
    "debt_equity": 0.12,        # inverted
    "current_ratio": 0.08,
}

# A narrower set emphasising pricing power & capital efficiency (the moat).
MOAT_WEIGHTS: Dict[str, float] = {
    "roic": 0.40,
    "gross_margin": 0.30,
    "net_margin": 0.15,
    "debt_equity": 0.15,        # inverted
}

# Metrics where a lower raw value is better.
_INVERT_METRICS = frozenset({"debt_equity"})


class QualityScorer:
    """
    Compute cross-sectional quality and moat scores from the latest snapshot.

    Parameters
    ----------
    db : DatabaseManager
        Open database manager used to read the latest fundamental snapshot.
    sector_neutral : bool
        When True, percentile ranks are computed within each sector rather than
        across the whole market. Default False (market-wide ranking).
    min_components : int
        Minimum number of available components required to emit a score.
        Stocks with fewer inputs receive None. Default 3.
    """

    def __init__(
        self,
        db: DatabaseManager,
        sector_neutral: bool = False,
        min_components: int = 3,
    ) -> None:
        self.db = db
        self.sector_neutral = sector_neutral
        self.min_components = min_components

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_scores(self, snapshot_date: Optional[str] = None) -> pd.DataFrame:
        """
        Compute quality and moat scores for every ticker on *snapshot_date*.

        Parameters
        ----------
        snapshot_date : ISO date string. When None, the most recent snapshot
            date present in the database is used.

        Returns
        -------
        pd.DataFrame
            Columns: ticker, sector, quality_score, moat_score, plus the
            per-component percentile ranks (suffixed ``_rank``).
        """
        df = self._latest_snapshot(snapshot_date)
        if df.empty:
            logger.warning("QualityScorer: no fundamental snapshots found.")
            return pd.DataFrame()

        components = sorted(set(QUALITY_WEIGHTS) | set(MOAT_WEIGHTS))
        rank_cols: List[str] = []
        for metric in components:
            if metric not in df.columns:
                continue
            rank_cols.append(self._add_rank(df, metric))

        if not rank_cols:
            logger.warning("QualityScorer: no usable component columns present.")
            return pd.DataFrame()

        df["quality_score"] = self._weighted_score(df, QUALITY_WEIGHTS)
        df["moat_score"] = self._weighted_score(df, MOAT_WEIGHTS)

        keep = ["ticker", "sector", "quality_score", "moat_score"] + rank_cols
        keep = [c for c in keep if c in df.columns]
        return df[keep].sort_values("quality_score", ascending=False).reset_index(drop=True)

    def compute_and_store(self, snapshot_date: Optional[str] = None) -> int:
        """
        Compute scores and persist them onto the matching FundamentalSnapshot rows.

        Returns the number of rows updated.
        """
        scores = self.compute_scores(snapshot_date)
        if scores.empty:
            return 0
        snap = snapshot_date or self._latest_date()
        updated = 0
        with self.db._connect() as conn:  # noqa: SLF001 — internal write helper
            for _, row in scores.iterrows():
                conn.execute(
                    """
                    UPDATE fundamental_snapshots
                       SET quality_score = ?, moat_score = ?
                     WHERE ticker = ? AND snapshot_date = ?
                    """,
                    (
                        _none_if_nan(row.get("quality_score")),
                        _none_if_nan(row.get("moat_score")),
                        row["ticker"],
                        snap,
                    ),
                )
                updated += 1
        logger.info("QualityScorer: stored scores for %d tickers", updated)
        return updated

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _add_rank(self, df: pd.DataFrame, metric: str) -> str:
        """Add a percentile-rank column (0-1) for *metric*; return its name."""
        col = f"{metric}_rank"
        values = pd.to_numeric(df[metric], errors="coerce")
        if metric in _INVERT_METRICS:
            values = -values
        if self.sector_neutral and "sector" in df.columns:
            df[col] = values.groupby(df["sector"]).rank(pct=True)
        else:
            df[col] = values.rank(pct=True)
        return col

    def _weighted_score(
        self, df: pd.DataFrame, weights: Dict[str, float]
    ) -> pd.Series:
        """Weighted average of available component ranks, renormalised per row."""
        rank_frame = pd.DataFrame(index=df.index)
        weight_frame = pd.DataFrame(index=df.index)
        for metric, w in weights.items():
            col = f"{metric}_rank"
            if col not in df.columns:
                continue
            present = df[col].notna()
            rank_frame[metric] = df[col] * w
            weight_frame[metric] = np.where(present, w, np.nan)

        weighted_sum = rank_frame.sum(axis=1, skipna=True)
        weight_total = weight_frame.sum(axis=1, skipna=True)
        n_present = rank_frame.notna().sum(axis=1)

        score = weighted_sum / weight_total.replace(0, np.nan)
        score[n_present < self.min_components] = np.nan
        return score

    def _latest_snapshot(self, snapshot_date: Optional[str]) -> pd.DataFrame:
        snap = snapshot_date or self._latest_date()
        if snap is None:
            return pd.DataFrame()
        df = self.db.query(
            "SELECT * FROM fundamental_snapshots WHERE snapshot_date = ?", [snap]
        )
        if "sector" not in df.columns:
            stocks = self.db.query("SELECT ticker, sector FROM stocks")
            df = df.merge(stocks, on="ticker", how="left")
        return df

    def _latest_date(self) -> Optional[str]:
        df = self.db.query(
            "SELECT MAX(snapshot_date) AS d FROM fundamental_snapshots "
            "WHERE pl IS NOT NULL OR roic IS NOT NULL OR roe IS NOT NULL"
        )
        if df.empty or pd.isna(df.iloc[0]["d"]):
            return None
        return str(df.iloc[0]["d"])


def _none_if_nan(value) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f
