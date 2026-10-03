"""History — pick-vs-ASI scoreboard with a comparison chart."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from components import api_get, empty_state, naira0


def _comparison_chart(perfs: list[dict]):
    labels, mine, asi = [], [], []
    for p in perfs:
        legs = [l for l in p.get("legs", []) if "return_pct" in l]
        if "asi_return_pct" not in p or not legs:
            continue
        avg = sum(l["return_pct"] for l in legs) / len(legs)
        labels.append(p["month"])
        mine.append(round(avg, 2))
        asi.append(p["asi_return_pct"])
    if not labels:
        return None
    fig = go.Figure()
    fig.add_bar(x=labels, y=mine, name="My picks (avg)", marker_color="#00D395")
    fig.add_bar(x=labels, y=asi, name="NGX ASI", marker_color="#5A6372")
    fig.update_layout(barmode="group", height=300, margin=dict(t=10, b=10, l=10, r=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font_color="#E8ECF1", yaxis_title="% since pick")
    return fig


def render() -> None:
    st.markdown("### Track record — you vs the market")
    st.caption("Every saved pick, measured against the NGX All-Share Index from the day it was made.")

    picks_data, err = api_get("/picks")
    picks = (picks_data or {}).get("picks", []) if picks_data else []
    if err or not picks:
        empty_state("No history yet",
                    "Generate your first pick in <b>This Month</b> and this page starts keeping score.")
        return

    perfs = []
    for p in picks:
        pr, _ = api_get(f"/picks/{p['month']}/performance")
        if pr and "error" not in pr:
            perfs.append(pr)
    fig = _comparison_chart(perfs)
    if fig:
        st.plotly_chart(fig, use_container_width=True)

    for p in picks:
        legs = " + ".join(f"{l['symbol']} ×{l['units']}" for l in p.get("picks", []))
        pr = next((x for x in perfs if x["month"] == p["month"]), {})
        line = ""
        if "asi_return_pct" in pr:
            legs_ret = [l for l in pr.get("legs", []) if "return_pct" in l]
            if legs_ret:
                avg = sum(l["return_pct"] for l in legs_ret) / len(legs_ret)
                line = f" · you {avg:+.1f}% vs ASI {pr['asi_return_pct']:+.1f}%"
        st.markdown(
            f'<div class="card"><h4>{p["month"]} — {legs}</h4>'
            f'<div class="muted">{naira0(p.get("cash"))} deployed{line}</div></div>',
            unsafe_allow_html=True)
