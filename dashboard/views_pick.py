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
        recon = ""
        if a.get("analyst_overlay"):
            sign = "+" if a["analyst_overlay"] > 0 else ""
            recon = (f'<div class="note">Quant {a.get("quant_score", a.get("score"))} '
                     f'× analyst overlay {sign}{a["analyst_overlay"]:.0f} → final {a.get("score")}</div>')
        st.markdown(
            f'<div class="pick-hero"><div class="action">Buy · score {a.get("score")}</div>'
            f'<div class="ticker">{a["symbol"]}</div>'
            f'<div class="detail">{a["units"]} units @ {naira(a["est_price"])} = '
            f'{naira(a["allocation_ngn"])} <span class="muted">(fees ~{naira(a.get("est_fees"))})</span></div>'
            f'<div class="note">{a.get("note", "")}</div>{recon}</div>',
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


def _analyst_section(cash: float) -> None:
    from datetime import date as _d
    st.markdown("### AI analyst deep-dive")
    st.caption("Grounded reasoning over the same numbers above — bull/bear, risks, catalysts. "
               "Advisory only: the quant rank still makes the call.")
    month = _d.today().strftime("%Y-%m")
    stored, _ = api_get(f"/analyst/monthly/{month}")
    if stored and "error" not in stored:
        _render_analysis(stored.get("payload", {}), stored.get("model", "?"))
    else:
        st.info("No deep-dive for this month yet.")
    if st.button("🧠 Run AI deep-dive", help="Analyzes the top candidates. Uses your LLM key; costs a few cents."):
        with st.spinner("Analyst at work — reading scores, signals and outlook…"):
            res, err = api_post("/analyst/monthly", json={"cash": cash}, timeout=300.0)
        if err or not res or res.get("error"):
            st.warning((res or {}).get("error") if res else
                       "Analyst unreachable. If it mentions LLM_API_KEY, add your DeepSeek key to .env and restart.")
        else:
            _render_analysis(res, res.get("model", "?"))


def _render_analysis(payload: dict, model: str) -> None:
    st.caption(f"Model: {model} · verify every figure against the evidence above before acting.")
    if payload.get("market_read"):
        st.markdown(f'<div class="card"><h4>Market read</h4>'
                    f'<div class="muted">{payload["market_read"]}</div></div>', unsafe_allow_html=True)
    for a in payload.get("analyses", []):
        conf = a.get("confidence", 0)
        with st.expander(f"{a.get('symbol')} — {a.get('verdict', '?')} (confidence {conf})", expanded=False):
            st.markdown(f"**Thesis:** {a.get('thesis', '—')}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Bull case**")
                for b in a.get("bull_case", []):
                    st.markdown(f"<div class='ev'>🟢 {b}</div>", unsafe_allow_html=True)
                st.markdown("**Catalysts**")
                for b in a.get("catalysts", []):
                    st.markdown(f"<div class='ev'>⚡ {b}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown("**Bear case**")
                for b in a.get("bear_case", []):
                    st.markdown(f"<div class='ev'>🔴 {b}</div>", unsafe_allow_html=True)
                st.markdown("**Key risks**")
                for b in a.get("key_risks", []):
                    st.markdown(f"<div class='ev'>⚠️ {b}</div>", unsafe_allow_html=True)
    if payload.get("suggested_focus"):
        st.success(f"Suggested focus: {payload['suggested_focus']}")


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
    with_ai = st.toggle("Include AI deep-dive (slower, reconciles analyst verdicts into scores)",
                        value=True)

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
            res, err = api_post("/picks/generate",
                                json={"cash": cash, "analyze": with_ai},
                                timeout=300.0)
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

    st.divider()
    _analyst_section(cash)
