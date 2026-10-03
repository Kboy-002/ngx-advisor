"""Signal taxonomy + source tiers (planning contract).

Machine collects + links with receipts; human judges. Signals apply as a
±10pt overlay on the numeric score, never overriding it.
Tiers: 1 = NGX filing, 2 = company IR, 3 = press/rumour.
"""
from __future__ import annotations

EVENT_TYPES = (
    "M&A_DEAL", "INSIDER_BUYING", "EARNINGS_BEAT", "EARNINGS_MISS",
    "DIVIDEND_DECLARED", "BONUS_SPLIT", "NEW_LISTING",
    "REGULATORY_APPROVAL", "MANAGEMENT_CHANGE", "OTHER",
)

# Bullish events push +, bearish push -. Magnitude capped at ±10 total.
EVENT_DIRECTION = {
    "M&A_DEAL": +6, "INSIDER_BUYING": +5, "EARNINGS_BEAT": +5,
    "DIVIDEND_DECLARED": +1, "BONUS_SPLIT": +1, "NEW_LISTING": +2,
    "REGULATORY_APPROVAL": +4, "MANAGEMENT_CHANGE": 0,
    "EARNINGS_MISS": -5, "OTHER": 0,
}

TIER_CONFIDENCE = {1: "high", 2: "medium", 3: "low"}


def overlay_for(events: list[dict]) -> tuple[float, list[str]]:
    total = 0.0
    notes: list[str] = []
    for e in events:
        d = EVENT_DIRECTION.get(e.get("event_type", "OTHER"), 0)
        tier = int(e.get("source_tier", 3))
        weight = {1: 1.0, 2: 0.7, 3: 0.4}.get(tier, 0.4)
        total += d * weight
        notes.append(f"[{e.get('event_type')}] {e.get('title', '')} — {e.get('source', '?')} (tier {tier}) {e.get('url', '')}".strip())
    total = max(-10.0, min(10.0, total))
    return round(total, 1), notes
