# Roadmap — Brazil Stocks Valuation Toolkit

A living backlog the agent maintains. When an item is completed, check it off and add the
date. When a new idea emerges, append it under "Next up" or "Ideas / backlog".

## Done

- [x] Surface previously-scraped Fundamentus fields (ROIC, gross/EBIT margins, P/EBIT,
      EV/EBIT, current ratio, book value) through the schema, DB and snapshots — 2026-06
- [x] Free-cash-flow fetch from yfinance cash-flow statement (`fetch_fcf_ttm`) and
      dividend history / 5y dividend CAGR (`fetch_dividend_cagr`) — 2026-06
- [x] Two-stage DCF intrinsic value + margin of safety (`analysis/dcf.py`) — 2026-06
- [x] Quality & moat composite scoring via percentile ranks (`analysis/quality.py`) — 2026-06
- [x] Master quality-value screen `screen_graham_buffett` and
      `get_intrinsic_value_ranking` in the orchestrator — 2026-06
- [x] Extend Z-score universe to the new profitability/leverage/multiple metrics — 2026-06
- [x] **Net-debt/EBITDA**: derive EBITDA from EV and EV/EBITDA and populate
      `ebitda` / `net_debt_ebitda` in the valuation step — 2026-06
- [x] **DCF equity bridge**: subtract net debt per share from the FCFF DCF so levered
      names no longer show inflated intrinsic value; fixed net-debt 100× scaling bug — 2026-06
- [x] **Exclude financials + liquidity floor**: `exclude_financials` / `min_liquidity`
      on the screens (banks excluded from FCFF DCF, illiquid microcaps filtered);
      `liquidity_2m` surfaced from Fundamentus, sector enriched from yfinance — 2026-06
- [x] **DB persistence / multi-source refresh**: `DatabaseManager.backup()` and
      `orchestrator.update_database()` for repeatable dated refreshes — 2026-06
- [x] **Momentum & low-volatility factors** (`analysis/factors.py`): 12-1 momentum,
      6-1 momentum, realised vol and distance-to-52w-high computed from stored prices;
      added as a first-class 20%-weight pillar of the Claude Screen — 2026-06
- [x] **Walk-forward momentum backtest** (`analysis/backtest.py` + `orchestrator
      .backtest_momentum`): point-in-time, no-look-ahead validation of the momentum
      pillar with quantile equity curves; surfaced in notebook + dashboard page 7.
      Full-DB result: top-vs-bottom long-short spread CAGR ~18%, Sharpe ~0.84;
      bottom-momentum basket −12% CAGR / −60% drawdown (the value trap) — 2026-06

## Next up (highest value first)

- [ ] **CVM share-buyback & insider signal** (`dados.cvm.gov.br`): daily
      `cia_aberta-eventos-recompra_acoes` repurchase programs + insider transactions as a
      "smart money" factor; also use official DFP/ITR statements to replace flaky yfinance.
- [ ] **BCB macro-regime overlay** (SGS / `dadosabertos.bcb.gov.br`): SELIC + Focus market
      expectations to flag the rate regime and tilt sector exposure (rates dominate B3).
- [ ] **Piotroski F-Score** (9-point) and **Greenblatt Magic Formula** (earnings yield ×
      ROIC) as additional, already-computable fundamental factors.
- [ ] **Payout ratio**: populate `payout` from dividends / net income and add a
      dividend-quality sub-screen (sustainable payout + rising dividends).
- [ ] **Reverse DCF**: back out the growth rate the current price implies, to flag names
      pricing in implausible growth.
- [ ] **Sector-relative scoring**: default `QualityScorer(sector_neutral=True)` and make
      the master screen sector-aware to avoid banking/utility skew.
- [ ] **Per-sector / dynamic discount rate**: replace the flat 13 % WACC with a
      configurable per-sector (or CDI-linked) discount rate.
- [ ] **Margin stability**: use multi-period statements to score gross/net margin
      *stability* (a stronger moat signal than point-in-time level).

## Ideas / backlog

- [ ] Piotroski F-score (9-point fundamental health checklist).
- [ ] Greenwald Earnings Power Value (EPV) as a DCF cross-check.
- [ ] Altman Z-score (distress / bankruptcy risk) as a quality penalty.
- [ ] Owner-earnings (Buffett) variant of FCF: net income + D&A − maintenance capex.
- [ ] Sensitivity tables / tornado charts for DCF assumptions in the notebook.
- [ ] Cache yfinance statements to disk to speed up repeated valuation runs.
- [ ] Backtest: do high quality_score + high margin_of_safety names outperform IBOV?
