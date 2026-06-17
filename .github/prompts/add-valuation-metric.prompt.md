---
mode: agent
description: Add a new fundamental/valuation metric end-to-end through the pipeline.
---
# Add a valuation metric

Add a new metric named `${input:metric:metric field name (snake_case)}` to the toolkit,
wired all the way through the one-directional pipeline. Follow the project conventions in
`.github/copilot-instructions.md` and `.github/instructions/analysis.instructions.md`.

Work in this exact order and verify after each layer:

1. **Schema** — add the field to `FundamentalSnapshot` in
   `brazil_stocks/models/schemas.py` with a short unit comment.
2. **Storage** — in `brazil_stocks/storage/database.py`:
   - add the column to `_DDL`,
   - add it to the idempotent migration list in `_init_schema`,
   - add it to the `upsert_fundamental_snapshots` row tuple, the `INSERT` column list,
     and the `COALESCE`-guarded `ON CONFLICT … DO UPDATE` block.
3. **Source/compute** — populate it in the relevant fetcher (`fetchers/`) or analyzer
   (`analysis/`). Degrade gracefully to `None` on missing data.
4. **Orchestrator** — surface it in a screen or ranking in `orchestrator.py` if relevant.
5. **Z-score (optional)** — if it should be ranked statistically, append it to
   `FUNDAMENTAL_METRICS` (and `_POSITIVE_ONLY_METRICS` if positive-only) in
   `analysis/zscore.py`.

Remember: Fundamentus percentages are unscaled (`18.0` = 18 %). Prefer scale-invariant
logic; divide by 100 only when feeding decimals into math like DCF growth.

**Verify:** run `python -c "..."` against a `:memory:` `DatabaseManager` with a couple of
hand-built snapshots, run `get_errors` on every edited file, and confirm the new column
is populated (not all NULL). Do not add a test framework or new dependencies.
