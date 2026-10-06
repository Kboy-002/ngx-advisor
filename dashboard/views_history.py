"""History — pick-vs-ASI scoreboard with a comparison chart."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from components import api_get, api_post, empty_state, naira0


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
    if not labels or all(v == 0 for v in mine) and all(v == 0 for v in asi):
        return None  # nothing has moved yet — caller shows the waiting state
    fig = go.Figure()
    fig.add_bar(x=labels, y=mine, name="My picks (avg)", marker_color="#00D395")
    fig.add_bar(x=labels, y=asi, name="NGX ASI", marker_color="#5A6372")
    fig.update_layout(barmode="group", height=300, margin=dict(t=10, b=10, l=10, r=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font_color="#E8ECF1", yaxis_title="% since pick")
    fig.update_xaxes(type="category")  # "2026-10" is a label, not a date
    fig.update_yaxes(ticksuffix="%", zeroline=True, zerolinecolor="#2A3348")
    return fig


CHART_CONFIG = {"displayModeBar": False}  # legend stays readable, no icon clutter


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
        st.plotly_chart(fig, use_container_width=True, config=CHART_CONFIG)
    else:
        st.info("Scoreboard starts counting from each pick's day — prices haven't moved since the "
                "latest pick, so there's nothing to compare yet. Check back after the market moves.")

    for p in picks:
        legs = " + ".join(f"{l['symbol']} ×{l['units']}" for l in p.get("picks", []))
        pr = next((x for x in perfs if x["month"] == p["month"]), {})
        line = ""
        if "asi_return_pct" in pr:
            legs_ret = [l for l in pr.get("legs", []) if "return_pct" in l]
            if legs_ret:
                avg = sum(l["return_pct"] for l in legs_ret) / len(legs_ret)
                if avg == 0 and pr["asi_return_pct"] == 0:
                    line = " · made today — tracking from today's prices"
                else:
                    line = f" · you {avg:+.1f}% vs ASI {pr['asi_return_pct']:+.1f}%"
        st.markdown(
            f'<div class="card"><h4>{p["month"]} — {legs}</h4>'
            f'<div class="muted">{naira0(p.get("cash"))} deployed{line}</div></div>',
            unsafe_allow_html=True)

    st.divider()
    with st.expander("Log an off-system (gut) trade — keep the record honest"):
        st.caption("Bought on a tip outside the machine? Log it here. It gets scored against the ASI "
                   "like everything else — no shame, just data.")
        gc1, gc2, gc3 = st.columns(3)
        with gc1:
            gsym = st.text_input("Ticker", placeholder="GTCO").upper()
            gunits = st.number_input("Units", min_value=0.0, value=0.0, step=1.0)
        with gc2:
            gprice = st.number_input("Buy price (₦)", min_value=0.0, value=0.0, step=0.5)
            gdate = st.date_input("Buy date")
        with gc3:
            gnote = st.text_input("Why? (one line)", placeholder="Heard it at lunch")
        if st.button("Log gut trade"):
            if gsym and gunits > 0 and gprice > 0:
                res, err = api_post("/gut", json={"trade_date": str(gdate), "symbol": gsym,
                                                  "units": gunits, "price": gprice, "note": gnote})
                if err or not (res or {}).get("ok"):
                    st.error("Couldn't save it — try again.")
                else:
                    st.success("Logged. The scoreboard is watching.")
                    st.rerun()
            else:
                st.warning("Ticker, units and price are all required.")
    guts, _ = api_get("/gut")
    for g in (guts or {}).get("guts", []):
        perf = (f" · {g['return_pct']:+.1f}% (now ₦{g['now_price']:,.2f})"
                if "return_pct" in g else " · awaiting prices")
        st.markdown(
            f'<div class="card verdict PAUSE"><h4>🎲 {g["symbol"]} ×{g["units"]:,.0f} @ ₦{g["price"]:,.2f}</h4>'
            f'<div class="muted">{g["date"]}{perf} · {g.get("note") or "no reason given"}</div></div>',
            unsafe_allow_html=True)
