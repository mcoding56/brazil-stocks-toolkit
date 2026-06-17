---
mode: agent
description: Review progress, pick the next roadmap item, and implement an improvement.
---
# Research & improve

Act as the project's standing quant researcher for the Brazil Stocks Valuation Toolkit.

1. **Review state.** Read `AGENTS.md`, `.github/copilot-instructions.md`, and
   `docs/ROADMAP.md`. Skim `brazil_stocks/orchestrator.py` to see what screens exist.
2. **Pick one item.** Choose the highest-value, lowest-risk *unchecked* item from the
   "Next up" section of `docs/ROADMAP.md` (or propose a better one and add it there).
   Prefer changes that strengthen the Graham/Buffett/Damodaran/Greenwald valuation
   signal: intrinsic value accuracy, quality/moat robustness, growth durability, or
   margin-of-safety calibration.
3. **Implement** it following the metric-addition order in
   `add-valuation-metric.prompt.md` and the module instructions under
   `.github/instructions/`. Keep changes focused — no scope creep, no new heavy deps.
4. **Verify** with `python -c` smoke tests against a `:memory:` DB and `get_errors` on
   edited files. For pipeline changes, validate on ~5 IBOV tickers and confirm new DB
   columns populate.
5. **Update the roadmap.** Check off the completed item in `docs/ROADMAP.md` and append
   any new ideas you discovered while working.

Report back: what you changed, why it improves the valuation signal, how you verified it,
and what you recommend tackling next.
