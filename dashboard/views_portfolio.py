"""Saturday Check — styled PDF upload, formatted holdings, verdict cards."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components import (api_post, move_class, naira, signed_pct,
                        verdict_class)


def _holdings_frame(holdings: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([{
        "Ticker": h.get("symbol", ""),
        "Units": h.get("quantity", 0),
        "Avg cost": h.get("avg_cost", 0),
        "Price": h.get("price", 0),
        "Value": h.get("value", 0),
        "Gain %": h.get("gain_pct", 0),
        "Share": h.get("acct_pct", 0),
    } for h in holdings])
    return df.sort_values("Value", ascending=False)


def _show_snapshot(snap: dict) -> None:
    st.success(f"Statement read: {snap.get('statement_from', '?')} → {snap.get('statement_to', '?')} "
               f"· account {snap.get('account_no', '?')}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f'<div class="card"><h4>{naira(snap.get("total_value"))}</h4>'
                    '<div class="muted">Total portfolio value</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="card"><h4>{naira(snap.get("cash_balance"))}</h4>'
                    '<div class="muted">Cash waiting to work</div></div>', unsafe_allow_html=True)

    st.markdown("**Holdings**")
    st.dataframe(_holdings_frame(snap.get("holdings", [])), use_container_width=True,
                 column_config={
                     "Avg cost": st.column_config.NumberColumn(format="₦%.2f"),
                     "Price": st.column_config.NumberColumn(format="₦%.2f"),
                     "Value": st.column_config.NumberColumn(format="₦%.2f"),
                     "Gain %": st.column_config.NumberColumn(format="%.1f%%"),
                     "Share": st.column_config.NumberColumn(format="%.2f%%"),
                 })

    st.markdown("**Verdicts — what to do with each name**")
    for v in snap.get("verdicts", []):
        cls = verdict_class(v.get("verdict", ""))
        st.markdown(
            f'<div class="card verdict {cls}"><h4>{v["symbol"]} — {v["verdict"]}</h4>'
            f'<div class="muted">{v["reason"]}</div></div>',
            unsafe_allow_html=True)


def render() -> None:
    st.markdown("### Saturday check")
    st.caption("Drop this week's Afrinvest valuation statement. I'll read every line and tell you what to do.")
    up = st.file_uploader("Valuation statement (PDF)", type=["pdf"],
                          help="The weekly Afrinvest PDF — holdings, prices and cash are read automatically.")
    if up is None:
        st.info("Waiting on your PDF — nothing to judge until you share it.")
        return
    with st.spinner("Reading your statement…"):
        snap, err = api_post("/portfolio/parse",
                             files={"file": (up.name, up.getvalue(), "application/pdf")},
                             timeout=120.0)
    if err or not snap:
        st.error("That file wouldn't parse. Make sure it's the Afrinvest valuation statement, not a contract note.")
        return
    _show_snapshot(snap)
