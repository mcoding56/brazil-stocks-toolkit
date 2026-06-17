"""Export a slim, read-only copy of the full database for the web dashboard.

The full ``data/brazil_stocks.db`` is ~124 MB (mostly daily ``price_history``),
which is too large to commit to GitHub. This script writes
``data/brazil_stocks_slim.db`` containing only what the Streamlit app needs:

* ``stocks``                — all rows (tiny)
* ``fundamental_snapshots`` — latest snapshot date only
* ``zscore_results``        — latest snapshot date only
* ``price_history``         — IBOV constituents, most recent ~2 years

It then VACUUMs the slim DB so it compresses to a few MB.

Run from the repo root::

    python scripts/export_slim_db.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brazil_stocks.fetchers.ibov import get_ibov_tickers
from brazil_stocks.storage.database import DatabaseManager

SRC_PATH = Path("data/brazil_stocks.db")
DEST_PATH = Path("data/brazil_stocks_slim.db")
PRICE_HISTORY_YEARS = 2


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def main() -> None:
    if not SRC_PATH.exists():
        raise SystemExit(f"Source DB not found: {SRC_PATH.resolve()}")

    src = DatabaseManager(SRC_PATH)
    print("Source summary:", src.summary())

    latest_snap = src.query(
        "SELECT MAX(snapshot_date) AS m FROM fundamental_snapshots"
    ).iloc[0, 0]
    latest_z = src.query(
        "SELECT MAX(snapshot_date) AS m FROM zscore_results"
    ).iloc[0, 0]
    print(f"Latest fundamental snapshot: {latest_snap}")
    print(f"Latest z-score snapshot:     {latest_z}")

    # ------------------------------------------------------------------
    # Pull the slim subsets
    # ------------------------------------------------------------------
    stocks = src.query("SELECT * FROM stocks")
    snapshots = src.query(
        "SELECT * FROM fundamental_snapshots WHERE snapshot_date = ?",
        [latest_snap],
    )
    zscores = src.query(
        "SELECT * FROM zscore_results WHERE snapshot_date = ?",
        [latest_z],
    )

    ibov = get_ibov_tickers()
    cutoff = (date.today() - timedelta(days=365 * PRICE_HISTORY_YEARS)).isoformat()
    placeholders = ",".join("?" for _ in ibov)
    prices = src.query(
        f"""
        SELECT * FROM price_history
         WHERE ticker IN ({placeholders}) AND date >= ?
         ORDER BY ticker, date
        """,
        [*ibov, cutoff],
    )

    print(
        f"Slim rows -> stocks={len(stocks)}, snapshots={len(snapshots)}, "
        f"zscores={len(zscores)}, prices={len(prices)} "
        f"({prices['ticker'].nunique() if not prices.empty else 0} IBOV tickers, "
        f">= {cutoff})"
    )
    filled = (stocks["sector"].fillna("").str.len() > 0).sum() if not stocks.empty else 0
    print(f"Sectors populated on stocks: {filled}/{len(stocks)}")

    # ------------------------------------------------------------------
    # Write the slim DB (fresh schema via DatabaseManager, then append rows)
    # ------------------------------------------------------------------
    if DEST_PATH.exists():
        DEST_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        side = DEST_PATH.with_name(DEST_PATH.name + suffix)
        if side.exists():
            side.unlink()

    dest = DatabaseManager(DEST_PATH)  # creates empty schema + migrations
    conn = dest._conn

    def _append(df: pd.DataFrame, table: str) -> None:
        if df.empty:
            print(f"  (skip {table}: no rows)")
            return
        cols = set(_table_columns(conn, table))
        # Drop autoincrement id so SQLite assigns fresh ones; keep only known cols.
        keep = [c for c in df.columns if c in cols and c != "id"]
        df[keep].to_sql(table, conn, if_exists="append", index=False)

    _append(stocks, "stocks")
    _append(snapshots, "fundamental_snapshots")
    _append(zscores, "zscore_results")
    _append(prices, "price_history")
    conn.commit()

    # Compact the file.
    conn.execute("PRAGMA wal_checkpoint(FULL)")
    conn.execute("VACUUM")
    conn.commit()

    print("Slim summary:", dest.summary())

    size_mb = DEST_PATH.stat().st_size / (1024 * 1024)
    print(f"Wrote {DEST_PATH} ({size_mb:.1f} MB)")

    src.close()
    dest.close()


if __name__ == "__main__":
    main()
