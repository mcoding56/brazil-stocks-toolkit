"""
DCFValuator
===========
Two-stage Discounted Cash Flow (DCF) intrinsic-value estimation, following the
Damodaran framework adapted for the Brazilian (BRL) market.

Method
------
1. Start from trailing-12-month Free Cash Flow (FCF) per share.
2. Project FCF forward for ``projection_years`` at a fading growth rate that
   converges from an initial growth estimate toward the perpetual
   ``terminal_growth`` rate.
3. Discount each projected year at the nominal BRL discount rate
   (``discount_rate``, a proxy for WACC / cost of equity).
4. Add a Gordon-growth terminal value at the end of the explicit horizon.
5. Sum discounted cash flows → intrinsic value per share.

Margin of safety
----------------
    margin_of_safety = (intrinsic_value - price) / intrinsic_value

A positive margin means the market price sits below estimated intrinsic value
(Graham's core idea: only buy with a meaningful discount).

Caveats
-------
* DCF is highly sensitive to growth and discount-rate assumptions; treat the
  output as one input among many, not a precise figure.
* Companies with negative FCF cannot be valued this way — the valuator returns
  ``None`` and the rest of the pipeline continues unaffected.
* Default assumptions (13 % nominal discount, 4 % terminal growth) are rough
  long-run BRL proxies and should be revisited as macro conditions change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Default BRL macro assumptions (nominal). See module docstring caveats.
DEFAULT_DISCOUNT_RATE = 0.13      # ~ nominal cost of equity in BRL
DEFAULT_TERMINAL_GROWTH = 0.04    # ~ long-run nominal GDP + inflation proxy
DEFAULT_PROJECTION_YEARS = 10
MAX_INITIAL_GROWTH = 0.25         # cap on the first-year growth assumption
MIN_INITIAL_GROWTH = -0.05        # floor (allow modest decline)


@dataclass
class DCFResult:
    """Outcome of a single-ticker DCF valuation."""

    ticker: str
    intrinsic_value: Optional[float]      # equity value per share, BRL
    margin_of_safety: Optional[float]     # (IV - price) / IV
    price: Optional[float]
    assumed_growth: Optional[float]       # initial growth rate used
    discount_rate: float
    terminal_growth: float
    enterprise_value: Optional[float] = None  # firm value per share, pre net-debt


class DCFValuator:
    """
    Estimate intrinsic value per share via a two-stage DCF.

    Parameters
    ----------
    discount_rate : float
        Nominal annual discount rate (WACC / cost-of-equity proxy). Default 13 %.
    terminal_growth : float
        Perpetual growth rate after the explicit projection horizon. Default 4 %.
    projection_years : int
        Number of explicitly projected years. Default 10.
    """

    def __init__(
        self,
        discount_rate: float = DEFAULT_DISCOUNT_RATE,
        terminal_growth: float = DEFAULT_TERMINAL_GROWTH,
        projection_years: int = DEFAULT_PROJECTION_YEARS,
    ) -> None:
        if discount_rate <= terminal_growth:
            raise ValueError(
                "discount_rate must exceed terminal_growth for a finite valuation."
            )
        self.discount_rate = discount_rate
        self.terminal_growth = terminal_growth
        self.projection_years = projection_years

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def value_share(
        self,
        ticker: str,
        fcf_per_share: Optional[float],
        price: Optional[float] = None,
        growth_rate: Optional[float] = None,
        net_debt_per_share: Optional[float] = None,
    ) -> DCFResult:
        """
        Compute intrinsic value per share and margin of safety for one ticker.

        The projected free cash flow is treated as **free cash flow to the firm**
        (operating cash flow minus capex, i.e. before debt service), so the
        present value of those flows is an *enterprise* value per share. To obtain
        the per-share **equity** value we apply the standard Damodaran bridge:

            equity_value_per_share = enterprise_value_per_share - net_debt_per_share

        Parameters
        ----------
        ticker : plain B3 ticker.
        fcf_per_share : trailing FCF (to firm) per share (BRL). None/<=0 → no valuation.
        price : current market price (BRL) for margin-of-safety calculation.
        growth_rate : initial annual FCF growth estimate (decimal, e.g. 0.10).
            When None, falls back to the terminal growth rate (conservative).
        net_debt_per_share : net debt per share (BRL). When provided it is
            subtracted from the enterprise value; negative net debt (net cash)
            correctly *increases* equity value. When None, no bridge is applied
            (enterprise value is used as-is — less correct for levered firms).
        """
        enterprise = self._intrinsic_value(fcf_per_share, growth_rate)
        iv = enterprise
        if enterprise is not None and net_debt_per_share is not None:
            iv = enterprise - net_debt_per_share
            if iv <= 0:  # debt claim exceeds firm value → equity worthless here
                iv = None
        mos = self._margin_of_safety(iv, price)
        return DCFResult(
            ticker=ticker,
            intrinsic_value=iv,
            margin_of_safety=mos,
            price=price,
            assumed_growth=self._clamp_growth(growth_rate),
            discount_rate=self.discount_rate,
            terminal_growth=self.terminal_growth,
            enterprise_value=enterprise,
        )

    # ------------------------------------------------------------------
    # Core math
    # ------------------------------------------------------------------

    def _intrinsic_value(
        self,
        fcf_per_share: Optional[float],
        growth_rate: Optional[float],
    ) -> Optional[float]:
        """Two-stage DCF with linearly fading growth toward terminal growth."""
        if fcf_per_share is None or fcf_per_share <= 0:
            return None

        g0 = self._clamp_growth(growth_rate)
        r = self.discount_rate
        gt = self.terminal_growth
        n = self.projection_years

        pv_sum = 0.0
        fcf = float(fcf_per_share)
        last_fcf = fcf
        for year in range(1, n + 1):
            # Growth fades linearly from g0 (year 1) to gt (year n)
            frac = (year - 1) / max(n - 1, 1)
            g = g0 + (gt - g0) * frac
            fcf = fcf * (1 + g)
            pv_sum += fcf / ((1 + r) ** year)
            last_fcf = fcf

        # Gordon-growth terminal value on the final projected FCF
        terminal_value = last_fcf * (1 + gt) / (r - gt)
        pv_terminal = terminal_value / ((1 + r) ** n)

        iv = pv_sum + pv_terminal
        return float(iv) if iv > 0 else None

    @staticmethod
    def _margin_of_safety(
        intrinsic_value: Optional[float], price: Optional[float]
    ) -> Optional[float]:
        if intrinsic_value is None or not intrinsic_value or price is None:
            return None
        return float((intrinsic_value - price) / intrinsic_value)

    def _clamp_growth(self, growth_rate: Optional[float]) -> float:
        """Bound the initial growth assumption to a sane range."""
        if growth_rate is None:
            return self.terminal_growth
        return float(max(MIN_INITIAL_GROWTH, min(MAX_INITIAL_GROWTH, growth_rate)))
