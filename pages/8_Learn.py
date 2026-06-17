"""Learn — a plain-English guide to the dashboard, the scores and the legends."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import ui

st.set_page_config(page_title="Learn · Brazil Stocks", page_icon="📚", layout="wide")

ui.page_header(
    "📚 Learn — the plain-English guide",
    "No finance degree required. Here's what every page, score and colour means.",
)

# ---------------------------------------------------------------------------
# A. The five investing legends
# ---------------------------------------------------------------------------
st.subheader("The ideas behind the dashboard")
st.write(
    "This toolkit applies the playbook of five of the most respected value "
    "investors in history. Each page below answers one simple question using "
    "their approach."
)
legends = pd.DataFrame(
    [{"Investor": name, "Their idea in one line": idea, "Where you'll see it": page}
     for name, idea, page in ui.INVESTOR_LEGENDS]
).set_index("Investor")
st.dataframe(legends, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# B. Which page answers which question
# ---------------------------------------------------------------------------
st.subheader("Pick your question")
questions = pd.DataFrame(
    [
        {"Your question": "Is a stock cheaper than it's really worth?",
         "Page": "💰 Fair Value", "Approach": "Buffett · Damodaran"},
        {"Your question": "Is it a good business at a fair price?",
         "Page": "🏆 Quality-Value Screen", "Approach": "Graham · Buffett"},
        {"Your question": "Is it cheap versus its own past and its peers?",
         "Page": "📊 Cheap vs. History", "Approach": "Statistics / mean-reversion"},
        {"Your question": "Is it a great, durable business?",
         "Page": "🛡️ Great Business?", "Approach": "Buffett · Greenwald"},
        {"Your question": "Is it cheap AND growing fast?",
         "Page": "🌱 Cheap AND Growing", "Approach": "Peter Lynch"},
        {"Your question": "Tell me everything about one stock.",
         "Page": "🔎 One-Stock Deep Dive", "Approach": "—"},
        {"Your question": "Blend every signal — what comes out on top?",
         "Page": "🧠 All-In-One Ranking", "Approach": "Multi-factor"},
    ]
).set_index("Your question")
st.dataframe(questions, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# C. What the scores mean (plain language, no formulas)
# ---------------------------------------------------------------------------
st.subheader("What the scores mean")

c1, c2 = st.columns(2)
with c1:
    st.markdown(
        "**Cheap vs. expensive**  \n"
        "We compare a company's price to its profits, sales, book value and cash "
        "flow. 'Cheap' means you pay little for each R$1 the business earns."
    )
    st.markdown(
        "**Margin of safety**  \n"
        "How big a discount the price is to our estimate of what the company is "
        "truly worth. A 30% margin of safety means it's trading 30% below fair "
        "value — a cushion if we're wrong."
    )
    st.markdown(
        "**Quality**  \n"
        "How good the business is at turning money into more money — high returns "
        "on capital, fat profit margins and low debt."
    )
    st.markdown(
        "**Moat**  \n"
        "A durable competitive advantage (brand, scale, switching costs) that lets "
        "a company defend high profits for years. Buffett's favourite trait."
    )
with c2:
    st.markdown(
        "**Growth**  \n"
        "How fast revenue and earnings are rising. Worth most when the business "
        "also earns good returns on the capital it reinvests."
    )
    st.markdown(
        "**Momentum**  \n"
        "Whether the share price has been trending up. Historically, recent "
        "winners tend to keep winning for a while."
    )
    st.markdown(
        "**Z-score**  \n"
        "A simple 'how unusual is this?' number. 0 = perfectly average; −2 = "
        "unusually cheap; +2 = unusually expensive. We use it to compare a stock "
        "to its own history and to its peers."
    )
    st.markdown(
        "**Price vs. VWAP**  \n"
        "Whether the price today sits below or above the average price most shares "
        "actually traded at over the last two years. Below = potential bargain."
    )

st.divider()

# ---------------------------------------------------------------------------
# D. How to read the colours
# ---------------------------------------------------------------------------
st.subheader("How to read the colours & verdicts")
st.markdown(
    "Across the dashboard we use the same simple colour scale:\n\n"
    "- 🟢 **Green** — cheap / strong / good value\n"
    "- ⚪ **White / grey** — fairly priced or average\n"
    "- 🔴 **Red** — expensive / weak / risky\n"
)
st.markdown(
    "Some tables also show a one-glance **Verdict** badge that blends *cheapness* "
    "and *business quality*:"
)
st.markdown(
    "- 🟢 **Cheap & high-quality** — the sweet spot\n"
    "- 🟡 **Great business, pricey** — wonderful company, wait for a better price\n"
    "- ⚠️ **Cheap but weak** — a possible value trap; cheap for a reason\n"
    "- 🔴 **Looks expensive** — paying up versus the fundamentals\n"
)

st.divider()

# ---------------------------------------------------------------------------
# E. The full reference glossary (formulas + definitions)
# ---------------------------------------------------------------------------
st.subheader("Full metric glossary")
st.caption("Want the exact formulas? Everything is here.")
ui.metric_glossary(expanded=True)

st.divider()
st.info(
    "This is a research and learning tool, not investment advice. All figures are "
    "model estimates from public data and can be wrong or out of date.",
    icon="ℹ️",
)
