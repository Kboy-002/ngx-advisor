"""This Month — the buy instruction: hero pick card, score bars, evidence, risks."""
from __future__ import annotations

import streamlit as st

from components import (api_get, api_post, empty_state, naira, score_bars,
                        tier_badge)


def _evidence_block(ev: dict) -> None:
    groups = [("momentum", "Trend"), ("quality", "Growth quality"),
              ("value", "Price"), ("risk_liquidity", "Risk"),
              ("dividend", "Dividend")]
    bullets = []
    for key, label in groups:
        for line in (ev.get(key) or []):
            bullets.append(f"<div class='ev'><b>{label}:</b> {line}</div>")
    if bullets:
        st.markdown("".join(bullets), unsafe_allow_html=True)
    for s in ev.get("signals", []) or []:
        st.markdown(f"<div class='sig'>{s}</div>", unsafe_allow_html=True)


def _pick_cards(picks: list[dict]) -> None:
    for a in picks:
        st.markdown(
            f'<div class="pick-hero"><div class="action">Buy · score {a.get("score")}</div>'
            f'<div class="ticker">{a["symbol"]}</div>'
            f'<div class="detail">{a["units"]} units @ {naira(a["est_price"])} = '
            f'{naira(a["allocation_ngn"])} <span class="muted">(fees ~{naira(a.get("est_fees"))})</span></div>'
            f'<div class="note">{a.get("note", "")}</div></div>',
            unsafe_allow_html=True)
        with st.expander(f"Why {a['symbol']} — evidence trail", expanded=False):
            st.markdown("**Score breakdown**")
            score_bars(a.get("factor_scores") or {})
            st.markdown("**Evidence**")
            _evidence_block(a.get("evidence", {}))
            risks = a.get("risks") or []
            if risks:
                st.markdown("**Risks — read before you buy**")
                for r in risks:
                    st.markdown(f"<div class='ev'>⚠️ {r}</div>", unsafe_allow_html=True)


def render(cash: float) -> None:
    st.markdown("### This month's instruction")
    st.caption("One clear buy (or a pair, only if earned). Backed by numbers, not vibes.")

    picks_data, _ = api_get("/picks")
    stored = (picks_data or {}).get("picks", [])

    col1, col2 = st.columns([1, 1])
    with col1:
        gen = st.button("✨ Generate this month's pick", type="primary")
    with col2:
        refresh = st.button("↻ Refresh market feed")

    if refresh:
        with st.spinner("Pulling today's NGX prices…"):
            res, err = api_post("/ingest/run", timeout=120.0)
        if err or (res or {}).get("error"):
            st.error("Couldn't reach the market feed. Your saved data is untouched — try again after 4:30pm.")
        else:
            st.success(f"Feed updated: {res.get('prices', 0)} prices"
                       + (" · ASI captured" if res.get("asi") else ""))

    if gen:
        with st.spinner("Screening the market for your cash…"):
            res, err = api_post("/picks/generate", json={"cash": cash}, timeout=120.0)
        if err or not res or res.get("error"):
            st.warning(res.get("error") if res else
                       "The engine isn't reachable. Check the status dot in the sidebar.")
        else:
            if res.get("warming_up"):
                st.info("Fresh data pipeline — momentum is provisional until ~40 trading days accumulate. "
                        "Scores lean on price action + any fundamentals on file.")
            st.success(f"Saved for {res['month']} · screened {res.get('universe', '?')} stocks")
            _pick_cards(res["picks"])
    elif stored:
        latest = stored[0]
        st.caption(f"Showing saved pick for {latest['month']} — press Generate to re-run with {naira(cash)}.")
        _pick_cards(latest["picks"])
    else:
        empty_state("No pick yet",
                    "Press <b>Generate this month's pick</b> and the engine will screen the market "
                    "for exactly what to buy with your cash.")
