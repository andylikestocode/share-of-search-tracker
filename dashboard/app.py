"""
Share of Search Dashboard — Streamlit.

Reads artifacts/ files (committed to repo by the GitHub Action).
Deploy free at share.streamlit.io.
"""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"

st.set_page_config(
    page_title="BRUNT Share of Search",
    page_icon="🥾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Fraunces:wght@400;600;900&display=swap');
  html, body, [class*="css"] {
    font-family: 'JetBrains Mono', monospace;
    background-color: #0a0a0a;
    color: #e5e5e5;
  }
  h1, h2, h3 {
    font-family: 'Fraunces', serif;
    color: #fff;
    letter-spacing: -0.02em;
  }
  h1 { font-weight: 900; }
  .stMetric {
    background: #141414;
    padding: 1.2rem;
    border-radius: 4px;
    border-left: 3px solid #ff6b00;
  }
  [data-testid="stMetricValue"] {
    font-family: 'Fraunces', serif;
    font-size: 2rem;
    color: #ff6b00;
  }
  [data-testid="stMetricLabel"] {
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 0.1em;
    color: #888;
  }
  .stApp { background-color: #0a0a0a; }
  hr { border-color: #222; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=600)
def load():
    sos = pd.read_csv(ART / "sos_history.csv")
    sos["date"] = pd.to_datetime(sos["date"])
    trade = pd.read_csv(ART / "trade_opportunity.csv")
    cat = pd.read_csv(ART / "category_summary.csv")
    cat["date"] = pd.to_datetime(cat["date"])
    return sos, trade, cat


st.markdown("# BRUNT / Share of Search")
st.markdown(
    '<p style="color:#666; margin-top:-1rem; font-size:0.9rem;">'
    'Monthly competitive brand search demand · Powered by Google Keyword Planner'
    '</p>',
    unsafe_allow_html=True,
)
st.markdown("---")

try:
    sos, trade, cat = load()
except FileNotFoundError:
    st.error("No data found. Run the pipeline first (push a CSV to /data).")
    st.stop()

# --- Sidebar ---
with st.sidebar:
    st.markdown("### Filters")
    all_comps = sorted(sos["competitor"].unique())
    default = [c for c in all_comps if c in ("brunt", "carhartt", "timberland_pro", "red_wing", "truewerk")]
    selected = st.multiselect("Competitors", all_comps, default=default)

df = sos[sos["competitor"].isin(selected)] if selected else sos

# --- KPIs ---
latest_date = sos["date"].max()
latest = sos[sos["date"] == latest_date]
brunt = latest[latest["competitor"] == "brunt"]

if not brunt.empty:
    b = brunt.iloc[0]
    rank = (latest["sos_pct"] > b["sos_pct"]).sum() + 1
    c1, c2, c3, c4 = st.columns(4)
    mom = b.get("sos_mom_delta")
    c1.metric("BRUNT SoS", f"{b['sos_pct']:.1f}%", f"{mom:+.2f} pts MoM" if pd.notna(mom) else None)
    c2.metric("Rank", f"#{rank}", f"of {len(latest)}")
    yoy = b.get("sos_yoy_delta")
    c3.metric("YoY", f"{yoy:+.2f} pts" if pd.notna(yoy) else "—")
    c4.metric("Latest Month", latest_date.strftime("%b %Y"))

st.markdown("---")

# --- Trendline ---
st.markdown("### SoS Trendline")
palette = {
    "brunt": "#ff6b00",
    "carhartt": "#c9a961",
    "timberland_pro": "#8b6f47",
    "red_wing": "#b94646",
    "thorogood": "#6b8e6b",
    "wolverine": "#7a7a7a",
    "keen_utility": "#5b8aa6",
    "danner": "#9b6b3d",
    "georgia_boot": "#8b5a3c",
    "ariat_work": "#a67c52",
    "truewerk": "#4a90a4",
}

fig = go.Figure()
for comp in df["competitor"].unique():
    sub = df[df["competitor"] == comp].sort_values("date")
    is_brunt = comp == "brunt"
    fig.add_trace(go.Scatter(
        x=sub["date"], y=sub["sos_pct"], name=comp, mode="lines+markers",
        line=dict(color=palette.get(comp, "#888"), width=3 if is_brunt else 1.5),
        marker=dict(size=6 if is_brunt else 4),
        opacity=1.0 if is_brunt else 0.7,
    ))
fig.update_layout(
    plot_bgcolor="#0a0a0a", paper_bgcolor="#0a0a0a",
    font=dict(family="JetBrains Mono", color="#e5e5e5"),
    xaxis=dict(showgrid=False, color="#888"),
    yaxis=dict(title="Share of Search (%)", gridcolor="#1a1a1a", color="#888"),
    height=480, hovermode="x unified",
    legend=dict(orientation="h", y=-0.2),
    margin=dict(l=20, r=20, t=20, b=20),
)
st.plotly_chart(fig, use_container_width=True)

# --- Standings + trade opportunities ---
col_left, col_right = st.columns([1, 1])
with col_left:
    st.markdown("### Latest Standings")
    disp = latest.sort_values("sos_pct", ascending=False)[
        ["competitor", "sos_pct", "sos_mom_delta", "sos_yoy_delta"]
    ].rename(columns={
        "competitor": "Brand",
        "sos_pct": "SoS %",
        "sos_mom_delta": "MoM Δ",
        "sos_yoy_delta": "YoY Δ",
    })
    st.dataframe(disp, use_container_width=True, hide_index=True)

with col_right:
    st.markdown("### Trade Keyword Opportunity")
    st.caption("BRUNT's wedge — where tradespeople search")
    trade_disp = trade.head(11).rename(columns={
        "keyword": "Keyword",
        "avg_monthly_searches": "Searches/mo",
    })
    trade_disp["Searches/mo"] = trade_disp["Searches/mo"].astype(int).map("{:,}".format)
    st.dataframe(trade_disp, use_container_width=True, hide_index=True)

# --- Category mix ---
st.markdown("---")
st.markdown("### Category Demand Pool")
st.caption("Total search volume in each category, by month")

cat_pivot = cat.pivot(index="date", columns="category", values="avg_monthly_searches").fillna(0)
fig2 = go.Figure()
cat_colors = {
    "branded": "#ff6b00",
    "generic_work_boots": "#888",
    "trade_specific": "#c9a961",
    "feature_use_case": "#5b8aa6",
    "consideration": "#b94646",
    "workwear_adjacency": "#6b8e6b",
}
for c in cat_pivot.columns:
    fig2.add_trace(go.Bar(
        x=cat_pivot.index, y=cat_pivot[c], name=c,
        marker_color=cat_colors.get(c, "#666"),
    ))
fig2.update_layout(
    barmode="stack", plot_bgcolor="#0a0a0a", paper_bgcolor="#0a0a0a",
    font=dict(family="JetBrains Mono", color="#e5e5e5"),
    xaxis=dict(showgrid=False, color="#888"),
    yaxis=dict(gridcolor="#1a1a1a", color="#888"),
    height=360, legend=dict(orientation="h", y=-0.2),
    margin=dict(l=20, r=20, t=10, b=20),
)
st.plotly_chart(fig2, use_container_width=True)
