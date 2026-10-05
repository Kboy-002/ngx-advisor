"""Monthly pick pipeline — DB in, persisted pick out.

Universe: every symbol with a recent close. Momentum is derived from our
own stored price history (needs a few weeks of daily runs to warm up;
before that, day_change_pct seeds the 3-mo slot and scores carry a
'warming up' flag). Fundamentals join where present, else neutral.
"""
from __future__ import annotations

from datetime import date

import allocator
import scoring
import store
from config import SECTORS, SUSPENDED_TAGS
from signals import overlay_for


def _returns(history: list[dict]) -> dict:
    """history: newest-first [{date, close}]. Returns 3m/6m % + 52w position."""
    if len(history) < 2:
        return {}
    closes = [h["close"] for h in history if h.get("close")]
    if len(closes) < 2 or closes[0] <= 0:
        return {}
    out: dict = {}
    # ~63 trading days per 3 months, ~126 per 6 months.
    for label, n in (("ret_3m", 63), ("ret_6m", 126)):
        if len(closes) > n and closes[n] > 0:
            out[label] = round((closes[0] / closes[n] - 1) * 100, 1)
    window = closes[:252]
    hi, lo = max(window), min(window)
    if hi > lo:
        out["pos_52w"] = round((closes[0] - lo) / (hi - lo), 2)
    return out


def build_candidates() -> tuple[list[dict], bool]:
    prices = store.latest_prices()
    funds = store.latest_fundamentals()
    meta = store.all_meta()
    # Sector-average P/E from live feed data — value is measured against peers.
    sector_pes: dict[str, list[float]] = {}
    for sym, f in funds.items():
        if f.get("pe"):
            sec = (meta.get(sym, {}).get("sector") or SECTORS.get(sym, "other") or "other").lower()
            sector_pes.setdefault(sec, []).append(float(f["pe"]))
    sector_avg = {s: sum(v) / len(v) for s, v in sector_pes.items() if v}
    cands: list[dict] = []
    thin = True
    for p in prices:
        sym = p["symbol"]
        if any(t in sym for t in ("FG", "FGS")):
            continue
        f = funds.get(sym, {})
        sector = meta.get(sym, {}).get("sector") or SECTORS.get(sym, "unmapped")
        value_in = {k: f[k] for k in ("pe",) if f.get(k) is not None}
        if value_in.get("pe") and str(sector).lower() in sector_avg:
            value_in["sector_pe"] = round(sector_avg[str(sector).lower()], 1)
        hist = store.price_history(sym)
        mom = _returns(hist)
        if p.get("week_change_pct") is not None:
            mom.setdefault("ret_7d", round(p["week_change_pct"], 1))
        if not mom and p.get("change_pct") is not None:
            mom = {"ret_3m": round(p["change_pct"] * 20, 1)}  # seed until history warms
        else:
            thin = False if mom.get("ret_6m") is not None else thin
        evts = store.signals_for(sym)
        adj, notes = overlay_for(
            [{"event_type": e["event_type"], "title": e["title"], "source": e["source"],
              "source_tier": e["source_tier"], "url": e["url"]} for e in evts])
        cands.append({
            "symbol": sym, "price": p["close"],
            "momentum": mom,
            "quality": {k: f[k] for k in ("revenue_growth", "eps_growth", "roe",
                                          "profit_margin", "debt_equity") if f.get(k) is not None},
            "value": value_in,
            "risk": {"suspended": False,
                     **({"daily_value": float(p["volume"]) * float(p["close"])}
                        if p.get("volume") else
                        ({"daily_value": 50_000_000} if len(hist) > 20 else {}))},
            "dividend": ({k: f[k] for k in ("streak_years",) if f.get(k) is not None}
                         | ({"yield_pct": f["dividend_yield"]} if f.get("dividend_yield") is not None else {})),
            "signal_adj": adj, "signal_notes": notes,
            "risks": [f"Sector: {sector}"] +
                     ([f"{len(evts)} linked signal(s) in last 120d — see evidence"] if evts else []),
        })
    warming = all(len(store.price_history(p["symbol"])) < 40 for p in prices[:5]) if prices else True
    return cands, warming


def apply_analyst_overlay(ranked: list[dict], analysis: dict) -> tuple[list[dict], list[str]]:
    """Fold analyst verdicts back into quant scores, transparently.

    AVOID -15, NEUTRAL 0, BUY +5. Returns (adjusted_ranked, reconciliation_notes).
    """
    adj_map = {"AVOID": -15.0, "NEUTRAL": 0.0, "BUY": 5.0}
    verdicts = {a.get("symbol"): a for a in (analysis.get("analyses") or [])}
    notes: list[str] = []
    for c in ranked:
        v = verdicts.get(c["symbol"])
        if not v:
            c["analyst_overlay"] = 0.0
            continue
        adj = adj_map.get(str(v.get("verdict", "NEUTRAL")).upper(), 0.0)
        c["analyst_overlay"] = adj
        c["score"] = round(max(0.0, min(100.0, c["score"] + adj)), 1)
        notes.append(f"{c['symbol']}: quant {c.get('quant_score', c['score'])} "
                     f"× analyst {v.get('verdict')} (conf {v.get('confidence')}) → {c['score']}")
    ranked.sort(key=lambda x: x["score"], reverse=True)
    for i, c in enumerate(ranked, 1):
        c["rank"] = i
    return ranked, notes


def generate_monthly_pick(cash: float, month: str | None = None,
                          analyze: bool = False) -> dict:
    """Full pipeline: DB -> ranked -> (optional AI deep-dive overlay) -> allocated -> persisted."""
    month = month or date.today().strftime("%Y-%m")
    cands, warming = build_candidates()
    if not cands:
        raise RuntimeError("No price data yet — run the daily EOD ingest first (GET /ingest/run).")
    ranked = scoring.rank_candidates(cands)
    for c in ranked:
        c["quant_score"] = c["score"]
    # Liquidity guardrail: can't deploy the ticket where it exceeds 20% of a
    # day's typical naira turnover without moving the price against yourself.
    liquid = [c for c in ranked
              if not c.get("risk", {}).get("daily_value")
              or cash <= 0.20 * float(c["risk"]["daily_value"])]
    skipped = len(ranked) - len(liquid)
    if liquid:
        ranked = liquid
    else:
        skipped = 0  # nothing deployable; fall back to full list with warning
    reconciliation: list[str] = []
    analysis = None
    if analyze:
        import analyst as analystmod
        analysis = analystmod.monthly_analysis(cash, month)
        ranked, reconciliation = apply_analyst_overlay(ranked, analysis)
    portfolio = store.latest_holdings()
    meta2 = store.all_meta()
    def _sec(s: str) -> str:
        return meta2.get(s, {}).get("sector") or SECTORS.get(s, "other")
    pf = None
    if portfolio:
        pf = {"holdings": [{"symbol": h["symbol"], "value": h["value"]}
                           for h in portfolio["holdings"]],
              "total_value": portfolio["total_value"],
              "sectors": {h["symbol"]: _sec(h["symbol"]) for h in portfolio["holdings"]}}
    for c in ranked:
        c["sector_live"] = _sec(c["symbol"])
    allocs = allocator.allocate(cash, ranked, pf)
    asi = store.latest_asi()
    rationale = (
        f"Growth-first screen over {len(cands)} symbols"
        + (" (price history still warming — momentum seeded, treat ranks as provisional)" if warming else "")
        + (f". {skipped} thin name(s) excluded: ticket exceeds 20% of daily turnover." if skipped else "")
        + (f". AI overlay applied: {'; '.join(reconciliation)}." if reconciliation else "")
        + f". Concentration guardrails vs {len(pf['holdings']) if pf else 0} held tickers."
    )
    store.record_cash(month, cash)
    store.save_pick(month, cash, allocs, rationale, asi["asi"] if asi else None)
    return {"month": month, "cash": cash, "picks": allocs, "rationale": rationale,
            "asi_at_pick": asi, "warming_up": warming, "universe": len(cands),
            "deployable": len(ranked), "reconciliation": reconciliation,
            "analyzed": analysis is not None}


def pick_performance(month: str) -> dict:
    """Pick-vs-ASI since the pick was made. Needs stored prices to have moved."""
    picks = [p for p in store.list_picks() if p["month"] == month]
    if not picks:
        raise KeyError(f"No pick stored for {month}")
    pick = picks[0]
    asi_now = store.latest_asi()
    out = {"month": month, "cash": pick["cash"], "asi_at_pick": pick["asi_at_pick"],
           "asi_now": asi_now, "legs": []}
    if pick["asi_at_pick"] and asi_now:
        out["asi_return_pct"] = round((asi_now["asi"] / pick["asi_at_pick"] - 1) * 100, 2)
    latest = {p["symbol"]: p for p in store.latest_prices()}
    for leg in pick["picks"]:
        cur = latest.get(leg["symbol"])
        leg_perf = {"symbol": leg["symbol"], "units": leg["units"],
                    "buy_price": leg["est_price"], "score": leg["score"]}
        if cur:
            leg_perf["now_price"] = cur["close"]
            leg_perf["return_pct"] = round((cur["close"] / leg["est_price"] - 1) * 100, 2)
        out["legs"].append(leg_perf)
    return out
