"""
YFinanceFetcher
===============
Wraps `yfinance` to retrieve:

1. **Historical daily OHLCV prices** for a list of B3 tickers.
2. **Quarterly financial statements** (EPS, net revenue) per ticker — used
   by MetricsCalculator to reconstruct historical P/E and P/S series.

B3 tickers must carry the `.SA` suffix in yfinance (e.g. `PETR4.SA`).
The fetcher transparently handles suffix conversion so callers can always
pass plain B3 tickers (e.g. `PETR4`).
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf

from brazil_stocks.fetchers.base import BaseFetcher
from brazil_stocks.models.schemas import PriceBar

logger = logging.getLogger(__name__)

_SA_SUFFIX = ".SA"
_DEFAULT_PERIOD = "5y"
_BATCH_SIZE = 50          # yfinance handles batch downloads well up to ~50 tickers
_RETRY_DELAY = 2.0        # seconds between retries on network errors
_MAX_RETRIES = 3


def _add_suffix(ticker: str) -> str:
    """Add `.SA` suffix if not already present."""
    return ticker if ticker.endswith(_SA_SUFFIX) else ticker + _SA_SUFFIX


def _strip_suffix(ticker: str) -> str:
    """Remove `.SA` suffix if present."""
    return ticker.removesuffix(_SA_SUFFIX)


class YFinanceFetcher(BaseFetcher):
    """
    Fetch historical prices and quarterly financials from Yahoo Finance.

    Parameters
    ----------
    period : str
        yfinance period string for price history (e.g. ``"5y"``, ``"2y"``).
        Ignored when explicit start/end dates are passed to `fetch_prices`.
    batch_size : int
        Number of tickers to download in a single yfinance call.
    request_delay : float
        Seconds to sleep between batches to be polite to Yahoo Finance.
    """

    def __init__(
        self,
        period: str = _DEFAULT_PERIOD,
        batch_size: int = _BATCH_SIZE,
        request_delay: float = 0.5,
    ) -> None:
        self.period = period
        self.batch_size = batch_size
        self.request_delay = request_delay

    # ------------------------------------------------------------------
    # BaseFetcher implementation
    # ------------------------------------------------------------------

    def fetch(self, tickers: Optional[List[str]] = None, **kwargs) -> pd.DataFrame:
        """
        Convenience method that maps to `fetch_prices`.

        Returns a long-form DataFrame with columns:
        ticker, date, open, high, low, close, volume
        """
        if not tickers:
            raise ValueError("'tickers' list must be provided.")
        return self.fetch_prices(tickers, **kwargs)

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def fetch_prices(
        self,
        tickers: List[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Download OHLCV data for *tickers* and return a long-form DataFrame.

        Parameters
        ----------
        tickers : list of plain B3 tickers (without .SA suffix)
        start   : ISO date string (overrides `period`)
        end     : ISO date string (used with `start`)
        period  : yfinance period string, defaults to constructor value

        Returns
        -------
        pd.DataFrame
            Columns: ticker, date, open, high, low, close, volume
        """
        # Deduplicate while preserving order to avoid redundant network calls.
        clean_tickers = list(dict.fromkeys(tickers))
        sa_tickers = [_add_suffix(t) for t in clean_tickers]
        period = period or self.period

        chunks = [
            sa_tickers[i : i + self.batch_size]
            for i in range(0, len(sa_tickers), self.batch_size)
        ]

        frames: List[pd.DataFrame] = []
        for chunk in chunks:
            df = self._download_prices(chunk, start=start, end=end, period=period)
            if df is not None and not df.empty:
                frames.append(df)
            if self.request_delay:
                time.sleep(self.request_delay)

        if not frames:
            logger.warning("YFinanceFetcher: no price data returned for any ticker.")
            return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])

        result = pd.concat(frames, ignore_index=True)
        result["ticker"] = result["ticker"].apply(_strip_suffix)
        result = result.drop_duplicates(subset=["ticker", "date"]).reset_index(drop=True)
        return result

    def to_price_bars(self, df: pd.DataFrame) -> List[PriceBar]:
        """Convert a fetched prices DataFrame to PriceBar instances."""
        bars = []
        for _, row in df.iterrows():
            bars.append(
                PriceBar(
                    ticker=row["ticker"],
                    date=row["date"],
                    open=row.get("open"),
                    high=row.get("high"),
                    low=row.get("low"),
                    close=row.get("close"),
                    volume=row.get("volume"),
                )
            )
        return bars

    # ------------------------------------------------------------------
    # Quarterly financials
    # ------------------------------------------------------------------

    def fetch_financials(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Return quarterly (income_statement_df, balance_sheet_df) for *ticker*.

        The DataFrames are indexed by metric name with quarterly period columns.
        Returns empty DataFrames if data is unavailable.

        Useful rows in income_statement_df
        ------------------------------------
        "Net Income"        → quarterly net earnings (for EPS estimation)
        "Total Revenue"     → quarterly revenue (for P/S estimation)
        "Basic EPS"         → direct EPS if available

        Parameters
        ----------
        ticker : plain B3 ticker (without .SA suffix)
        """
        sa = _add_suffix(ticker)
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                t = yf.Ticker(sa)
                income = t.quarterly_income_stmt
                balance = t.quarterly_balance_sheet
                # Transpose so that columns = metrics, index = period dates
                income = income.T if income is not None and not income.empty else pd.DataFrame()
                balance = balance.T if balance is not None and not balance.empty else pd.DataFrame()
                return income, balance
            except Exception as exc:
                logger.warning(
                    "fetch_financials(%s) attempt %d/%d failed: %s",
                    ticker, attempt, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY * attempt)
        return pd.DataFrame(), pd.DataFrame()

    def fetch_shares_outstanding(self, ticker: str) -> Optional[float]:
        """Return the latest reported shares outstanding, or None."""
        sa = _add_suffix(ticker)
        try:
            info = yf.Ticker(sa).info
            return info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        except Exception as exc:
            logger.debug("fetch_shares_outstanding(%s): %s", ticker, exc)
            return None

    def fetch_info(self, ticker: str) -> dict:
        """Return a small dict of company info in a single ``.info`` call.

        Keys: ``shares`` (float|None), ``sector`` (str|None),
        ``industry`` (str|None). Degrades to an empty-valued dict on error.
        """
        sa = _add_suffix(ticker)
        try:
            info = yf.Ticker(sa).info
            return {
                "shares": info.get("sharesOutstanding")
                or info.get("impliedSharesOutstanding"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            }
        except Exception as exc:
            logger.debug("fetch_info(%s): %s", ticker, exc)
            return {"shares": None, "sector": None, "industry": None}

    # ------------------------------------------------------------------
    # Cash flow & dividends
    # ------------------------------------------------------------------

    def fetch_cashflow(self, ticker: str) -> pd.DataFrame:
        """
        Return the quarterly cash-flow statement for *ticker*.

        The DataFrame is transposed so columns = metrics, index = period dates
        (most recent first). Returns an empty DataFrame when unavailable.

        Useful columns
        --------------
        "Operating Cash Flow"   → cash generated by operations
        "Capital Expenditure"   → CapEx (reported as a negative number)
        "Free Cash Flow"        → reported FCF when present

        Parameters
        ----------
        ticker : plain B3 ticker (without .SA suffix)
        """
        sa = _add_suffix(ticker)
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                cf = yf.Ticker(sa).quarterly_cashflow
                if cf is None or cf.empty:
                    return pd.DataFrame()
                return cf.T
            except Exception as exc:
                logger.warning(
                    "fetch_cashflow(%s) attempt %d/%d failed: %s",
                    ticker, attempt, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY * attempt)
        return pd.DataFrame()

    def fetch_fcf_ttm(self, ticker: str) -> Optional[float]:
        """
        Compute trailing-12-month Free Cash Flow = Operating Cash Flow − CapEx.

        Sums the four most recent quarters. CapEx is reported by Yahoo as a
        negative value, so it is *added* to operating cash flow.
        Returns None when the cash-flow statement is missing required rows.
        """
        cf = self.fetch_cashflow(ticker)
        if cf.empty:
            return None

        def _series(*names: str) -> Optional[pd.Series]:
            for n in names:
                if n in cf.columns:
                    return pd.to_numeric(cf[n], errors="coerce")
            return None

        # Prefer a directly reported Free Cash Flow row when available
        reported = _series("Free Cash Flow")
        if reported is not None and reported.head(4).notna().any():
            return float(reported.head(4).dropna().sum())

        ocf = _series("Operating Cash Flow", "Total Cash From Operating Activities")
        capex = _series("Capital Expenditure", "Capital Expenditures")
        if ocf is None or capex is None:
            return None
        ttm_ocf = ocf.head(4).dropna().sum()
        ttm_capex = capex.head(4).dropna().sum()
        if ttm_ocf == 0 and ttm_capex == 0:
            return None
        return float(ttm_ocf + ttm_capex)  # capex is negative → adds correctly

    def fetch_dividends(self, ticker: str) -> pd.Series:
        """
        Return the dividend history as a date-indexed Series (BRL per share).

        Returns an empty Series when no dividend history is available.

        Parameters
        ----------
        ticker : plain B3 ticker (without .SA suffix)
        """
        sa = _add_suffix(ticker)
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                divs = yf.Ticker(sa).dividends
                if divs is None or divs.empty:
                    return pd.Series(dtype=float)
                return divs
            except Exception as exc:
                logger.warning(
                    "fetch_dividends(%s) attempt %d/%d failed: %s",
                    ticker, attempt, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY * attempt)
        return pd.Series(dtype=float)

    def fetch_dividend_cagr(self, ticker: str, years: int = 5) -> Optional[float]:
        """
        Compute the dividend-per-share CAGR over the last *years* full calendar
        years. Returns None when insufficient history exists or the base year
        paid no dividends.
        """
        divs = self.fetch_dividends(ticker)
        if divs.empty:
            return None
        try:
            annual = divs.groupby(divs.index.year).sum()
        except Exception:
            return None
        # Drop the current (incomplete) year to avoid understating the latest point
        from datetime import date as _date
        current_year = _date.today().year
        annual = annual[annual.index < current_year]
        if len(annual) < years + 1:
            return None
        recent = annual.iloc[-1]
        base = annual.iloc[-(years + 1)]
        if base is None or base <= 0 or recent <= 0:
            return None
        return float((recent / base) ** (1 / years) - 1)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _download_prices(
        self,
        sa_tickers: List[str],
        start: Optional[str],
        end: Optional[str],
        period: str,
    ) -> Optional[pd.DataFrame]:
        kwargs: dict = {"auto_adjust": True, "progress": False}
        if start:
            kwargs["start"] = start
            if end:
                kwargs["end"] = end
        else:
            kwargs["period"] = period

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                raw = yf.download(sa_tickers, **kwargs)
                if raw.empty:
                    return None
                return self._wide_to_long(raw, sa_tickers)
            except Exception as exc:
                logger.warning(
                    "_download_prices attempt %d/%d failed for %s tickers: %s",
                    attempt, _MAX_RETRIES, len(sa_tickers), exc,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY * attempt)
        return None

    @staticmethod
    def _wide_to_long(raw: pd.DataFrame, sa_tickers: List[str]) -> pd.DataFrame:
        """
        Convert yfinance wide-format output to long form.

        yfinance 1.x always returns a MultiIndex with levels (Price, Ticker),
        e.g. ('Close', 'PETR4.SA').  After reset_index() the date column
        becomes ('Date', '').  This method handles both old flat and new
        MultiIndex formats.
        """
        raw = raw.copy()
        raw = raw.reset_index()

        # Locate the date column regardless of whether columns are MultiIndex
        if isinstance(raw.columns, pd.MultiIndex):
            date_col = next(
                (c for c in raw.columns if str(c[0]).lower() in ("date", "datetime")),
                None,
            )
        else:
            date_col = next(
                (c for c in raw.columns if str(c).lower() in ("date", "datetime")),
                None,
            )

        if date_col is None:
            logger.warning("_wide_to_long: could not find date column in %s", list(raw.columns[:6]))
            return pd.DataFrame()

        frames = []
        for ticker in sa_tickers:
            if isinstance(raw.columns, pd.MultiIndex):
                cols_map = {
                    "open":   ("Open",   ticker),
                    "high":   ("High",   ticker),
                    "low":    ("Low",    ticker),
                    "close":  ("Close",  ticker),
                    "volume": ("Volume", ticker),
                }
            else:
                cols_map = {
                    "open":   "Open",
                    "high":   "High",
                    "low":    "Low",
                    "close":  "Close",
                    "volume": "Volume",
                }

            src_cols = [v for v in cols_map.values() if v in raw.columns]
            dst_cols = [k for k, v in cols_map.items() if v in raw.columns]

            if not src_cols:
                continue

            sub = raw[[date_col] + src_cols].copy()
            sub.columns = ["date"] + dst_cols
            sub["date"] = pd.to_datetime(sub["date"]).dt.date
            # Some tickers are returned with all-NaN bars; treat them as no data.
            if "close" not in sub.columns:
                continue
            sub = sub[sub["close"].notna()].copy()
            if sub.empty:
                continue
            sub.insert(0, "ticker", ticker)
            frames.append(sub)

        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
