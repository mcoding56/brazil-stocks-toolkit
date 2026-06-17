"""
Fetch the current IBOV (Ibovespa) index composition from B3.

Primary source: BMF/Bovespa public page (no auth, real-time composition).
Fallback: hard-coded list of ~90 stocks that are typically in the index.
"""

from __future__ import annotations

import io
import logging
import re
from typing import List

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_BVMF_URL = (
    "https://bvmf.bmfbovespa.com.br/indices/ResumoCarteiraTeorica.aspx"
    "?Indice=IBOV&idioma=pt-br"
)

# Hard-coded fallback — typical IBOV composition (as of Q2 2026).
# Refreshed when B3 publishes each quarterly revision.
_IBOV_FALLBACK: List[str] = [
    "ABEV3", "ALPA4", "ARZZ3", "ASAI3", "AZUL4",
    "B3SA3", "BBAS3", "BBDC3", "BBDC4", "BBSE3",
    "BEEF3", "BPAC11", "BRAP4", "BRFS3", "BRKM5",
    "CASH3", "CCRO3", "CIEL3", "CMIG4", "CMIN3",
    "COGN3", "CPFE3", "CPLE6", "CRFB3", "CSAN3",
    "CSNA3", "CVCB3", "CYRE3", "DXCO3", "ECOR3",
    "EGIE3", "ELET3", "ELET6", "EMBR3", "ENEV3",
    "ENGI11", "EQTL3", "EZTC3", "FLRY3",
    "GGBR4", "GOAU4", "GOLL4", "HAPV3", "HYPE3",
    "IGTI11", "IRBR3", "ITSA4", "ITUB4",
    "JBSS3", "JHSF3", "KLBN11", "LREN3", "LWSA3",
    "MGLU3", "MRFG3", "MRVE3", "MULT3", "NTCO3",
    "PCAR3", "PETR3", "PETR4", "PETZ3", "PRIO3",
    "PSSA3", "RADL3", "RAIZ4", "RDOR3", "RENT3",
    "RRRP3", "SANB11", "SBSP3", "SLCE3", "SMTO3",
    "SOMA3", "STBP3", "SUZB3", "TAEE11", "TIMS3",
    "TOTS3", "UGPA3", "USIM5", "VALE3", "VBBR3",
    "VIVT3", "WEGE3", "YDUQ3",
]

_TICKER_RE = re.compile(r"^[A-Z]{4}\d{1,2}$")


def get_ibov_tickers(use_fallback_on_error: bool = True) -> List[str]:
    """
    Return the list of IBOV component tickers (without the ``.SA`` suffix).

    Tries to fetch the live composition from B3's public page.  If that fails
    (network error, page structure changed, etc.) and *use_fallback_on_error*
    is ``True``, the hard-coded fallback list is returned instead.

    Parameters
    ----------
    use_fallback_on_error:
        Whether to silently fall back to the hard-coded list on fetch errors.

    Returns
    -------
    List[str]
        Tickers such as ``["ABEV3", "PETR4", …]``.
    """
    try:
        tickers = _fetch_live()
        if tickers:
            logger.info("IBOV: fetched %d tickers from B3", len(tickers))
            return tickers
        logger.warning("IBOV: live fetch returned empty list; using fallback")
    except Exception as exc:
        logger.warning("IBOV: live fetch failed (%s); using fallback", exc)

    if use_fallback_on_error:
        return list(_IBOV_FALLBACK)

    raise RuntimeError("Could not fetch IBOV composition and fallback is disabled")


def _fetch_live() -> List[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    resp = requests.get(_BVMF_URL, headers=headers, timeout=15)
    resp.raise_for_status()

    tables = pd.read_html(io.StringIO(resp.text))
    # The composition table has columns: Código, Ação, Tipo, Qtde. Teórica, Part.
    for t in tables:
        cols_lower = [str(c).lower() for c in t.columns]
        if any("código" in c or "codigo" in c for c in cols_lower):
            ticker_col = next(
                c for c, cl in zip(t.columns, cols_lower)
                if "código" in cl or "codigo" in cl
            )
            raw = t[ticker_col].dropna().astype(str).str.strip().str.upper()
            tickers = [t for t in raw if _TICKER_RE.match(t)]
            if tickers:
                return tickers

    return []
