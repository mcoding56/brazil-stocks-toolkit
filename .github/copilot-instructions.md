# Brazil Stocks Toolkit — Copilot Instructions

A Python toolkit for quantitative valuation of Brazilian (B3) equities. It fetches
fundamentals and prices, stores them in SQLite, and computes Z-scores, growth,
quality/moat, and DCF intrinsic-value screens grounded in the Graham / Buffett /
Damodaran / Greenwald value-investing framework.

## Architecture (data flows in one direction)

```
fetchers/  →  storage/  →  analysis/  →  orchestrator.py  →  notebooks/
(raw data)    (SQLite)     (compute)     (facade/screens)    (presentation)
```

- `brazil_stocks/fetchers/` — data sources. `fundamentus.py` (all-B3 fundamentals via
  HTML scrape), `yfinance_client.py` (prices, quarterly statements, cash flow, dividends),
  `ibov.py` (index universe). All subclass `base.BaseFetcher`.
- `brazil_stocks/models/schemas.py` — plain `@dataclass` records: `Stock`,
  `FundamentalSnapshot`, `PriceBar`, `ZScoreResult`. This is the single source of truth
  for field names.
- `brazil_stocks/storage/database.py` — `DatabaseManager`, a thin SQLite wrapper. Holds
  the `_DDL`, idempotent column migrations, and `upsert_*` / `get_*` methods.
- `brazil_stocks/analysis/` — pure computation: `metrics.py` (historical P/E, P/S),
  `growth.py` (growth composite), `zscore.py` (time-series + cross-sectional Z-scores),
  `dcf.py` (`DCFValuator`), `quality.py` (`QualityScorer`).
- `brazil_stocks/orchestrator.py` — `StockAnalysisOrchestrator`, the facade that wires
  everything and exposes screens (`screen_quality_value`, `screen_graham_buffett`,
  `get_intrinsic_value_ranking`, `get_zscore_ranking`).

## Conventions to follow

- **Schemas first.** When adding a metric, update `FundamentalSnapshot` in `schemas.py`,
  then the `_DDL` **and** the migration list in `database.py._init_schema`, then the
  `upsert_fundamental_snapshots` rows + SQL (all `COALESCE`-guarded so partial updates
  never wipe existing values).
- **Idempotent migrations.** Never drop/recreate tables. Add columns via the
  `ALTER TABLE ADD COLUMN` loop guarded by `PRAGMA table_info`.
- **Graceful degradation.** External data (yfinance cash flow, dividends) is unreliable
  for many B3 tickers. Always return `None`/empty and let the pipeline continue; never
  raise out of an enrichment loop.
- **Units gotcha.** Fundamentus reports percentages as plain numbers (`roic=18.0` means
  18 %, not 0.18) because `_br_to_float` strips the `%`. Scale-invariant logic
  (percentile ranks, Z-scores) is preferred; divide by 100 only when feeding decimals to
  math like DCF growth.
- **Cross-sectional ranking** uses `.rank(pct=True)`; valuation ratios that are only
  meaningful when positive are listed in `_POSITIVE_ONLY_METRICS`.
- English for code, comments, and docs. Type hints + concise docstrings on public methods.
- `from __future__ import annotations` at the top of every module.

## Verification (no pytest suite — notebook/REPL driven)

- Smoke-test imports and math with `python -c "..."` against a `:memory:` `DatabaseManager`.
- Run `get_errors` on every edited file before considering a change done.
- For pipeline changes, validate on ~5 IBOV tickers and query the DB to confirm new
  columns populate (not all NULL).
- Sanity-check DCF outputs: intrinsic value positive, margin of safety in a plausible range.

## Do not

- Do not add a test framework, CI, or new heavy dependencies without being asked.
- Do not change existing metric units/semantics (it would corrupt stored history).
- Do not commit the SQLite DB under `data/` or large notebook outputs.
