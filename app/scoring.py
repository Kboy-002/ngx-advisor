"""Growth-first scoring (weights locked in planning).

momentum 30 / quality-growth 25 / value 20 / risk-liquidity 20 / dividend 5.
Each factor scores 0-100 from available data; missing inputs degrade
gracefully to 50 (neutral) and are flagged in evidence so a thin-data
stock can't fake a high score. Signal overlay (±10) applied separately.
"""
from __future__ import annotations

from config import WEIGHTS


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _num(x, default=None):
    try:
        return float(x) if x is not None else default
    except (TypeError, ValueError):
        return default


def score_momentum(ret_3m=None, ret_6m=None, ret_7d=None, vs_asi_3m=None, pos_52w=None, vol_trend=None) -> tuple[float, list[str]]:
    ev: list[str] = []
    parts: list[float] = []
    ret_3m, ret_6m, ret_7d = _num(ret_3m), _num(ret_6m), _num(ret_7d)
    vs_asi_3m, pos_52w, vol_trend = _num(vs_asi_3m), _num(pos_52w), _num(vol_trend)
    if ret_7d is not None:
        parts.append(_clamp(50 + ret_7d * 4.0))
        ev.append(f"7-day move {ret_7d:+.1f}%")
    if ret_3m is not None:
        parts.append(_clamp(50 + ret_3m * 1.5))
        ev.append(f"3-mo return {ret_3m:+.1f}%")
    if ret_6m is not None:
        parts.append(_clamp(50 + ret_6m * 0.8))
        ev.append(f"6-mo return {ret_6m:+.1f}%")
    if vs_asi_3m is not None:
        parts.append(_clamp(50 + vs_asi_3m * 2.0))
        ev.append(f"{vs_asi_3m:+.1f}pp vs ASI (3 mo)")
    if pos_52w is not None:
        parts.append(_clamp(pos_52w * 100))
        ev.append(f"{pos_52w * 100:.0f}% of 52-week range")
    if vol_trend is not None:
        parts.append(_clamp(50 + vol_trend * 25))
        ev.append(f"Volume trend {vol_trend:+.2f}x")
    if not parts:
        return 50.0, ["No momentum data — neutral"]
    return round(sum(parts) / len(parts), 1), ev


def score_quality(rev_growth=None, eps_growth=None, roe=None, margin=None, debt_equity=None) -> tuple[float, list[str]]:
    ev: list[str] = []
    parts: list[float] = []
    rev_growth, eps_growth, roe = _num(rev_growth), _num(eps_growth), _num(roe)
    margin, debt_equity = _num(margin), _num(debt_equity)
    if rev_growth is not None:
        parts.append(_clamp(50 + rev_growth * 1.2))
        ev.append(f"Revenue growth {rev_growth:+.1f}% YoY")
    if eps_growth is not None:
        parts.append(_clamp(50 + eps_growth * 1.0))
        ev.append(f"EPS growth {eps_growth:+.1f}% YoY")
    if roe is not None:
        parts.append(_clamp(min(roe * 2.5, 100)))
        ev.append(f"ROE {roe:.1f}%")
    if margin is not None:
        parts.append(_clamp(min(margin * 2.0, 100)))
        ev.append(f"Net margin {margin:.1f}%")
    if debt_equity is not None:
        parts.append(_clamp(90 - debt_equity * 30))
        ev.append(f"D/E {debt_equity:.2f}")
    if not parts:
        return 50.0, ["No quality data — neutral"]
    return round(sum(parts) / len(parts), 1), ev


def score_value(pe=None, sector_pe=None, peg=None) -> tuple[float, list[str]]:
    ev: list[str] = []
    pe, sector_pe, peg = _num(pe), _num(sector_pe), _num(peg)
    if pe is None or pe <= 0:
        return 50.0, ["No P/E — neutral"]
    base = _clamp(90 - (pe - 5) * 3)  # ~5x -> 90, ~15x -> 60, ~25x -> 30
    ev.append(f"P/E {pe:.1f}x" + (f" vs sector {sector_pe:.1f}x" if sector_pe else ""))
    if sector_pe and sector_pe > 0:
        base = _clamp(base + (sector_pe - pe) * 2)
    if peg is not None:
        base = _clamp(base + (1.5 - peg) * 15)
        ev.append(f"PEG {peg:.2f}")
    return round(base, 1), ev


def score_risk(beta=None, drawdown=None, daily_value=None, suspended=False) -> tuple[float, list[str]]:
    ev: list[str] = []
    beta, drawdown, daily_value = _num(beta), _num(drawdown), _num(daily_value)
    if suspended:
        return 0.0, ["Suspended/restricted tag — excluded"]
    parts: list[float] = []
    if beta is not None:
        parts.append(_clamp(90 - abs(beta - 0.9) * 40))
        ev.append(f"Beta {beta:.2f}")
    if drawdown is not None:
        parts.append(_clamp(100 + drawdown * 2))  # drawdown negative, e.g. -12 -> 76
        ev.append(f"Max drawdown {drawdown:.0f}%")
    if daily_value is not None:
        import math
        parts.append(_clamp(30 + 10 * math.log10(max(daily_value, 1))))
        ev.append(f"Avg daily value ₦{daily_value:,.0f}")
    if not parts:
        return 50.0, ["No risk data — neutral"]
    return round(sum(parts) / len(parts), 1), ev


def score_dividend_div(yield_pct=None, streak_years=None) -> tuple[float, list[str]]:
    # Tie-break only (5% weight): growth investor, small absolute payouts.
    yield_pct = _num(yield_pct)
    if yield_pct is None:
        return 50.0, ["No dividend data — neutral (growth focus)"]
    s = _clamp(40 + (yield_pct or 0) * 4)
    ev = [f"Yield {yield_pct:.1f}%"]
    if streak_years:
        s = _clamp(s + min(streak_years, 5) * 2)
        ev.append(f"Paid {streak_years}y straight")
    return round(s, 1), ev


def composite(m, q, v, r, d, signal_adj: float = 0.0) -> float:
    total = (
        m * WEIGHTS["momentum"] + q * WEIGHTS["quality"]
        + v * WEIGHTS["value"] + r * WEIGHTS["risk_liquidity"]
        + d * WEIGHTS["dividend"]
    )
    return round(_clamp(total + max(-10.0, min(10.0, signal_adj))), 1)


def rank_candidates(candidates: list[dict]) -> list[dict]:
    """Attach factor scores + composite to each candidate dict. Pure function."""
    out = []
    for c in candidates:
        m, m_ev = score_momentum(**c.get("momentum", {}))
        q, q_ev = score_quality(**c.get("quality", {}))
        v, v_ev = score_value(**c.get("value", {}))
        r, r_ev = score_risk(**c.get("risk", {}))
        d, d_ev = score_dividend_div(**c.get("dividend", {}))
        adj = float(c.get("signal_adj", 0.0))
        out.append({**c, "factor_scores": {"momentum": m, "quality": q, "value": v,
                                           "risk_liquidity": r, "dividend": d},
                    "evidence": {"momentum": m_ev, "quality": q_ev, "value": v_ev,
                                 "risk_liquidity": r_ev, "dividend": d_ev,
                                 "signals": c.get("signal_notes", [])},
                    "score": composite(m, q, v, r, d, adj)})
    out.sort(key=lambda x: x["score"], reverse=True)
    for i, c in enumerate(out, 1):
        c["rank"] = i
    return out
