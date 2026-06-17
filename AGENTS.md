# AGENTS.md — Brazil Stocks Valuation Toolkit

Guidance for AI agents (and humans) working in this repository. The goal of this
project is to rank B3-listed companies by **intrinsic value and business quality**,
not just price action — applying the value-investing framework of Benjamin Graham,
Warren Buffett, Aswath Damodaran and Bruce Greenwald to Brazilian equities.

## What the project does

1. **Fetch** current fundamentals for the whole B3 universe (Fundamentus) plus prices,
   quarterly statements, cash flow and dividends (yfinance).
2. **Store** everything in a local SQLite database (`data/brazil_stocks.db`).
3. **Compute** valuation signals: historical multiples, growth, cross-sectional and
   time-series Z-scores, free cash flow, DCF intrinsic value + margin of safety, and
   quality/moat scores.
4. **Screen** for quality-at-a-reasonable-price candidates.

## The valuation pillars (the "why" behind each module)

| Pillar (Graham/Buffett/Damodaran/Greenwald) | Where it lives |
|---|---|
| Future cash flow → intrinsic value (DCF)    | `analysis/dcf.py` (`DCFValuator`) |
| Sustainable earnings/revenue growth         | `analysis/growth.py` (`GrowthAnalyzer`) |
| Return on capital (ROIC, ROE)               | `quality.py` + Fundamentus fields |
| Low leverage (net-debt/equity, coverage)    | `quality.py`, snapshot fields |
| Stable, wide margins (gross/EBIT/net)       | `quality.py` |
| Competitive advantage ("moat")              | `quality.py` (`moat_score`) |
| Market multiples (P/L, P/VP, EV/EBITDA…)    | `analysis/zscore.py` |
| Free cash flow                              | `fetchers/yfinance_client.fetch_fcf_ttm` |
| Dividends (yield, payout, growth)           | `fetchers/yfinance_client.fetch_dividend_cagr` |
| Margin of safety                            | `dcf.py` (`margin_of_safety`) |

The master synthesis lives in `orchestrator.screen_graham_buffett`.

## Architecture & conventions

See `.github/copilot-instructions.md` for the full architecture map and coding
conventions. Key rules in brief:

- One-directional flow: `fetchers → storage → analysis → orchestrator → notebooks`.
- Add a metric in this order: `schemas.py` → `database.py` (DDL + migration + upsert) →
  fetcher/analyzer → orchestrator → notebook.
- Migrations are additive and idempotent. Never recreate tables.
- Fundamentus percentages are unscaled (`18.0` = 18 %). Prefer scale-invariant logic.
- Enrichment loops must degrade gracefully to `None` on missing external data.

## How to run

```python
from brazil_stocks.orchestrator import StockAnalysisOrchestrator

orc = StockAnalysisOrchestrator(db_path="data/brazil_stocks.db")
orc.run_full_pipeline(tickers=["PETR4", "VALE3", "ITUB4", "WEGE3", "ABEV3"])

orc.get_intrinsic_value_ranking(top_n=20)        # cheapest vs DCF
orc.screen_graham_buffett(min_margin_of_safety=0.2)  # master quality-value screen
```

## Verification

No pytest. Validate with `python -c` smoke tests against an in-memory DB, run
`get_errors` on edited files, then confirm new DB columns populate on a small
ticker sample. Sanity-check DCF/quality outputs for plausible ranges.

## Roadmap

Open improvement ideas are tracked in `docs/ROADMAP.md`. When you complete an item,
check it off there; when you discover a new idea, append it.
