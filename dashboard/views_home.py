"""Home — portfolio-first landing: hero strip, allocation donut, movers, pick teaser."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from components import (api_get, empty_state, move_class, naira, naira0,
                        signed_pct)


def _donut(holdings: list[dict]):
    rows = [(h["symbol"], float(h.get("value", 0) or 0)) for h in holdings]
    rows.sort(key=lambda x: x[1], reverse=True)
    big = [r for r in rows if r[1] > 0]
    main, rest = big[:7], big[7:]
    labels = [r[0] for r in main] + (["Other"] if rest else [])
    values = [r[1] for r in main] + ([sum(r[1] for r in rest)] if rest else [])
    fig = px.pie(names=labels, values=values, hole=0.55,
                 color_discrete_sequence=px.colors.sequential.Greens_r)
    fig.update_layout(showlegend=True, height=320, margin=dict(t=10, b=10, l=10, r=10),
                      paper_bgcolor="rgba(0,0,0,0)", font_color="#E8ECF1")
    fig.update_traces(textinfo="percent", textfont_size=11)
    return fig


def render() -> None:
    snap, err = api_get("/portfolio/latest")
    if err or not snap or snap.get("empty"):
        empty_state("No portfolio on file yet",
                    "Upload your Afrinvest valuation statement in <b>Saturday Check</b> "
                    "and this page becomes your wealth home screen.")
        picks, _ = api_get("/picks")
        if picks and picks.get("picks"):
            _pick_teaser(picks["picks"][0])
        return

    holdings = snap.get("holdings", [])
    total = snap.get("total_value", 0) or 0
    cash = snap.get("cash_balance", 0) or 0
    winners = sorted(holdings, key=lambda h: h.get("gain_pct", 0) or 0, reverse=True)
    top = winners[0] if winners else None

    chg_txt = ""
    if top:
        g = top.get("gain_pct", 0) or 0
        chg_txt = (f'<span class="{move_class(g)}">{signed_pct(g)}</span> '
                   f'on your best mover {top["symbol"]}')

    st.markdown(
        f'<div class="hero"><div class="label">Portfolio value · {snap.get("statement_to", "")}</div>'
        f'<div class="value">{naira0(total)}</div>'
        f'<div class="sub">{len(holdings)} holdings · {naira0(cash)} sitting in cash · {chg_txt}</div></div>',
        unsafe_allow_html=True)

    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.markdown("**Where your money sits**")
        if holdings:
            st.plotly_chart(_donut(holdings), use_container_width=True)
        conc = max((h.get("acct_pct", 0) or 0 for h in holdings), default=0)
        if conc > 35:
            st.warning(f"One ticker is {conc:.0f}% of everything — fresh buys should diversify, not add to it.")
    with c2:
        st.markdown("**Movers**")
        ups = [h for h in winners[:3] if (h.get("gain_pct", 0) or 0) > 0]
        downs = sorted([h for h in holdings if (h.get("gain_pct", 0) or 0) < 0],
                       key=lambda h: h.get("gain_pct", 0))[:3]
        for h in ups:
            st.markdown(
                f'<div class="card"><h4>{h["symbol"]} '
                f'<span class="up">{signed_pct(h.get("gain_pct"))}</span></h4>'
                f'<div class="muted">{naira(h.get("value"))} · letting it run</div></div>',
                unsafe_allow_html=True)
        for h in downs:
            st.markdown(
                f'<div class="card"><h4>{h["symbol"]} '
                f'<span class="down">{signed_pct(h.get("gain_pct"))}</span></h4>'
                f'<div class="muted">{naira(h.get("value"))} · hold, don\'t chase</div></div>',
                unsafe_allow_html=True)
        if not ups and not downs:
            st.caption("Movers appear once a statement is uploaded.")

    picks, _ = api_get("/picks")
    if picks and picks.get("picks"):
        _pick_teaser(picks["picks"][0])


def _pick_teaser(p: dict) -> None:
    legs = " + ".join(l["symbol"] for l in p.get("picks", []))
    st.markdown(
        f'<div class="card"><h4>This month: {legs}</h4>'
        f'<div class="muted">{naira0(p.get("cash"))} deployed · full breakdown in '
        f"<b>This Month</b>.</div></div>",
        unsafe_allow_html=True)
