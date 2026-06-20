"""
FundamentusFetcher
==================
Scrapes `https://www.fundamentus.com.br/resultado.php` to retrieve current
fundamental data for ALL B3-listed equities in a single request.

Columns returned by `fetch()`
------------------------------
ticker, name, sector, price, pl, pvp, ps, ev_ebitda,
dy, roe, net_margin, debt_equity

Notes
-----
- fundamentus returns values already formatted for Brazilian locale
  (dots as thousands separators, commas as decimal separators, and
  percentage signs). The parser handles all of these.
- Rows for FIIs (real-estate funds) and BDRs can optionally be excluded
  via `include_fiis` and `include_bdrs` constructor parameters.
- A custom `User-Agent` is sent to avoid trivial bot-blocking; no login is required.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Optional

import pandas as pd
import requests

from brazil_stocks.fetchers.base import BaseFetcher
from brazil_stocks.models.schemas import FundamentalSnapshot, Stock

logger = logging.getLogger(__name__)

_URL = "https://www.fundamentus.com.br/resultado.php"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.fundamentus.com.br/",
}
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0

# Map fundamentus Portuguese column headers → our internal names
# (these match the actual <th> text returned by the current site as of 2025-2026)
_COLUMN_MAP = {
    "Papel":               "ticker",
    "Cotação":             "price",
    "P/L":                 "pl",
    "P/VP":                "pvp",
    "PSR":                 "ps",
    "Div.Yield":           "dy",
    "P/Ativo":             "p_ativo",
    "P/Cap.Giro":          "p_cap_giro",
    "P/EBIT":              "p_ebit",
    "P/Ativ Circ.Liq":     "p_acl",
    "EV/EBIT":             "ev_ebit",
    "EV/EBITDA":           "ev_ebitda",
    "Mrg Bruta":           "gross_margin",
    "Mrg Ebit":            "ebit_margin",
    "Mrg. Líq.":           "net_margin",
    "Liq. Corr.":          "current_ratio",
    "ROIC":                "roic",
    "ROE":                 "roe",
    "Liq.2meses":          "liquidity_2m",
    "Patrim. Líq":         "book_value",
    "Dív.Líq/ Patrim.":    "debt_equity",   # net debt / equity
    "Cresc. Rec.5a":       "revenue_growth_5y",
    # legacy / alternative spellings kept for backwards compatibility
    "Nome":                "name",
    "Setor":               "sector",
    "Tipo":                "type",
    "P/Ativ.Circ.Liq":     "p_acl",
    "Mrg.Líq.":            "net_margin",
    "Liq.Corr.":           "current_ratio",
    "Patrim.Líq":          "book_value",
    "Dív.Brut/Patrim.":    "debt_equity",
    "Cresc.Rec.5a":        "revenue_growth_5y",
}


def _br_to_float(val) -> Optional[float]:
    """Convert a Brazilian-locale string such as '1.234,56' or '12,34%' to float.

    If *val* is already numeric (int / float / numpy scalar), it is returned
    directly — pd.read_html with ``decimal=','`` already handled the conversion
    for non-percentage cells, so we must NOT strip the decimal point again.
    """
    if val is None:
        return None
    # Already numeric — return as-is (avoids the "3.55" → "355" bug)
    try:
        import numpy as _np
        if isinstance(val, (_np.integer, _np.floating)):
            f = float(val)
            return None if _np.isnan(f) else f
    except ImportError:
        pass
    if isinstance(val, (int, float)):
        import math
        return None if math.isnan(float(val)) else float(val)
    # String path: strip % sign, fix Brazilian locale separators
    s = str(val).strip().replace("%", "").replace(".", "").replace(",", ".")
    if s in ("", "-", "?"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


class FundamentusFetcher(BaseFetcher):
    """
    Fetches current fundamentals for all B3 equities from fundamentus.com.br.

    Parameters
    ----------
    include_fiis : bool
        Whether to include Fundos de Investimento Imobiliário (FIIs).
        Default False — FII P/L semantics differ from equities.
    include_bdrs : bool
        Whether to include Brazilian Depositary Receipts. Default False.
    timeout : int
        HTTP request timeout in seconds. Default 30.
    """

    def __init__(
        self,
        include_fiis: bool = False,
        include_bdrs: bool = False,
        timeout: int = 30,
    ) -> None:
        self.include_fiis = include_fiis
        self.include_bdrs = include_bdrs
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, **kwargs) -> pd.DataFrame:
        """
        Download and return fundamentals for all B3-listed equities.

        Returns
        -------
        pd.DataFrame
            Columns: ticker, name, sector, price, pl, pvp, ps, ev_ebitda,
                     dy, roe, net_margin, debt_equity, snapshot_date
        """
        raw_df = self._download()
        if raw_df.empty:
            logger.warning("FundamentusFetcher: empty payload returned; continuing with no new fundamentals.")
            return pd.DataFrame(columns=[
                "ticker", "name", "sector", "price",
                "pl", "pvp", "ps", "ev_ebitda", "ev_ebit", "p_ebit",
                "dy", "roe", "roic", "gross_margin", "ebit_margin", "net_margin",
                "debt_equity", "current_ratio", "book_value", "liquidity_2m",
                "revenue_growth_5y", "snapshot_date",
            ])
        df = self._clean(raw_df)
        df["snapshot_date"] = date.today().isoformat()
        logger.info("FundamentusFetcher: %d equities fetched", len(df))
        return df

    def to_stocks(self, df: pd.DataFrame) -> list[Stock]:
        """Convert a fetched DataFrame to a list of Stock dataclass instances."""
        stocks = []
        for _, row in df.iterrows():
            stocks.append(
                Stock(
                    ticker=row["ticker"],
                    name=row.get("name", ""),
                    sector=row.get("sector", ""),
                )
            )
        return stocks

    def to_snapshots(self, df: pd.DataFrame) -> list[FundamentalSnapshot]:
        """Convert a fetched DataFrame to FundamentalSnapshot instances."""
        snapshots = []
        today = date.today()
        for _, row in df.iterrows():
            snapshots.append(
                FundamentalSnapshot(
                    ticker=row["ticker"],
                    snapshot_date=today,
                    pl=row.get("pl"),
                    pvp=row.get("pvp"),
                    ev_ebitda=row.get("ev_ebitda"),
                    ev_ebit=row.get("ev_ebit"),
                    p_ebit=row.get("p_ebit"),
                    ps=row.get("ps"),
                    roe=row.get("roe"),
                    roic=row.get("roic"),
                    gross_margin=row.get("gross_margin"),
                    ebit_margin=row.get("ebit_margin"),
                    net_margin=row.get("net_margin"),
                    debt_equity=row.get("debt_equity"),
                    current_ratio=row.get("current_ratio"),
                    book_value=row.get("book_value"),
                    liquidity_2m=row.get("liquidity_2m"),
                    dy=row.get("dy"),
                    price=row.get("price"),
                    revenue_growth_5y=row.get("revenue_growth_5y"),
                )
            )
        return snapshots

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _download(self) -> pd.DataFrame:
        """POST to fundamentus and parse the HTML table."""
        import io as _io

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                # The result page requires a POST with an empty payload (or default
                # filter values) to return the full list of stocks.
                resp = requests.post(
                    _URL,
                    data={},
                    headers=_HEADERS,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                # Fundamentus serves ISO-8859-1; let requests decode correctly
                resp.encoding = resp.apparent_encoding or "iso-8859-1"

                # Newer pandas/lxml requires a file-like object, not a raw HTML string
                tables = pd.read_html(
                    _io.StringIO(resp.text),
                    decimal=",",
                    thousands=".",
                    flavor="lxml",
                )
                if not tables:
                    logger.warning(
                        "Fundamentus _download attempt %d/%d returned no tables.",
                        attempt,
                        _MAX_RETRIES,
                    )
                else:
                    # The first (and usually only) table holds the data
                    return tables[0]
            except Exception as exc:
                logger.warning(
                    "Fundamentus _download attempt %d/%d failed: %s",
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY * attempt)

        logger.warning("Fundamentus _download exhausted retries; returning empty DataFrame.")
        return pd.DataFrame()

    def _clean(self, raw: pd.DataFrame) -> pd.DataFrame:
        # Rename columns we recognise
        raw = raw.rename(columns={c: _COLUMN_MAP.get(c, c) for c in raw.columns})

        # Add placeholder columns if the site doesn't expose them
        for col in ("name", "sector"):
            if col not in raw.columns:
                raw[col] = ""

        # Keep only known useful columns that are present
        desired = [
            "ticker", "name", "sector", "price",
            "pl", "pvp", "ps", "ev_ebitda", "ev_ebit", "p_ebit",
            "dy", "roe", "roic",
            "gross_margin", "ebit_margin", "net_margin",
            "debt_equity", "current_ratio", "book_value",
            "liquidity_2m", "revenue_growth_5y",
        ]
        present = [c for c in desired if c in raw.columns]
        df = raw[present].copy()

        # Ensure ticker is a clean string
        df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()

        # Filter out non-equity rows (header repetitions, empty rows)
        df = df[df["ticker"].str.match(r"^[A-Z]{4}\d{1,2}$", na=False)]

        # Optionally drop FIIs (tickers ending in 11 are predominantly FIIs)
        if not self.include_fiis:
            df = df[~df["ticker"].str.endswith("11")]

        # Optionally drop BDRs (tickers ending in 32, 33, 34, 35)
        if not self.include_bdrs:
            df = df[~df["ticker"].str.match(r".*3[2345]$")]

        # Convert numeric columns from Brazilian locale to float
        # (percentage columns like "37,74%" are still strings at this point)
        numeric_cols = [c for c in present if c not in ("ticker", "name", "sector")]
        for col in numeric_cols:
            df[col] = df[col].apply(_br_to_float)

        df = df.reset_index(drop=True)
        return df
