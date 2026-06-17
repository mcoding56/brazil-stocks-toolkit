---
applyTo: "brazil_stocks/analysis/**"
---
# Analysis module conventions

These modules are **pure computation** — they read from `DatabaseManager` and return
DataFrames or dataclass results. They must not fetch from the network directly (that is
the fetchers' job; the orchestrator wires fetchers to analyzers).

## Rules

- `from __future__ import annotations` at the top; type-hint all public methods.
- Each analyzer takes a `DatabaseManager` (and optionally a fetcher) in its constructor.
- Expose a `compute_*` method that returns a DataFrame and a `compute_and_store` /
  `compute_all` method that persists results via `db.upsert_*`.
- Handle NaN/None gracefully: stocks with insufficient data get `None`/`NaN`, never an
  exception. Never let one ticker break a batch loop.
- Prefer **scale-invariant** statistics (`.rank(pct=True)`, Z-scores). Remember
  Fundamentus reports percentages unscaled (`roic=18.0` means 18 %).
- Valuation ratios that are only meaningful when positive belong in
  `_POSITIVE_ONLY_METRICS` (see `zscore.py`).
- DCF (`dcf.py`): keep growth assumptions clamped; `discount_rate` must exceed
  `terminal_growth`; return `None` for non-positive FCF rather than guessing.
- Quality (`quality.py`): components are percentile-ranked; "lower is better" metrics
  go in `_INVERT_METRICS`; weights live in `QUALITY_WEIGHTS` / `MOAT_WEIGHTS`.

## When adding a new metric

1. Add the field to `models/schemas.py` (`FundamentalSnapshot`).
2. Add the column to `storage/database.py` `_DDL`, the migration list, and the
   `upsert_fundamental_snapshots` rows + COALESCE SQL.
3. Compute it here, then surface it in `orchestrator.py`.
4. If it should be Z-scored, append it to `FUNDAMENTAL_METRICS` in `zscore.py`.

## Verify

`python -c "..."` against a `:memory:` DB with a few hand-built snapshots, then run
`get_errors` on the edited files.
