# Brazil Stocks — Value-Investing Dashboard

A Python toolkit and interactive web dashboard for the **quantitative valuation of
Brazilian (B3) equities**. It fetches fundamentals and prices, stores them in SQLite,
and computes Z-scores, growth, quality/moat, and DCF intrinsic-value screens grounded
in the Graham / Buffett / Damodaran / Greenwald value-investing framework.

## What it does

```
fetchers/  →  storage/  →  analysis/  →  orchestrator.py  →  streamlit_app.py
(raw data)    (SQLite)     (compute)     (facade/screens)    (web dashboard)
```

1. **Fetch** fundamentals for the whole B3 universe (Fundamentus) plus prices,
   quarterly statements, cash flow and dividends (yfinance).
2. **Store** everything in a local SQLite database (`data/brazil_stocks.db`).
3. **Compute** valuation signals: historical multiples, growth, cross-sectional and
   time-series Z-scores, free cash flow, DCF intrinsic value + margin of safety, and
   quality/moat scores.
4. **Screen & visualize** quality-at-a-reasonable-price candidates in a browser.

## The web dashboard

The Streamlit app exposes every screen and chart interactively:

| Page | What it shows |
|------|---------------|
| **Overview** | Database summary, snapshot date, headline top picks, methodology |
| **Intrinsic Value (DCF)** | Margin-of-safety ranking with liquidity / financials filters |
| **Master Screen** | Graham-Buffett 7-pillar composite `master_score` |
| **Claude Screen** | Reliability-weighted composite `claude_score` (percentile-ranked pillars: quality 30 / safety 20 / valuation 20 / moat 15 / growth 15) |
| **Z-Score Explorer** | Per-metric ranking + cross-ticker heatmap + composite |
| **Quality & Moat** | Quality vs. moat scatter and scorecard |
| **GARP** | Value × growth 4-quadrant screen |
| **Stock Profile** | Single-ticker fundamentals, Z-scores, P/L history, live DCF |

### Run the dashboard locally

```powershell
pip install -r requirements.txt
# The app reads data/brazil_stocks_slim.db (a few MB, committed to the repo).
streamlit run streamlit_app.py
```

The home page shows the latest snapshot date and a refresh panel. On Streamlit
Community Cloud, the refresh button updates the running app instance. If you want
the committed dashboard data to stay fresh between restarts, run a scheduled
GitHub Action that rebuilds and commits `data/brazil_stocks_slim.db`.

### Keep Streamlit Cloud data updated automatically

This repo includes a scheduled workflow at
`.github/workflows/refresh-dataset.yml` that:

1. Runs every weekday after market close (22:45 UTC)
2. Refreshes the full local DB via `update_database()`
3. Rebuilds `data/brazil_stocks_slim.db`
4. Commits and pushes the slim DB only when it changed

Enable it in GitHub:

1. Open **Actions** tab and allow workflows for the repository
2. Open **Refresh Streamlit Dataset** workflow
3. Click **Run workflow** once to seed and verify
4. Confirm the commit reaches `master` and Streamlit Cloud auto-redeploys

### Regenerate the slim database (optional)

The app ships with a pre-built read-only `data/brazil_stocks_slim.db`. To rebuild it
from a full `data/brazil_stocks.db` (e.g. after a fresh pipeline run):

```powershell
python scripts/export_slim_db.py
```

## Run the full data pipeline (heavy)

```python
from brazil_stocks.orchestrator import StockAnalysisOrchestrator

orc = StockAnalysisOrchestrator(db_path="data/brazil_stocks.db")
orc.run_full_pipeline(tickers=["PETR4", "VALE3", "ITUB4", "WEGE3", "ABEV3"])

orc.get_intrinsic_value_ranking(top_n=20)             # cheapest vs DCF
orc.screen_graham_buffett(min_margin_of_safety=0.2)   # master quality-value screen
```

A full B3 refresh (`orc.update_database()`) fetches ~940 equities plus prices and is
slow (15–30 min). The web app exposes a manual refresh button for the running
Streamlit instance, but the durable way to keep Streamlit Cloud up to date is a
scheduled rebuild of the committed slim database.

## Deploy free on Streamlit Community Cloud

1. Push this repository to a **public** GitHub repo.
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub.
3. Click **New app**, pick this repo/branch, set the main file to `streamlit_app.py`.
4. Click **Deploy**. The app installs `requirements.txt` and reads the committed
   `data/brazil_stocks_slim.db`.

> Need a **private** deployment? Use a
> [Hugging Face Space](https://huggingface.co/spaces) with the *Streamlit* SDK instead —
> the same `streamlit_app.py` works there.

## Notebook

`notebooks/brazil_stocks_analysis.ipynb` walks through the full pipeline and the original
matplotlib/seaborn analyses. The web app is the interactive successor to those cells.

## Project layout

```
brazil_stocks/      core toolkit (fetchers, storage, analysis, orchestrator)
app/                dashboard data layer + Plotly chart helpers
pages/              Streamlit multipage UI
scripts/            maintenance scripts (slim DB export)
data/               SQLite databases (slim DB committed; full DB git-ignored)
notebooks/          exploratory analysis notebook
docs/               roadmap and design notes
```

See `AGENTS.md` and `.github/copilot-instructions.md` for architecture and conventions.
