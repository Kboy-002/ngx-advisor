"""Allocator: single-stock default, 2nd only when earned.

Rules (locked in planning):
- Default 100% into #1.
- Split only if: gap <= ~10 pts AND diversifies sector, OR concentration
  guardrail would breach (ticker >35% / sector >45% incl. new buy),
  OR lot math leaves >25% cash idle on a single name.
- Converts NGN -> whole units after est. fees; reports remainder.
"""
from __future__ import annotations

import math

from config import EST_BUY_FEE_RATE, MAX_SECTOR_PCT, MAX_SINGLE_TICKER_PCT, SECTORS


def _units_and_cost(allocation: float, price: float) -> tuple[int, float, float]:
    if price <= 0:
        return 0, 0.0, allocation
    # Solve units so that units*price*(1+fee) <= allocation.
    units = math.floor(allocation / (price * (1 + EST_BUY_FEE_RATE)))
    cost = round(units * price, 2)
    fees = round(units * price * EST_BUY_FEE_RATE, 2)
    remainder = round(allocation - cost - fees, 2)
    return units, cost, fees


def allocate(cash: float, ranked: list[dict], portfolio: dict | None = None) -> list[dict]:
    """ranked: scoring.rank_candidates output (needs symbol, score, price).
    portfolio: {holdings: [{symbol, value}], total_value: float} or None."""
    if not ranked or cash <= 0:
        return []
    top = [c for c in ranked if c.get("price", 0) > 0][:5]
    if not top:
        return []
    first = top[0]
    second = top[1] if len(top) > 1 else None

    want_two = False
    reason = "Single best idea dominates"
    if second:
        gap = first["score"] - second["score"]
        s1, s2 = SECTORS.get(first["symbol"], "?"), SECTORS.get(second["symbol"], "?")
        if gap <= 10 and s1 != s2:
            want_two, reason = True, f"Scores close ({gap:.0f}pt gap) and diversifies {s1} + {s2}"
        if portfolio:
            tot = (portfolio.get("total_value") or 0) + cash
            if tot > 0:
                cur = {h["symbol"]: h.get("value", 0) for h in portfolio.get("holdings", [])}
                if (cur.get(first["symbol"], 0) + cash) / tot > MAX_SINGLE_TICKER_PCT:
                    want_two, reason = True, f"Caps {first['symbol']} concentration at {MAX_SINGLE_TICKER_PCT:.0%}"
                sec_tot: dict[str, float] = {}
                for h in portfolio.get("holdings", []):
                    sec_tot[SECTORS.get(h["symbol"], "?")] = sec_tot.get(SECTORS.get(h["symbol"], "?"), 0) + h.get("value", 0)
                sec_tot[s1] = sec_tot.get(s1, 0) + cash
                if sec_tot[s1] / tot > MAX_SECTOR_PCT:
                    want_two, reason = True, f"Caps {s1} sector at {MAX_SECTOR_PCT:.0%}"

    if not want_two:
        u, cost, fees = _units_and_cost(cash, first["price"])
        if cash - (cost + fees) > cash * 0.25 and second:
            want_two, reason = "Single-name lots leave cash idle — split improves deployment"
        else:
            return [{"symbol": first["symbol"], "allocation_ngn": round(cost + fees, 2),
                     "units": u, "est_price": first["price"], "est_fees": fees,
                     "score": first["score"], "note": reason,
                     "evidence": first.get("evidence", {}), "risks": first.get("risks", [])}]

    # Two-way split, score-weighted, rounded to lots.
    w1 = first["score"] / (first["score"] + second["score"])
    a1 = round(cash * w1, 2)
    u1, c1, f1 = _units_and_cost(a1, first["price"])
    rest = round(cash - (c1 + f1), 2)
    u2, c2, f2 = _units_and_cost(rest, second["price"])
    return [
        {"symbol": first["symbol"], "allocation_ngn": round(c1 + f1, 2), "units": u1,
         "est_price": first["price"], "est_fees": f1, "score": first["score"],
         "note": reason, "evidence": first.get("evidence", {}), "risks": first.get("risks", [])},
        {"symbol": second["symbol"], "allocation_ngn": round(c2 + f2, 2), "units": u2,
         "est_price": second["price"], "est_fees": f2, "score": second["score"],
         "note": reason, "evidence": second.get("evidence", {}), "risks": second.get("risks", [])},
    ]
