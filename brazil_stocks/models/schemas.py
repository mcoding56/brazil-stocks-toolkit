"""
Data classes (schemas) used throughout the brazil_stocks package.

All monetary/ratio values are stored as Python floats; None represents missing data.
Dates are stored as datetime.date objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class Stock:
    """Basic identifying information for a B3-listed stock."""

    ticker: str                       # e.g. "PETR4"
    name: str = ""                    # Company name
    sector: str = ""                  # Sector / segment from fundamentus
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FundamentalSnapshot:
    """
    Fundamental metrics for a single ticker captured at a given date.

    Metric naming follows Brazilian market convention where applicable.
    All ratio values may be None when the data source does not provide them
    (e.g. negative earnings make P/L meaningless).
    """

    ticker: str
    snapshot_date: date

    # Valuation multiples
    pl: Optional[float] = None            # P/L  — Price-to-Earnings
    pvp: Optional[float] = None           # P/VP — Price-to-Book
    ev_ebitda: Optional[float] = None     # EV/EBITDA
    ev_ebit: Optional[float] = None       # EV/EBIT
    p_ebit: Optional[float] = None        # P/EBIT
    ps: Optional[float] = None            # P/Receita — Price-to-Sales

    # Income / profitability
    roe: Optional[float] = None           # ROE  (%, e.g. 0.18 = 18 %)
    roic: Optional[float] = None          # ROIC (Return on Invested Capital, %)
    gross_margin: Optional[float] = None  # Margem Bruta (%)
    ebit_margin: Optional[float] = None   # Margem EBIT / Operacional (%)
    net_margin: Optional[float] = None    # Margem Líquida (%)

    # Capital structure / liquidity
    debt_equity: Optional[float] = None   # Dívida Líquida / Patrimônio
    current_ratio: Optional[float] = None # Liquidez Corrente
    book_value: Optional[float] = None    # Patrimônio Líquido (absolute, BRL)
    net_debt: Optional[float] = None      # Net debt (BRL)
    ebitda: Optional[float] = None        # TTM EBITDA (BRL)
    net_debt_ebitda: Optional[float] = None  # Net Debt / EBITDA
    liquidity_2m: Optional[float] = None  # Avg daily traded volume, 2 months (BRL)

    # Yield / shareholder returns
    dy: Optional[float] = None            # Dividend Yield (%)
    payout: Optional[float] = None        # Payout ratio (dividends / net income)
    dividend_cagr_5y: Optional[float] = None  # 5-year dividend CAGR

    # Current market price used to compute the snapshot
    price: Optional[float] = None

    # ---- Growth-analysis support (populated by MetricsCalculator) -----
    eps_ttm: Optional[float] = None       # Trailing-12-month EPS
    revenue_ttm: Optional[float] = None   # Trailing-12-month revenue (absolute)
    revenue_growth_5y: Optional[float] = None  # 5-year revenue CAGR (from Fundamentus)

    # ---- Free-cash-flow support (populated from yfinance cash-flow stmt) ----
    fcf_ttm: Optional[float] = None       # Trailing-12-month free cash flow (BRL)
    fcf_per_share: Optional[float] = None # FCF per share (BRL)

    # ---- Intrinsic-value / quality (populated by DCFValuator, QualityScorer) ----
    intrinsic_value: Optional[float] = None   # DCF intrinsic value per share (BRL)
    margin_of_safety: Optional[float] = None  # (intrinsic_value - price) / intrinsic_value
    quality_score: Optional[float] = None     # Composite quality score (0-1)
    moat_score: Optional[float] = None        # Competitive-advantage proxy (0-1)

    # ---- Price-based factors (populated by FactorAnalyzer from price_history) ----
    momentum_12_1: Optional[float] = None     # 12-month total return, skipping the last month
    momentum_6_1: Optional[float] = None      # 6-month total return, skipping the last month
    volatility_6m: Optional[float] = None     # Annualised realised volatility, trailing ~6 months
    dist_52w_high: Optional[float] = None      # Price / trailing-52-week high (1.0 = at the high)



@dataclass
class PriceBar:
    """OHLCV daily price bar for a ticker."""

    ticker: str
    date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None


@dataclass
class ZScoreResult:
    """
    Z-score values for one ticker / metric / date combination.

    time_series_zscore:
        How many standard deviations the current metric value lies from the
        stock's own historical mean over *window_years* years.
        Negative → cheaper / lower than its own history.

    cross_sectional_zscore:
        How many standard deviations the stock's metric lies from the
        contemporaneous market (or sector) mean on *snapshot_date*.
        Negative → cheaper / lower than peers on that day.
    """

    ticker: str
    snapshot_date: date
    metric: str                                 # e.g. "pl", "pvp", "ev_ebitda"
    time_series_zscore: Optional[float] = None
    cross_sectional_zscore: Optional[float] = None
    window_years: int = 5                       # rolling window used for time-series z-score
