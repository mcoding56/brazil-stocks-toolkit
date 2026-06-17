"""
StockAnalysisOrchestrator
=========================
High-level facade that coordinates the full pipeline:

    1. Fetch current fundamental snapshot   (FundamentusFetcher)
    2. Store stocks + snapshot              (DatabaseManager)
    3. Fetch & store price history          (YFinanceFetcher)
    4. Compute historical P/E, P/S          (MetricsCalculator)
    5. Compute & store Z-scores             (ZScoreAnalyzer)

Quick-start
-----------
    from brazil_stocks.orchestrator import StockAnalysisOrchestrator

    orc = StockAnalysisOrchestrator(db_path="data/brazil_stocks.db")

    # Run the full pipeline (can take several minutes on first run)
    orc.run_full_pipeline()

    # Get the 20 cheapest stocks by P/L time-series Z-score
    orc.get_zscore_ranking("pl", top_n=20)

    # Screen for stocks with composite Z-score below -1 (statistically cheap)
    orc.screen_stocks(zscore_threshold=-1.0)
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from tqdm import tqdm

from brazil_stocks.analysis.growth import COMPOSITE_METRIC as GROWTH_SCORE_METRIC, GrowthAnalyzer
from brazil_stocks.analysis.metrics import MetricsCalculator
from brazil_stocks.analysis.zscore import FUNDAMENTAL_METRICS, PRICE_METRIC, ZScoreAnalyzer
from brazil_stocks.analysis.dcf import DCFValuator
from brazil_stocks.analysis.quality import QualityScorer
from brazil_stocks.analysis.factors import FactorAnalyzer
from brazil_stocks.analysis.backtest import BacktestResult, MomentumBacktester
from brazil_stocks.fetchers.fundamentus import FundamentusFetcher
from brazil_stocks.fetchers.yfinance_client import YFinanceFetcher
from brazil_stocks.models.schemas import FundamentalSnapshot
from brazil_stocks.storage.database import DatabaseManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The "Claude Screen" — an opinionated, reliability-weighted composite.
#
# Philosophy: weight each pillar by *reliability x durability*. The most
# persistent, least-manipulable signals (business quality, balance-sheet
# safety) carry the most weight; the noisiest single-point estimate (the DCF
# margin of safety) is demoted and winsorised. Every pillar is percentile-
# ranked to [0, 1] within the surviving cohort *before* weighting, so the
# weights below literally equal each pillar's maximum contribution.
# ---------------------------------------------------------------------------
CLAUDE_WEIGHTS: Dict[str, float] = {
    "quality": 0.25,    # return on capital, margins — the wonderful-business core
    "momentum": 0.20,   # 12-1 price momentum + low-vol — the strongest return predictor
    "valuation": 0.20,  # 60% robust peer multiples + 40% capped DCF discount
    "safety": 0.15,     # graded leverage penalty — avoid permanent loss
    "moat": 0.10,       # durability proxy, kept small to avoid double-counting
    "growth": 0.10,     # conditioned on ROIC clearing its hurdle
}

# Inside the momentum pillar, trend leads the low-volatility (betting-against-beta) tilt.
_CLAUDE_MOM_TREND_WEIGHT = 0.70
_CLAUDE_MOM_LOWVOL_WEIGHT = 0.30

# Inside the valuation pillar, robust peer multiples lead the noisy DCF estimate,
# with the price-vs-VWAP cheapness signal as a complementary mean-reversion tilt.
_CLAUDE_VAL_MULTIPLES_WEIGHT = 0.50
_CLAUDE_VAL_DCF_WEIGHT = 0.30
_CLAUDE_VAL_PRICE_WEIGHT = 0.20

# DCF margin of safety is winsorised to this band before ranking, so a single
# runaway intrinsic-value estimate cannot dominate the screen.
_CLAUDE_MOS_FLOOR = -0.50
_CLAUDE_MOS_CAP = 0.90


class StockAnalysisOrchestrator:
    """
    Coordinate fetch → store → compute → query for Brazilian stock analysis.

    Parameters
    ----------
    db_path : str or Path
        SQLite file path. Created automatically if it does not exist.
    price_period : str
        yfinance period string for historical price downloads (default ``"5y"``).
    window_years : int
        Rolling window for time-series Z-scores (default ``5``).
    include_fiis : bool
        Pass FIIs through to FundamentusFetcher. Default False.
    include_bdrs : bool
        Pass BDRs through to FundamentusFetcher. Default False.
    discount_rate : float
        Nominal BRL discount rate (WACC proxy) for DCF intrinsic value. Default 0.13.
    terminal_growth : float
        Perpetual growth rate used by the DCF terminal value. Default 0.04.
    """

    def __init__(
        self,
        db_path: str | Path = "data/brazil_stocks.db",
        price_period: str = "5y",
        window_years: int = 5,
        include_fiis: bool = False,
        include_bdrs: bool = False,
        discount_rate: float = 0.13,
        terminal_growth: float = 0.04,
    ) -> None:
        self.db = DatabaseManager(db_path)
        self.fundamentus = FundamentusFetcher(
            include_fiis=include_fiis, include_bdrs=include_bdrs
        )
        self.yf = YFinanceFetcher(period=price_period)
        self.metrics_calc = MetricsCalculator(self.db, self.yf)
        self.zscore_analyzer = ZScoreAnalyzer(self.db, window_years=window_years)
        self.growth_analyzer = GrowthAnalyzer(self.db)
        self.dcf_valuator = DCFValuator(
            discount_rate=discount_rate, terminal_growth=terminal_growth
        )
        self.quality_scorer = QualityScorer(self.db)
        self.factor_analyzer = FactorAnalyzer(self.db)
        self.momentum_backtester = MomentumBacktester(self.db)

    # ------------------------------------------------------------------
    # Factor validation
    # ------------------------------------------------------------------

    def backtest_momentum(
        self,
        tickers: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        n_quantiles: int = 5,
        min_dollar_vol: float = 5_000_000.0,
    ) -> BacktestResult | None:
        """
        Walk-forward, point-in-time backtest of cross-sectional 12-1 momentum on
        the stored price history — the honest validation of the momentum pillar.

        Returns a :class:`BacktestResult` (equity curves, per-period returns and a
        performance summary), or ``None`` if there is not enough history.
        """
        bt = MomentumBacktester(
            self.db, n_quantiles=n_quantiles, min_dollar_vol=min_dollar_vol
        )
        return bt.run(tickers=tickers, start=start, end=end)

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def run_full_pipeline(
        self,
        fetch_prices: bool = True,
        compute_historical_metrics: bool = True,
        compute_valuation: bool = True,
        tickers: Optional[List[str]] = None,
        price_period: Optional[str] = None,
    ) -> dict:
        """
        Execute all pipeline steps in order.

        Parameters
        ----------
        fetch_prices : bool
            Whether to fetch and store historical price data (slow on first run).
        compute_historical_metrics : bool
            Whether to reconstruct historical P/E and P/S from yfinance financials.
        tickers : list, optional
            Override the stock universe. If None, all tickers from fundamentus are used.
        price_period : str, optional
            Override the default price period (e.g. ``"3y"``).

        Returns
        -------
        dict
            Summary with row counts for each step.
        """
        summary: dict = {}

        # Step 1 & 2: Fetch fundamentals + store
        logger.info("Step 1/5 — Fetching fundamental snapshot from fundamentus.com.br …")
        fund_df = self.fundamentus.fetch()
        stocks = self.fundamentus.to_stocks(fund_df)
        snapshots = self.fundamentus.to_snapshots(fund_df)
        self.db.upsert_stocks(stocks)
        self.db.upsert_fundamental_snapshots(snapshots)
        summary["stocks_upserted"] = len(stocks)
        summary["snapshots_upserted"] = len(snapshots)
        logger.info("  → %d stocks, %d snapshots stored.", len(stocks), len(snapshots))

        # Determine universe
        universe = tickers or [s.ticker for s in stocks]
        summary["universe_size"] = len(universe)

        # Step 3: Fetch price history
        if fetch_prices:
            logger.info(
                "Step 2/5 — Fetching price history for %d tickers …", len(universe)
            )
            period = price_period or self.yf.period
            price_df = self._fetch_prices_with_progress(universe, period)
            price_bars = self.yf.to_price_bars(price_df)
            n_bars = self.db.upsert_price_bars(price_bars)
            summary["price_bars_stored"] = n_bars
            logger.info("  → %d price bars stored.", n_bars)
        else:
            summary["price_bars_stored"] = 0

        # Step 4: Compute historical metrics
        if compute_historical_metrics:
            logger.info(
                "Step 3/5 — Computing historical metrics for %d tickers …",
                len(universe),
            )
            n_hist = self.metrics_calc.compute_and_store(universe)
            summary["historical_metric_rows"] = n_hist
            logger.info("  → %d historical metric rows stored.", n_hist)
        else:
            summary["historical_metric_rows"] = 0

        # Step 5: Compute Z-scores
        logger.info("Step 4/5 — Computing Z-scores …")
        results = self.zscore_analyzer.compute_all()
        summary["zscore_results"] = len(results)
        logger.info("  → %d Z-score results computed.", len(results))

        # Step 6: Intrinsic value (DCF), FCF & quality/moat scores
        if compute_valuation:
            logger.info(
                "Step 5/5 — Computing FCF, DCF intrinsic value & quality scores …"
            )
            n_val = self.compute_valuation_metrics(universe)
            n_qual = self.quality_scorer.compute_and_store()
            summary["valuation_rows"] = n_val
            summary["quality_rows"] = n_qual
            logger.info(
                "  → %d valuation rows, %d quality-scored tickers.", n_val, n_qual
            )
        else:
            summary["valuation_rows"] = 0
            summary["quality_rows"] = 0

        # Price-based factors (momentum, low-vol) — cheap, uses stored prices only.
        n_factor = self.factor_analyzer.compute_and_store()
        summary["factor_rows"] = n_factor
        logger.info("  → %d tickers with price factors (momentum/low-vol).", n_factor)

        summary["db_summary"] = self.db.summary()
        logger.info("Pipeline complete. DB summary: %s", summary["db_summary"])
        return summary

    def update_database(
        self,
        tickers: Optional[List[str]] = None,
        fetch_prices: bool = True,
        backup: bool = True,
    ) -> dict:
        """Refresh the database with the latest data from all sources.

        Convenience one-call wrapper around :meth:`run_full_pipeline` intended
        for periodic re-runs. Because snapshots are keyed by
        ``(ticker, snapshot_date)`` and upserts are COALESCE-guarded, repeated
        calls accumulate a dated history rather than overwriting it.

        Parameters
        ----------
        tickers : optional universe override (default: all of B3).
        fetch_prices : whether to refresh price history (slow).
        backup : if True and the DB is file-based, write a timestamped copy
            next to it under ``backups/`` after the refresh.

        Returns
        -------
        dict
            The pipeline summary, plus a ``backup_path`` key when a backup ran.
        """
        summary = self.run_full_pipeline(
            fetch_prices=fetch_prices, tickers=tickers
        )
        if backup and str(self.db.db_path) != ":memory:":
            src = Path(self.db.db_path)
            stamp = date.today().isoformat()
            dest = src.parent / "backups" / f"{src.stem}_{stamp}{src.suffix}"
            summary["backup_path"] = str(self.db.backup(dest))
        return summary

    # ------------------------------------------------------------------
    # Valuation enrichment
    # ------------------------------------------------------------------

    def compute_valuation_metrics(self, tickers: List[str]) -> int:
        """
        Enrich the latest snapshot of each ticker with cash-flow and
        intrinsic-value fields: ``fcf_ttm``, ``fcf_per_share``, ``net_debt``,
        ``net_debt_ebitda`` (when derivable), ``dividend_cagr_5y``,
        ``intrinsic_value`` and ``margin_of_safety``.

        FCF and dividends are fetched per-ticker from yfinance, so this step is
        slow; tickers with missing cash-flow data are skipped gracefully (their
        valuation fields stay None and the rest of the pipeline is unaffected).

        Returns the number of snapshot rows updated.
        """
        snap_obj = self.zscore_analyzer._latest_snapshot_date()
        snap = snap_obj.isoformat() if snap_obj else date.today().isoformat()
        latest = self.db.query(
            "SELECT * FROM fundamental_snapshots WHERE snapshot_date = ?", [snap]
        )
        if latest.empty:
            return 0
        by_ticker = latest.set_index("ticker").to_dict("index")

        updates: List[FundamentalSnapshot] = []
        sector_map: dict = {}
        for ticker in tqdm(tickers, desc="Valuation", unit="stock"):
            row = by_ticker.get(ticker)
            if row is None:
                continue
            price = _to_float(row.get("price"))

            fcf_ttm = self.yf.fetch_fcf_ttm(ticker)
            info = self.yf.fetch_info(ticker)
            shares = info.get("shares")
            sector = info.get("sector")
            if sector:
                sector_map[ticker] = sector
            fcf_per_share = (
                fcf_ttm / shares
                if fcf_ttm is not None and shares not in (None, 0)
                else None
            )

            # Net debt: Fundamentus net-debt/equity is a percentage (73.0 = 0.73×),
            # so scale by 100 before multiplying by book value (PL, absolute BRL).
            de = _to_float(row.get("debt_equity"))
            book = _to_float(row.get("book_value"))
            net_debt = (de / 100.0) * book if de is not None and book is not None else None
            net_debt_per_share = (
                net_debt / shares
                if net_debt is not None and shares not in (None, 0)
                else None
            )

            # EBITDA & Net Debt/EBITDA from enterprise value: EV = market cap + net debt,
            # then EBITDA = EV / (EV/EBITDA). Requires a positive ev_ebitda multiple.
            ev_ebitda = _to_float(row.get("ev_ebitda"))
            ebitda = None
            net_debt_ebitda = None
            if (
                price is not None and shares not in (None, 0)
                and net_debt is not None and ev_ebitda not in (None, 0)
                and ev_ebitda > 0
            ):
                enterprise_value = price * shares + net_debt
                ebitda = enterprise_value / ev_ebitda
                if ebitda not in (None, 0) and ebitda > 0:
                    net_debt_ebitda = net_debt / ebitda

            # Growth estimate for the DCF: 5y revenue CAGR (Fundamentus is in %)
            growth_raw = _to_float(row.get("revenue_growth_5y"))
            growth = growth_raw / 100.0 if growth_raw is not None else None

            dcf = self.dcf_valuator.value_share(
                ticker,
                fcf_per_share=fcf_per_share,
                price=price,
                growth_rate=growth,
                net_debt_per_share=net_debt_per_share,
            )

            div_cagr = self.yf.fetch_dividend_cagr(ticker)

            updates.append(
                FundamentalSnapshot(
                    ticker=ticker,
                    snapshot_date=snap,
                    fcf_ttm=fcf_ttm,
                    fcf_per_share=fcf_per_share,
                    net_debt=net_debt,
                    ebitda=ebitda,
                    net_debt_ebitda=net_debt_ebitda,
                    dividend_cagr_5y=div_cagr,
                    intrinsic_value=dcf.intrinsic_value,
                    margin_of_safety=dcf.margin_of_safety,
                )
            )

        if not updates:
            return 0
        if sector_map:
            self.db.update_sectors(sector_map)
        return self.db.upsert_fundamental_snapshots(updates)

    # ------------------------------------------------------------------
    # Query / analysis helpers
    # ------------------------------------------------------------------

    def get_zscore_ranking(
        self,
        metric: str,
        score_type: str = "time_series_zscore",
        top_n: int = 30,
        ascending: bool = True,
    ) -> pd.DataFrame:
        """
        Rank tickers by Z-score for *metric*.

        Parameters
        ----------
        metric     : e.g. ``"pl"``, ``"ev_ebitda"``
        score_type : ``"time_series_zscore"`` or ``"cross_sectional_zscore"``
        top_n      : number of results to return (0 = all)
        ascending  : True = cheapest first
        """
        df = self.zscore_analyzer.get_ranking(
            metric=metric, score_type=score_type, ascending=ascending
        )
        if top_n and not df.empty:
            df = df.head(top_n)
        return df

    def screen_stocks(
        self,
        zscore_threshold: float = -1.0,
        metrics: Optional[List[str]] = None,
        score_type: str = "time_series_zscore",
        require_all: bool = False,
    ) -> pd.DataFrame:
        """
        Screen for stocks where at least one (or all) metrics cross the Z-score threshold.

        Parameters
        ----------
        zscore_threshold : z-score cut-off (default -1.0 = 1 std below average)
        metrics          : metrics to screen (default all fundamental metrics)
        score_type       : which z-score to use
        require_all      : if True, ALL metrics must pass the threshold

        Returns
        -------
        pd.DataFrame  with columns: ticker, metric, <score_type>
        """
        metrics = metrics or FUNDAMENTAL_METRICS
        snap_date_obj = self.zscore_analyzer._latest_snapshot_date()
        snap_date = snap_date_obj.isoformat() if snap_date_obj else None

        df = self.db.get_zscore_results(snapshot_date=snap_date)
        if df.empty:
            return df

        df = df[df["metric"].isin(metrics)].copy()
        cheap = df[df[score_type] <= zscore_threshold]

        if require_all:
            counts = cheap.groupby("ticker")["metric"].nunique()
            qualifying = counts[counts == len(metrics)].index
            cheap = cheap[cheap["ticker"].isin(qualifying)]

        pivot = cheap.pivot_table(
            index="ticker", columns="metric", values=score_type, aggfunc="first"
        )
        pivot["composite_zscore"] = pivot.mean(axis=1)
        return pivot.sort_values("composite_zscore").reset_index()

    def get_stock_profile(self, ticker: str) -> dict:
        """
        Return a full profile for a single ticker:
        latest fundamentals + Z-scores for all metrics.
        """
        fund = self.db.get_fundamental_snapshots(ticker=ticker)
        latest_fund = fund.iloc[-1].to_dict() if not fund.empty else {}

        snap_date_obj = self.zscore_analyzer._latest_snapshot_date()
        snap_date = snap_date_obj.isoformat() if snap_date_obj else None
        zscores = self.db.get_zscore_results(ticker=ticker, snapshot_date=snap_date)

        return {
            "ticker": ticker,
            "latest_fundamentals": latest_fund,
            "zscores": zscores.to_dict(orient="records") if not zscores.empty else [],
        }

    def get_heatmap_data(
        self,
        metrics: Optional[List[str]] = None,
        score_type: str = "time_series_zscore",
        top_n: int = 50,
    ) -> pd.DataFrame:
        """
        Return a pivot table suitable for seaborn heatmap plotting.

        Rows = tickers (sorted cheapest composite first), columns = metrics.
        """
        return self.zscore_analyzer.get_zscore_heatmap_data(
            metrics=metrics, score_type=score_type, top_n=top_n
        )

    def get_composite_ranking(
        self,
        metrics: Optional[List[str]] = None,
        score_type: str = "time_series_zscore",
    ) -> pd.DataFrame:
        """Return a composite Z-score ranking across all metrics."""
        return self.zscore_analyzer.get_composite_score(
            metrics=metrics, score_type=score_type
        )

    # ------------------------------------------------------------------
    # GARP (Growth + Value) screening
    # ------------------------------------------------------------------

    def screen_quality_value(
        self,
        value_metrics: Optional[List[str]] = None,
        value_threshold: float = -1.0,
        growth_threshold: float = 1.0,
        score_type: str = "cross_sectional_zscore",
        require_growth: bool = True,
    ) -> pd.DataFrame:
        """
        Find stocks that are *cheap* (composite value Z <= value_threshold) **and**
        *growing* (growth_score >= growth_threshold).

        Returns a DataFrame with columns:
            ticker, value_zscore, growth_score, <per-metric value z-scores>
        Sorted by combined alpha (lower value_zscore + higher growth = better).
        """
        value_metrics = value_metrics or ["pl", "pvp", "ev_ebitda"]
        snap_obj = self.zscore_analyzer._latest_snapshot_date()
        snap = snap_obj.isoformat() if snap_obj else None

        zdf = self.db.get_zscore_results(snapshot_date=snap)
        if zdf.empty:
            return zdf

        # Value composite
        v = zdf[zdf["metric"].isin(value_metrics)].copy()
        v_pivot = v.pivot_table(
            index="ticker", columns="metric", values=score_type, aggfunc="first"
        )
        v_pivot["value_zscore"] = v_pivot.mean(axis=1)

        # Growth score
        g = zdf[zdf["metric"] == GROWTH_SCORE_METRIC][["ticker", "cross_sectional_zscore"]]
        g = g.rename(columns={"cross_sectional_zscore": "growth_score"}).set_index("ticker")

        out = v_pivot.join(g, how="left")
        out = out[out["value_zscore"] <= value_threshold]
        if require_growth:
            out = out[out["growth_score"] >= growth_threshold]

        # Combined alpha score: lower value + higher growth = better
        out["alpha_score"] = out["growth_score"].fillna(0) - out["value_zscore"]
        return out.sort_values("alpha_score", ascending=False).reset_index()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_prices_with_progress(
        self, tickers: List[str], period: str
    ) -> pd.DataFrame:
        """
        Fetch prices in batches with a tqdm progress bar.
        """
        batch_size = self.yf.batch_size
        batches = [
            tickers[i : i + batch_size] for i in range(0, len(tickers), batch_size)
        ]
        frames = []
        for batch in tqdm(batches, desc="Fetching prices", unit="batch"):
            df = self.yf.fetch_prices(batch, period=period)
            if not df.empty:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # ------------------------------------------------------------------
    # Intrinsic-value & master screens
    # ------------------------------------------------------------------

    def get_intrinsic_value_ranking(
        self,
        top_n: int = 30,
        min_margin_of_safety: Optional[float] = None,
        exclude_financials: bool = True,
        min_liquidity: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Rank tickers by DCF margin of safety on the latest snapshot.

        Parameters
        ----------
        top_n : number of rows to return (0 = all).
        min_margin_of_safety : optional filter, e.g. 0.30 keeps only names
            trading at least 30 % below estimated intrinsic value.
        exclude_financials : drop banks/insurers, for which the FCFF DCF is
            not meaningful (default True).
        min_liquidity : optional floor on 2-month average daily traded volume
            (BRL) to screen out thinly-traded microcaps with stale data.

        Returns
        -------
        pd.DataFrame
            Columns: ticker, sector, price, intrinsic_value, margin_of_safety,
            fcf_per_share, quality_score, moat_score — sorted by margin of safety.
        """
        snap_obj = self.zscore_analyzer._latest_snapshot_date()
        snap = snap_obj.isoformat() if snap_obj else None
        df = self.db.query(
            """
            SELECT f.ticker, s.sector, f.price, f.intrinsic_value, f.margin_of_safety,
                   f.fcf_per_share, f.liquidity_2m, f.quality_score, f.moat_score
              FROM fundamental_snapshots f
              LEFT JOIN stocks s ON s.ticker = f.ticker
             WHERE f.snapshot_date = ? AND f.intrinsic_value IS NOT NULL
            """,
            [snap],
        )
        if df.empty:
            return df
        if exclude_financials:
            df = df[~df["sector"].apply(_is_financial)]
        if min_liquidity is not None:
            df = df[df["liquidity_2m"].fillna(0) >= min_liquidity]
        if min_margin_of_safety is not None:
            df = df[df["margin_of_safety"] >= min_margin_of_safety]
        df = df.sort_values("margin_of_safety", ascending=False).reset_index(drop=True)
        return df.head(top_n) if top_n else df

    def screen_graham_buffett(
        self,
        min_margin_of_safety: float = 0.20,
        min_quality: float = 0.5,
        min_growth: float = 0.0,
        max_debt_equity: Optional[float] = None,
        exclude_financials: bool = True,
        min_liquidity: Optional[float] = None,
        top_n: int = 30,
    ) -> pd.DataFrame:
        """
        Master quality-value screen blending the seven priorities of Graham,
        Buffett and Damodaran into a single ``master_score``:

            1. Discount to intrinsic value      (DCF margin of safety)
            2. Sustainable earnings growth       (growth_score)
            3. High return on capital            (roic / quality_score)
            4. Low leverage                      (debt_equity, inverted)
            5. Durable competitive advantage     (moat_score)
            6. Overall business quality          (quality_score)
            7. Statistical cheapness vs peers    (value Z-score)

        Parameters
        ----------
        min_margin_of_safety : minimum DCF discount required (default 0.20).
        min_quality : minimum composite quality score 0-1 (default 0.5).
        min_growth : minimum growth_score cross-sectional Z (default 0.0).
        max_debt_equity : optional hard cap on net-debt/equity.
        exclude_financials : drop banks/insurers (FCFF DCF invalid; default True).
        min_liquidity : optional floor on 2-month average daily traded volume (BRL).
        top_n : number of rows to return (0 = all).

        Returns
        -------
        pd.DataFrame
            One row per qualifying ticker, sorted by ``master_score`` desc.
        """
        snap_obj = self.zscore_analyzer._latest_snapshot_date()
        snap = snap_obj.isoformat() if snap_obj else None

        fund = self.db.query(
            """
            SELECT f.ticker, s.sector, f.price, f.pl, f.pvp, f.roic, f.debt_equity,
                   f.liquidity_2m, f.intrinsic_value, f.margin_of_safety,
                   f.quality_score, f.moat_score
              FROM fundamental_snapshots f
              LEFT JOIN stocks s ON s.ticker = f.ticker
             WHERE f.snapshot_date = ?
            """,
            [snap],
        )
        if fund.empty:
            return fund

        # Attach growth_score and a value Z-score composite from zscore_results
        zdf = self.db.get_zscore_results(snapshot_date=snap)
        if not zdf.empty:
            g = zdf[zdf["metric"] == GROWTH_SCORE_METRIC][["ticker", "cross_sectional_zscore"]]
            g = g.rename(columns={"cross_sectional_zscore": "growth_score"})
            v = zdf[zdf["metric"].isin(["pl", "pvp", "ev_ebitda"])]
            v_pivot = v.pivot_table(
                index="ticker", columns="metric",
                values="cross_sectional_zscore", aggfunc="first",
            )
            v_pivot["value_zscore"] = v_pivot.mean(axis=1)
            fund = fund.merge(g, on="ticker", how="left")
            fund = fund.merge(
                v_pivot[["value_zscore"]].reset_index(), on="ticker", how="left"
            )
            # Price-vs-VWAP cheapness (time-series): cheap names sit below VWAP.
            pz = zdf[zdf["metric"] == PRICE_METRIC][["ticker", "time_series_zscore"]]
            pz = pz.rename(columns={"time_series_zscore": "price_vwap_z"})
            fund = fund.merge(pz, on="ticker", how="left")
        else:
            fund["growth_score"] = pd.NA
            fund["value_zscore"] = pd.NA
            fund["price_vwap_z"] = pd.NA

        # Apply filters
        out = fund.copy()
        if exclude_financials:
            out = out[~out["sector"].apply(_is_financial)]
        if min_liquidity is not None:
            out = out[out["liquidity_2m"].fillna(0) >= min_liquidity]
        out = out[out["margin_of_safety"].fillna(-1) >= min_margin_of_safety]
        out = out[out["quality_score"].fillna(0) >= min_quality]
        out = out[out["growth_score"].fillna(0) >= min_growth]
        if max_debt_equity is not None:
            out = out[out["debt_equity"].fillna(1e9) <= max_debt_equity]
        if out.empty:
            return out

        # Composite master score: each pillar contributes a normalised term.
        # A negative value_zscore (cheap vs peers) and a negative price_vwap_z
        # (price below its own VWAP) both *add* to the score.
        out["master_score"] = (
            out["margin_of_safety"].fillna(0)
            + out["quality_score"].fillna(0)
            + out["moat_score"].fillna(0)
            + out["growth_score"].fillna(0).clip(-3, 3) / 3.0
            - out["value_zscore"].fillna(0).clip(-3, 3) / 3.0
            - out["price_vwap_z"].fillna(0).clip(-3, 3) / 6.0
        )
        out = out.sort_values("master_score", ascending=False).reset_index(drop=True)
        return out.head(top_n) if top_n else out

    # ------------------------------------------------------------------ #
    # The Claude Screen                                                  #
    # ------------------------------------------------------------------ #
    def screen_claude(
        self,
        weights: Optional[Dict[str, float]] = None,
        roic_hurdle: float = 10.0,
        exclude_financials: bool = True,
        min_liquidity: Optional[float] = None,
        require_positive_quality: bool = True,
        min_pillar_coverage: float = 0.50,
        top_n: int = 30,
    ) -> pd.DataFrame:
        """
        The **Claude Screen** — an opinionated, reliability-weighted composite
        that improves on ``screen_graham_buffett`` in four ways:

        1. **Intentional weighting.** Every pillar is percentile-ranked to
           ``[0, 1]`` *within the surviving cohort* before weighting, so the
           weights in :data:`CLAUDE_WEIGHTS` are the literal maximum
           contribution of each pillar — no more accidental dominance by
           whichever column happens to have the widest numeric range.
        2. **The noisiest signal is demoted.** The single-point DCF margin of
           safety is winsorised and folded into the *valuation* pillar at 30%,
           behind robust peer multiples at 50% and a price-vs-VWAP cheapness
           tilt at 20% — instead of carrying full, uncapped weight.
        3. **Quality and moat are de-correlated.** Return on capital is no
           longer triple-counted; moat keeps a deliberately small 15% weight.
        4. **Leverage is a graded penalty, not a gate.** Balance-sheet safety
           is its own 20% pillar (percentile-ranked inverse net-debt/equity and
           current ratio), so a lightly levered name scores strictly better than
           a heavily levered one.

        Growth is additionally *conditioned on ROIC clearing* ``roic_hurdle``:
        growth without returns above the cost of capital destroys value
        (Damodaran), so it earns full credit only when the business out-earns
        its capital and is linearly damped toward zero below the hurdle.

        The **momentum** pillar blends 12-1 price momentum (70%) with a
        low-volatility tilt (30%, betting-against-beta). It is the strongest
        standalone return predictor and is negatively correlated with value, so
        it lifts the whole screen — *provided* price factors have been computed
        (``FactorAnalyzer.compute_and_store``). If they are missing, the pillar
        is simply absent and the remaining weights re-normalise.

        Pillar weights (see :data:`CLAUDE_WEIGHTS`):
        quality 25% · momentum 20% · valuation 20% · safety 15% · moat 10% ·
        growth 10%.

        Parameters
        ----------
        weights : optional override of the pillar weights (keys: ``quality``,
            ``safety``, ``valuation``, ``moat``, ``growth``). Re-normalised to
            sum to 1.
        roic_hurdle : ROIC in Fundamentus percent units (e.g. ``10.0`` = 10%)
            below which the growth pillar is linearly damped toward zero.
        exclude_financials : drop banks/insurers (FCFF DCF invalid; default True).
        min_liquidity : optional floor on 2-month average daily traded volume (BRL).
        require_positive_quality : drop names with no ``quality_score`` (default True).
        min_pillar_coverage : drop names whose *available* pillar weights sum to
            less than this (guards against scoring a stock on one lucky pillar).
        top_n : number of rows to return (0 = all).

        Returns
        -------
        pd.DataFrame
            One row per qualifying ticker with the per-pillar ``[0, 1]``
            contributions and the final ``claude_score`` (0-1), sorted desc.
        """
        # Resolve & re-normalise weights.
        w = dict(CLAUDE_WEIGHTS)
        if weights:
            w.update({k: float(v) for k, v in weights.items() if k in w})
        total_w = sum(w.values()) or 1.0
        w = {k: v / total_w for k, v in w.items()}

        snap_obj = self.zscore_analyzer._latest_snapshot_date()
        snap = snap_obj.isoformat() if snap_obj else None

        fund = self.db.query(
            """
            SELECT f.ticker, s.sector, f.price, f.roic, f.debt_equity,
                   f.current_ratio, f.liquidity_2m, f.intrinsic_value,
                   f.margin_of_safety, f.quality_score, f.moat_score,
                   f.momentum_12_1, f.volatility_6m
              FROM fundamental_snapshots f
              LEFT JOIN stocks s ON s.ticker = f.ticker
             WHERE f.snapshot_date = ?
            """,
            [snap],
        )
        if fund.empty:
            return fund

        # Attach growth_score and a value Z-score composite from zscore_results.
        zdf = self.db.get_zscore_results(snapshot_date=snap)
        if not zdf.empty:
            g = zdf[zdf["metric"] == GROWTH_SCORE_METRIC][["ticker", "cross_sectional_zscore"]]
            g = g.rename(columns={"cross_sectional_zscore": "growth_score"})
            v = zdf[zdf["metric"].isin(["pl", "pvp", "ev_ebitda"])]
            v_pivot = v.pivot_table(
                index="ticker", columns="metric",
                values="cross_sectional_zscore", aggfunc="first",
            )
            v_pivot["value_zscore"] = v_pivot.mean(axis=1)
            fund = fund.merge(g, on="ticker", how="left")
            fund = fund.merge(
                v_pivot[["value_zscore"]].reset_index(), on="ticker", how="left"
            )
            # Price-vs-VWAP cheapness (time-series): cheap names sit below VWAP.
            pz = zdf[zdf["metric"] == PRICE_METRIC][["ticker", "time_series_zscore"]]
            pz = pz.rename(columns={"time_series_zscore": "price_vwap_z"})
            fund = fund.merge(pz, on="ticker", how="left")
        else:
            fund["growth_score"] = pd.NA
            fund["value_zscore"] = pd.NA
            fund["price_vwap_z"] = pd.NA

        # Gates (membership of the peer cohort, not graded).
        cohort = fund.copy()
        if exclude_financials:
            cohort = cohort[~cohort["sector"].apply(_is_financial)]
        if min_liquidity is not None:
            cohort = cohort[cohort["liquidity_2m"].fillna(0) >= min_liquidity]
        if require_positive_quality:
            cohort = cohort[cohort["quality_score"].notna()]
        cohort = cohort.reset_index(drop=True)
        if cohort.empty:
            return cohort

        # --- Percentile-rank helpers (computed *within* the surviving cohort) ---
        def _pct(series, invert: bool = False) -> pd.Series:
            s = pd.to_numeric(series, errors="coerce")
            r = s.rank(pct=True)            # NaN stays NaN
            return (1.0 - r) if invert else r

        def _blend(parts: List) -> pd.Series:
            """Weighted mean of available ranks, ignoring NaN components per row."""
            num = pd.Series(0.0, index=cohort.index)
            den = pd.Series(0.0, index=cohort.index)
            for rank, weight in parts:
                num = num + (rank * weight).fillna(0.0)
                den = den + rank.notna().astype(float) * weight
            return num / den.replace(0.0, np.nan)

        # Pillar 1 — Quality (return on capital, margins): already a percentile.
        quality_pillar = _pct(cohort["quality_score"])

        # Pillar 2 — Safety (graded leverage): low net-debt/equity, high current ratio.
        safety_pillar = _blend([
            (_pct(cohort["debt_equity"], invert=True), 0.75),
            (_pct(cohort["current_ratio"]), 0.25),
        ])

        # Pillar 3 — Valuation: robust peer multiples lead the winsorised DCF,
        # with the price-vs-VWAP cheapness signal as a mean-reversion tilt.
        mos_capped = pd.to_numeric(cohort["margin_of_safety"], errors="coerce").clip(
            lower=_CLAUDE_MOS_FLOOR, upper=_CLAUDE_MOS_CAP
        )
        valuation_pillar = _blend([
            (_pct(cohort["value_zscore"], invert=True), _CLAUDE_VAL_MULTIPLES_WEIGHT),
            (_pct(mos_capped), _CLAUDE_VAL_DCF_WEIGHT),
            (_pct(cohort["price_vwap_z"], invert=True), _CLAUDE_VAL_PRICE_WEIGHT),
        ])

        # Pillar 4 — Moat durability (deliberately small to avoid double-counting).
        moat_pillar = _pct(cohort["moat_score"])

        # Pillar 5 — Growth, conditioned on ROIC clearing the hurdle.
        roic_gate = (
            pd.to_numeric(cohort["roic"], errors="coerce") / float(roic_hurdle)
        ).clip(lower=0.0, upper=1.0).fillna(0.5)
        growth_pillar = _pct(cohort["growth_score"]) * roic_gate

        # Pillar 6 — Momentum: 12-1 trend leads, low-volatility tilt follows.
        momentum_pillar = _blend([
            (_pct(cohort["momentum_12_1"]), _CLAUDE_MOM_TREND_WEIGHT),
            (_pct(cohort["volatility_6m"], invert=True), _CLAUDE_MOM_LOWVOL_WEIGHT),
        ])

        pillars = {
            "quality": quality_pillar,
            "safety": safety_pillar,
            "valuation": valuation_pillar,
            "moat": moat_pillar,
            "growth": growth_pillar,
            "momentum": momentum_pillar,
        }

        # Weighted blend, re-normalised by the weight of the *available* pillars
        # so a missing input degrades gracefully instead of zeroing the stock.
        score_num = pd.Series(0.0, index=cohort.index)
        weight_den = pd.Series(0.0, index=cohort.index)
        for name, pillar in pillars.items():
            score_num = score_num + (pillar * w[name]).fillna(0.0)
            weight_den = weight_den + pillar.notna().astype(float) * w[name]

        cohort = cohort.assign(
            quality_pillar=quality_pillar.round(4),
            safety_pillar=safety_pillar.round(4),
            valuation_pillar=valuation_pillar.round(4),
            moat_pillar=moat_pillar.round(4),
            growth_pillar=growth_pillar.round(4),
            momentum_pillar=momentum_pillar.round(4),
            pillar_coverage=weight_den.round(3),
            claude_score=(score_num / weight_den.replace(0.0, np.nan)).round(4),
        )

        # Require enough pillar coverage to trust the score.
        cohort = cohort[cohort["pillar_coverage"] >= min_pillar_coverage]
        cohort = cohort.dropna(subset=["claude_score"])
        if cohort.empty:
            return cohort

        out = cohort.sort_values("claude_score", ascending=False).reset_index(drop=True)
        return out.head(top_n) if top_n else out


def _to_float(value) -> Optional[float]:
    """Best-effort conversion to float, returning None for missing/NaN values."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


_FINANCIAL_KEYWORDS = (
    "financ", "bank", "banco", "insur", "seguro", "capital market",
    "credit", "crédito", "asset management",
)


def _is_financial(sector) -> bool:
    """True if *sector* looks like a bank/insurer/financial (DCF not meaningful)."""
    if sector is None or (isinstance(sector, float) and pd.isna(sector)):
        return False
    text = str(sector).lower()
    return any(kw in text for kw in _FINANCIAL_KEYWORDS)

