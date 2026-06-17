"""Z-Score Explorer page: per-metric ranking, heatmap and composite."""
from __future__ import annotations

import streamlit as st

from app import charts
from app import data as appdata
from app import ui

st.set_page_config(page_title="Z-Score Explorer · Brazil Stocks", page_icon="📊", layout="wide")

ui.page_header(
    "📊 Cheap vs. history — the Z-Score Explorer",
    "A simple 'how unusual is this price?' tool. It shows whether a stock is cheap "
    "compared to its own past and to its peers right now.",
)
ui.approach_banner(
    "Is this stock unusually cheap versus its own history and its peers?",
    "statistical / mean-reversion investing",
    "A z-score of 0 is perfectly normal; −2 means unusually cheap, +2 unusually "
    "expensive. Bargains often sit at the negative end and tend to drift back to "
    "normal over time.",
)
ui.learn_link()

st.sidebar.header("Settings")
score_type = st.sidebar.radio(
    "Compare against…",
    ["time_series_zscore", "cross_sectional_zscore"],
    format_func=lambda s: "Its own history (over time)"
    if s == "time_series_zscore" else "Its peers (right now)",
)
top_n = st.sidebar.slider("Tickers in heatmap", 10, 60, 25, step=5)

tab_metric, tab_heatmap, tab_composite = st.tabs(
    ["Single metric", "Heatmap", "Composite ranking"]
)

with tab_metric:
    metric = st.selectbox(
        "Metric",
        ui.ZSCORE_METRICS,
        format_func=lambda m: ui.METRIC_LABELS.get(m, m),
    )
    ui.metric_explainer(metric)
    ui.metric_explainer(score_type)
    ascending = metric in ui.LOWER_IS_CHEAPER
    rank = appdata.zscore_ranking(
        metric=metric, score_type=score_type, top_n=top_n, ascending=ascending
    )
    if rank.empty:
        st.info("No Z-scores available for this metric.")
    else:
        st.plotly_chart(
            charts.hbar_ranking(
                rank, value_col=score_type, label_col="ticker",
                title=f"{ui.METRIC_LABELS.get(metric, metric)} — Z-score",
                value_title="Z-score",
            ),
            use_container_width=True,
        )
        ui.styled_table(rank)

with tab_heatmap:
    matrix = appdata.heatmap_data(
        metrics=ui.ZSCORE_METRICS, score_type=score_type, top_n=top_n
    )
    if matrix.empty:
        st.info("Not enough data to build a heatmap.")
    else:
        matrix = matrix.rename(columns=ui.METRIC_LABELS)
        st.plotly_chart(
            charts.heatmap(matrix, title="Z-score heatmap (cheapest first)"),
            use_container_width=True,
        )

with tab_composite:
    comp = appdata.composite_ranking(metrics=None, score_type=score_type)
    if comp.empty:
        st.info("No composite scores available.")
    else:
        st.plotly_chart(
            charts.hbar_ranking(
                comp.head(top_n), value_col="composite_zscore", label_col="ticker",
                title="Composite Z-score (lower = cheaper across all metrics)",
                value_title="Composite Z-score",
            ),
            use_container_width=True,
        )
        ui.styled_table(appdata.attach_overall_score(comp.head(top_n)))
