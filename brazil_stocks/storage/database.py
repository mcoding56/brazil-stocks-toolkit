"""
DatabaseManager — SQLite persistence layer.

Tables
------
stocks               : master list of B3-listed tickers
fundamental_snapshots: point-in-time fundamental metrics per ticker
price_history        : daily OHLCV bars per ticker
zscore_results       : computed Z-scores per ticker/date/metric

Usage
-----
    from brazil_stocks.storage.database import DatabaseManager

    db = DatabaseManager("data/brazil_stocks.db")
    db.upsert_stocks(stocks_list)
    df = db.query("SELECT * FROM fundamental_snapshots WHERE ticker = ?", ["PETR4"])
"""

from __future__ import annotations

import sqlite3
import logging
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Generator, Iterable, List, Optional

import pandas as pd

from brazil_stocks.models.schemas import (
    FundamentalSnapshot,
    PriceBar,
    Stock,
    ZScoreResult,
)

logger = logging.getLogger(__name__)


_DDL = """
CREATE TABLE IF NOT EXISTS stocks (
    ticker      TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    sector      TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fundamental_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker            TEXT    NOT NULL,
    snapshot_date     TEXT    NOT NULL,
    pl                REAL,
    pvp               REAL,
    ev_ebitda         REAL,
    ev_ebit           REAL,
    p_ebit            REAL,
    ps                REAL,
    roe               REAL,
    roic              REAL,
    gross_margin      REAL,
    ebit_margin       REAL,
    net_margin        REAL,
    debt_equity       REAL,
    current_ratio     REAL,
    book_value        REAL,
    net_debt          REAL,
    ebitda            REAL,
    net_debt_ebitda   REAL,
    liquidity_2m      REAL,
    dy                REAL,
    payout            REAL,
    dividend_cagr_5y  REAL,
    price             REAL,
    eps_ttm           REAL,
    revenue_ttm       REAL,
    revenue_growth_5y REAL,
    fcf_ttm           REAL,
    fcf_per_share     REAL,
    intrinsic_value   REAL,
    margin_of_safety  REAL,
    quality_score     REAL,
    moat_score        REAL,
    UNIQUE (ticker, snapshot_date)
);

CREATE TABLE IF NOT EXISTS price_history (
    ticker  TEXT NOT NULL,
    date    TEXT NOT NULL,
    open    REAL,
    high    REAL,
    low     REAL,
    close   REAL,
    volume  REAL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS zscore_results (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                  TEXT    NOT NULL,
    snapshot_date           TEXT    NOT NULL,
    metric                  TEXT    NOT NULL,
    time_series_zscore      REAL,
    cross_sectional_zscore  REAL,
    window_years            INTEGER NOT NULL DEFAULT 5,
    UNIQUE (ticker, snapshot_date, metric, window_years)
);

CREATE INDEX IF NOT EXISTS idx_fs_ticker      ON fundamental_snapshots (ticker);
CREATE INDEX IF NOT EXISTS idx_fs_date        ON fundamental_snapshots (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_ph_ticker      ON price_history (ticker);
CREATE INDEX IF NOT EXISTS idx_zs_ticker_date ON zscore_results (ticker, snapshot_date);
"""


class DatabaseManager:
    """
    Thin wrapper around an SQLite database.

    Uses a single persistent connection (safe for single-threaded notebook use).
    Supports both file-based and ``:memory:`` databases.

    Parameters
    ----------
    db_path : str or Path
        Path to the SQLite file, or ``":memory:"`` for an in-memory database.
        Parent directories are created automatically for file-based paths.
    """

    def __init__(self, db_path: str | Path = "data/brazil_stocks.db") -> None:
        self.db_path = db_path if str(db_path) == ":memory:" else Path(db_path)
        if str(self.db_path) != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        """Explicitly close the underlying connection."""
        self._conn.close()

    def backup(self, dest_path: str | Path) -> Path:
        """Write a consistent copy of the database to *dest_path*.

        Checkpoints the WAL and uses SQLite's online backup API so it is safe
        to call while the connection is open. Returns the destination path.
        Not supported for ``:memory:`` source databases.
        """
        if str(self.db_path) == ":memory:":
            raise ValueError("Cannot back up an in-memory database")
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._conn.execute("PRAGMA wal_checkpoint(FULL)")
        with sqlite3.connect(str(dest)) as target:
            self._conn.backup(target)
        logger.info("Database backed up to %s", dest)
        return dest

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _init_schema(self) -> None:
        self._conn.executescript(_DDL)
        # Lightweight migration: add columns missing in older DB files
        existing = {r[1] for r in self._conn.execute(
            "PRAGMA table_info(fundamental_snapshots)"
        ).fetchall()}
        for col in (
            "eps_ttm", "revenue_ttm", "revenue_growth_5y",
            "ev_ebit", "p_ebit", "roic", "gross_margin", "ebit_margin",
            "current_ratio", "book_value", "net_debt", "ebitda",
            "net_debt_ebitda", "liquidity_2m", "payout", "dividend_cagr_5y",
            "fcf_ttm", "fcf_per_share", "intrinsic_value",
            "margin_of_safety", "quality_score", "moat_score",
        ):
            if col not in existing:
                self._conn.execute(
                    f"ALTER TABLE fundamental_snapshots ADD COLUMN {col} REAL"
                )
        self._conn.commit()
        logger.debug("Database schema initialised at %s", self.db_path)

    # ------------------------------------------------------------------
    # Generic query
    # ------------------------------------------------------------------

    def query(self, sql: str, params: Iterable = ()) -> pd.DataFrame:
        """Execute *sql* and return the result as a DataFrame."""
        return pd.read_sql_query(sql, self._conn, params=list(params))

    # ------------------------------------------------------------------
    # Stocks
    # ------------------------------------------------------------------

    def upsert_stocks(self, stocks: List[Stock]) -> int:
        """Insert or update stocks. Returns the number of rows affected."""
        rows = [
            (s.ticker, s.name, s.sector, s.updated_at.isoformat())
            for s in stocks
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO stocks (ticker, name, sector, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    name       = COALESCE(excluded.name, stocks.name),
                    sector     = COALESCE(excluded.sector, stocks.sector),
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        logger.debug("Upserted %d stocks", len(rows))
        return len(rows)

    def get_all_tickers(self) -> List[str]:
        """Return a sorted list of all known tickers."""
        df = self.query("SELECT ticker FROM stocks ORDER BY ticker")
        return df["ticker"].tolist()

    def update_sectors(self, mapping: dict) -> int:
        """Set the ``sector`` for existing tickers from ``{ticker: sector}``.

        Only updates rows that already exist and skips empty sectors so a
        missing value never wipes a previously-stored one. Returns the number
        of tickers updated.
        """
        rows = [(sector, ticker) for ticker, sector in mapping.items() if sector]
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                "UPDATE stocks SET sector = ? WHERE ticker = ?", rows
            )
        return len(rows)

    # ------------------------------------------------------------------
    # Fundamental snapshots
    # ------------------------------------------------------------------

    def upsert_fundamental_snapshots(
        self, snapshots: List[FundamentalSnapshot]
    ) -> int:
        rows = [
            (
                s.ticker,
                s.snapshot_date.isoformat() if isinstance(s.snapshot_date, date) else s.snapshot_date,
                s.pl,
                s.pvp,
                s.ev_ebitda,
                s.ev_ebit,
                s.p_ebit,
                s.ps,
                s.roe,
                s.roic,
                s.gross_margin,
                s.ebit_margin,
                s.net_margin,
                s.debt_equity,
                s.current_ratio,
                s.book_value,
                s.net_debt,
                s.ebitda,
                s.net_debt_ebitda,
                s.liquidity_2m,
                s.dy,
                s.payout,
                s.dividend_cagr_5y,
                s.price,
                s.eps_ttm,
                s.revenue_ttm,
                s.revenue_growth_5y,
                s.fcf_ttm,
                s.fcf_per_share,
                s.intrinsic_value,
                s.margin_of_safety,
                s.quality_score,
                s.moat_score,
            )
            for s in snapshots
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO fundamental_snapshots
                    (ticker, snapshot_date, pl, pvp, ev_ebitda, ev_ebit, p_ebit, ps,
                     roe, roic, gross_margin, ebit_margin, net_margin,
                     debt_equity, current_ratio, book_value, net_debt, ebitda,
                     net_debt_ebitda, liquidity_2m, dy, payout, dividend_cagr_5y, price,
                     eps_ttm, revenue_ttm, revenue_growth_5y,
                     fcf_ttm, fcf_per_share, intrinsic_value, margin_of_safety,
                     quality_score, moat_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, snapshot_date) DO UPDATE SET
                    pl                = COALESCE(excluded.pl, fundamental_snapshots.pl),
                    pvp               = COALESCE(excluded.pvp, fundamental_snapshots.pvp),
                    ev_ebitda         = COALESCE(excluded.ev_ebitda, fundamental_snapshots.ev_ebitda),
                    ev_ebit           = COALESCE(excluded.ev_ebit, fundamental_snapshots.ev_ebit),
                    p_ebit            = COALESCE(excluded.p_ebit, fundamental_snapshots.p_ebit),
                    ps                = COALESCE(excluded.ps, fundamental_snapshots.ps),
                    roe               = COALESCE(excluded.roe, fundamental_snapshots.roe),
                    roic              = COALESCE(excluded.roic, fundamental_snapshots.roic),
                    gross_margin      = COALESCE(excluded.gross_margin, fundamental_snapshots.gross_margin),
                    ebit_margin       = COALESCE(excluded.ebit_margin, fundamental_snapshots.ebit_margin),
                    net_margin        = COALESCE(excluded.net_margin, fundamental_snapshots.net_margin),
                    debt_equity       = COALESCE(excluded.debt_equity, fundamental_snapshots.debt_equity),
                    current_ratio     = COALESCE(excluded.current_ratio, fundamental_snapshots.current_ratio),
                    book_value        = COALESCE(excluded.book_value, fundamental_snapshots.book_value),
                    net_debt          = COALESCE(excluded.net_debt, fundamental_snapshots.net_debt),
                    ebitda            = COALESCE(excluded.ebitda, fundamental_snapshots.ebitda),
                    net_debt_ebitda   = COALESCE(excluded.net_debt_ebitda, fundamental_snapshots.net_debt_ebitda),
                    liquidity_2m      = COALESCE(excluded.liquidity_2m, fundamental_snapshots.liquidity_2m),
                    dy                = COALESCE(excluded.dy, fundamental_snapshots.dy),
                    payout            = COALESCE(excluded.payout, fundamental_snapshots.payout),
                    dividend_cagr_5y  = COALESCE(excluded.dividend_cagr_5y, fundamental_snapshots.dividend_cagr_5y),
                    price             = COALESCE(excluded.price, fundamental_snapshots.price),
                    eps_ttm           = COALESCE(excluded.eps_ttm, fundamental_snapshots.eps_ttm),
                    revenue_ttm       = COALESCE(excluded.revenue_ttm, fundamental_snapshots.revenue_ttm),
                    revenue_growth_5y = COALESCE(excluded.revenue_growth_5y, fundamental_snapshots.revenue_growth_5y),
                    fcf_ttm           = COALESCE(excluded.fcf_ttm, fundamental_snapshots.fcf_ttm),
                    fcf_per_share     = COALESCE(excluded.fcf_per_share, fundamental_snapshots.fcf_per_share),
                    intrinsic_value   = COALESCE(excluded.intrinsic_value, fundamental_snapshots.intrinsic_value),
                    margin_of_safety  = COALESCE(excluded.margin_of_safety, fundamental_snapshots.margin_of_safety),
                    quality_score     = COALESCE(excluded.quality_score, fundamental_snapshots.quality_score),
                    moat_score        = COALESCE(excluded.moat_score, fundamental_snapshots.moat_score)
                """,
                rows,
            )
        logger.debug("Upserted %d fundamental snapshots", len(rows))
        return len(rows)

    def get_fundamental_snapshots(
        self,
        ticker: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Return fundamental snapshots optionally filtered by ticker and date range.

        Parameters
        ----------
        ticker     : filter to a single ticker (None = all tickers)
        start_date : ISO date string lower bound inclusive
        end_date   : ISO date string upper bound inclusive
        """
        conditions, params = [], []
        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker)
        if start_date:
            conditions.append("snapshot_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("snapshot_date <= ?")
            params.append(end_date)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        return self.query(
            f"SELECT * FROM fundamental_snapshots {where} ORDER BY ticker, snapshot_date",
            params,
        )

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def upsert_price_bars(self, bars: List[PriceBar]) -> int:
        rows = [
            (
                b.ticker,
                b.date.isoformat() if isinstance(b.date, date) else b.date,
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
            )
            for b in bars
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO price_history (ticker, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, date) DO UPDATE SET
                    open   = excluded.open,
                    high   = excluded.high,
                    low    = excluded.low,
                    close  = excluded.close,
                    volume = excluded.volume
                """,
                rows,
            )
        logger.debug("Upserted %d price bars", len(rows))
        return len(rows)

    def get_price_history(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        conditions = ["ticker = ?"]
        params: list = [ticker]
        if start_date:
            conditions.append("date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date)
        where = "WHERE " + " AND ".join(conditions)
        return self.query(
            f"SELECT * FROM price_history {where} ORDER BY date",
            params,
        )

    # ------------------------------------------------------------------
    # Z-score results
    # ------------------------------------------------------------------

    def upsert_zscore_results(self, results: List[ZScoreResult]) -> int:
        rows = [
            (
                r.ticker,
                r.snapshot_date.isoformat() if isinstance(r.snapshot_date, date) else r.snapshot_date,
                r.metric,
                r.time_series_zscore,
                r.cross_sectional_zscore,
                r.window_years,
            )
            for r in results
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO zscore_results
                    (ticker, snapshot_date, metric, time_series_zscore,
                     cross_sectional_zscore, window_years)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, snapshot_date, metric, window_years) DO UPDATE SET
                    time_series_zscore     = excluded.time_series_zscore,
                    cross_sectional_zscore = excluded.cross_sectional_zscore
                """,
                rows,
            )
        logger.debug("Upserted %d Z-score results", len(rows))
        return len(rows)

    def get_zscore_results(
        self,
        snapshot_date: Optional[str] = None,
        metric: Optional[str] = None,
        ticker: Optional[str] = None,
    ) -> pd.DataFrame:
        conditions, params = [], []
        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker)
        if snapshot_date:
            conditions.append("snapshot_date = ?")
            params.append(snapshot_date)
        if metric:
            conditions.append("metric = ?")
            params.append(metric)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        return self.query(
            f"SELECT * FROM zscore_results {where} ORDER BY ticker, metric",
            params,
        )

    # ------------------------------------------------------------------
    # Convenience summary
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Return row counts for each table."""
        tables = ["stocks", "fundamental_snapshots", "price_history", "zscore_results"]
        return {
            t: self.query(f"SELECT COUNT(*) AS n FROM {t}").iloc[0]["n"]
            for t in tables
        }
