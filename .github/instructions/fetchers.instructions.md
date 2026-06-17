---
applyTo: "brazil_stocks/fetchers/**"
---
# Fetcher module conventions

Fetchers retrieve raw data from external sources and normalise it into the dataclasses
in `models/schemas.py`. They must be resilient: external B3 data is frequently missing
or malformed.

## Rules

- `from __future__ import annotations`; subclass `base.BaseFetcher` and implement
  `fetch()` returning a normalised `pd.DataFrame`.
- B3 tickers are passed **without** the `.SA` suffix everywhere in the codebase; add the
  suffix only at the yfinance boundary (`_add_suffix` / `_strip_suffix`).
- Wrap every network call in retry logic and **return empty/`None` on failure** — never
  raise out to the caller. Log at `warning`/`debug`, do not crash the pipeline.
- Fundamentus (`fundamentus.py`):
  - Map Portuguese headers in `_COLUMN_MAP`; keep alternative spellings for resilience.
  - `_br_to_float` converts Brazilian locale and strips `%`, so percentages come out
    unscaled (`"18,0%"` → `18.0`). Do not re-scale here.
  - To surface a new scraped field, add it to the `desired` list in `_clean` **and** to
    `to_snapshots`.
- yfinance (`yfinance_client.py`): cash-flow and dividend data are spotty for B3 names.
  Helper methods (`fetch_fcf_ttm`, `fetch_dividend_cagr`) must return `None` when rows are
  missing so the orchestrator can skip valuation for that ticker.

## Verify

Fetchers hit the network, so prefer testing their *pure* helpers (`_clean`, `_br_to_float`,
`fetch_fcf_ttm` logic) on synthetic DataFrames. Run `get_errors` on edited files. When
validating live, use ~5 tickers and confirm the returned columns are populated.
