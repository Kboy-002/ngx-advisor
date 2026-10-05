"""Grounded AI analyst — DeepSeek (or any OpenAI-compatible) over our own evidence.

Contract (planning): the model sees ONLY an evidence pack we assemble
(quant scores, factor numbers, signals with URLs, Afrinvest outlook,
portfolio fit). It must cite only provided figures. Quant rank +
concentration guardrails still decide the buy; the analyst advises.
Outputs persist (analyses / digests tables) and render on the dashboard
labeled as reasoning aids, not orders.
"""
from __future__ import annotations

import os
from datetime import date

import llm
import store

ANALYST_RULES = """You are a skeptical Nigerian equities analyst writing for a 21-year-old
growth investor with ~₦100k monthly tickets on the NGX.
HARD RULES:
- Use ONLY figures given in the evidence pack. Never invent prices, ratios, dates, or URLs.
- Every claim about a company must trace to a pack item; say "per pack" when uncertain.
- Prefer NOMISS: if evidence is thin, say so and lower confidence instead of filling gaps.
- No hype, no guarantees, no "must buy" language. Plain, direct tone.
- Output STRICT JSON matching the requested schema. No markdown fences."""


def _model() -> str:
    return os.getenv("LLM_MODEL", "deepseek-chat")


def _pack_for(symbols: list[str], ranked: list[dict]) -> str:
    rmap = {c["symbol"]: c for c in ranked}
    pf = store.latest_holdings()
    held = {h["symbol"]: h for h in (pf.get("holdings", []) if pf else [])}
    research = store.latest_research(2)
    lines = []
    for s in symbols:
        c = rmap.get(s, {})
        ev = c.get("evidence", {}) or {}
        sig_lines = [f"    - [{t}] {x}" for t in ("signals",) for x in (ev.get(t) or [])]
        fac = c.get("factor_scores", {}) or {}
        h = held.get(s)
        lines.append(
            f"- {s}: price ₦{c.get('price')}, quant score {c.get('score')}, "
            f"factors {fac}\n"
            f"  factor evidence: { {k: (ev.get(k) or []) for k in ('momentum','quality','value','risk_liquidity','dividend')} }\n"
            + ("\n".join(sig_lines) if sig_lines else "    - no linked signals in 120d") + "\n"
            + (f"  HELD: {h['quantity']} units @ avg ₦{h['avg_cost']} = {n(h['value'])} ({h['gain_pct']:+.1f}%)"
               if h else "  HELD: no position")
        )
    outlook = "\n".join(
        f"- {r['published']}: {r['title']} (ASI {r['asi_close'] or 'n/a'}) {r['url']}\n  {(r['summary'] or '')[:800]}"
        for r in research) or "- no Afrinvest weekly on file yet"
    asi = store.asi_series(8)
    asi_txt = ", ".join(f"{a['date']}={a['asi']:,.0f}" for a in reversed(asi)) or "n/a"
    return ("CANDIDATES (top quant-ranked):\n" + "\n".join(lines)
            + f"\n\nAFRINVEST WEEKLY OUTLOOK:\n{outlook}"
            + f"\n\nASI RECENT: {asi_txt}")


def n(v) -> str:
    try:
        return f"₦{float(v):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def monthly_analysis(cash: float, month: str | None = None, top_n: int = 6) -> dict:
    """Deep-dive the top-N quant candidates. Returns + persists the analysis."""
    import pick as pickpipe

    month = month or date.today().strftime("%Y-%m")
    cands, warming = pickpipe.build_candidates()
    if not cands:
        raise RuntimeError("No price data yet — run the daily EOD ingest first.")
    ranked = __import__("scoring").rank_candidates(cands)
    top = ranked[:top_n]
    pack = _pack_for([c["symbol"] for c in top], ranked)
    portfolio = store.latest_holdings()
    pftxt = ("none on file" if not portfolio else
             f"total {n(portfolio['total_value'])}, cash {n(portfolio['cash_balance'])}, "
             + ", ".join(f"{h['symbol']} {h['acct_pct']}%" for h in portfolio["holdings"][:8]))
    user = (f"MONTHLY BUDGET: ₦{cash:,.0f} for {month}. HISTORY WARMING: {warming}.\n"
            f"PORTFOLIO: {pftxt}.\n\n{pack}\n\n"
            "Return JSON: {\"analyses\": [{\"symbol\": ..., \"thesis\": \"2-3 sentences\", "
            "\"bull_case\": [3 strings], \"bear_case\": [3 strings], "
            "\"key_risks\": [3 strings], \"catalysts\": [2 strings], "
            "\"confidence\": 0-100, \"verdict\": \"BUY\"|\"NEUTRAL\"|\"AVOID\"}], "
            "\"market_read\": \"3-4 sentences on ASI + outlook + what it means for deploying cash this month\", "
            "\"suggested_focus\": \"which 1-2 symbols the evidence best supports and why in one sentence\"}")
    out = llm.chat_json(ANALYST_RULES, user, max_tokens=3000)
    payload = {"month": month, "cash": cash, "warming_up": warming,
               "quant_top": [{"symbol": c["symbol"], "score": c["score"]} for c in top],
               **out}
    store.save_analysis(month, payload, _model())
    payload["model"] = _model()
    return payload


def weekly_digest(week: str | None = None) -> dict:
    """Saturday digest: week's signals + Afrinvest weekly + portfolio movers."""
    from datetime import date as _d

    week = week or _d.today().strftime("%Y-%m-%d")
    import db as _db

    with _db.conn() as c:
        cur = c.execute(
            """SELECT symbol, event_type, title, url, source, published FROM signals
               WHERE created_at > now() - INTERVAL '7 days' ORDER BY created_at DESC LIMIT 40""")
        sigs = [{"symbol": r[0], "type": r[1], "title": r[2], "url": r[3],
                 "source": r[4], "date": str(r[5]) if r[5] else None} for r in cur.fetchall()]
    research = store.latest_research(1)
    pf = store.latest_holdings()
    asi = store.asi_series(8)
    asi_txt = ", ".join(f"{a['date']}={a['asi']:,.0f}" for a in reversed(asi)) or "no ASI on file"
    movers = ""
    if pf:
        hs = sorted(pf["holdings"], key=lambda h: abs(h.get("gain_pct", 0) or 0), reverse=True)[:6]
        movers = ", ".join(f"{h['symbol']} {h['gain_pct']:+.1f}% ({n(h['value'])})" for h in hs)
    sig_txt = "\n".join(f"- {s['symbol']} [{s['type']}] {s['title']} ({s['source']}) {s['url'] or ''}"
                        for s in sigs) or "- no tagged signals this week"
    res_txt = ""
    for r in research:
        res_txt += f"- {r['published']}: {r['title']} (ASI {r['asi_close'] or 'n/a'}) {r['url']}\n{(r['summary'] or '')[:1200]}\n"
    user = (f"WEEK ENDING {week}.\nASI RECENT: {asi_txt}.\nSIGNALS THIS WEEK:\n{sig_txt}\n\n"
            f"AFRINVEST WEEKLY:\n{res_txt or '- none on file'}\n\n"
            f"PORTFOLIO MOVERS: {movers or 'no portfolio on file'}\n\n"
            "Return JSON: {\"headline\": \"one line\", \"market_summary\": \"3-4 sentences\", "
            "\"what_moved\": [\"3-5 bullets with tickers\"], \"portfolio_notes\": [\"2-4 bullets tied to held names\"], "
            "\"watch_next_week\": [\"2-3 bullets\"], \"sources\": [\"urls cited\"]}")
    out = llm.chat_json(ANALYST_RULES, user, max_tokens=2000)
    payload = {"week": week, **out}
    store.save_digest(week, payload, _model())
    payload["model"] = _model()
    return payload
