"""Afrinvest Valuation Statement PDF parser.

Matched to the real layout (Sept 25 – Oct 2, 2026 statement):
Holdings page columns:
  Mrkt | Symbol | Quantity | Avg. Cost | Dividend | Total Cost |
  Price | Gain/(Loss) | Gain/(Loss) % | Value | Acct. %
Plus: account number (0000051128), statement dates, cash balance from the
Investment Asset Summary page ("Cash, Money Funds & Bank Deposits" closing value).

Tolerant: finds the Holdings table by header keywords, skips wrapped lines,
handles comma/parenthesis negatives like (5,235.55).
"""
from __future__ import annotations

import re
from datetime import date

NUM = r"[\d,]+\.\d{2}|[\d,]+"

HEADER_KEYS = ("symbol", "quantity", "avg", "total cost", "price", "gain", "value", "acct")


def _to_float(raw: str) -> float:
    s = raw.strip().replace(",", "").replace("₦", "").replace("N", "", 1) if False else raw.strip()
    s = raw.strip().replace(",", "").replace("₦", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    if s in ("-", "", "--"):
        return 0.0
    # strip stray leading currency letter left by the Naira sign decode
    s = re.sub(r"^[A-Za-z]+", "", s)
    try:
        v = float(s)
    except ValueError:
        return 0.0
    return -v if neg else v


def parse_holdings_text(text: str) -> dict:
    """Parse pdfplumber-extracted text. Returns snapshot dict (no DB writes)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    account_no = ""
    m = re.search(r"Account:\s*NGN\s*-\s*(\d+)", text)
    if m:
        account_no = m.group(1)

    stmt_from = stmt_to = None
    m = re.search(
        r"Valuation Statement\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})\s+to\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})",
        text,
    )
    if m:
        from datetime import datetime as _dt

        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                stmt_from = _dt.strptime(m.group(1).strip(), fmt).date()
                stmt_to = _dt.strptime(m.group(2).strip(), fmt).date()
                break
            except ValueError:
                continue

    cash_balance = 0.0
    m = re.search(
        r"Cash,\s*Money Funds & Bank Deposits\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})", text
    )
    if m:
        cash_balance = _to_float(m.group(2))

    holdings: list[dict] = []
    in_table = False
    for ln in lines:
        low = ln.lower()
        if not in_table:
            if all(k in low for k in ("symbol", "quantity")) and "acct" in low:
                in_table = True
            continue
        if low.startswith("total") or low.startswith("valuation statement") or low.startswith("activity"):
            # 'Total' row ends the holdings table (first occurrence).
            if low.startswith("total"):
                break
            continue
        # Expected row: NGX SYMBOL qty avg ... price gain pct value acctpct
        parts = re.split(r"\s{2,}|\t", ln)
        if len(parts) < 8:
            parts = ln.split()
        if len(parts) < 9 or parts[0] != "NGX":
            continue
        try:
            symbol = parts[1].strip().upper()
            quantity = _to_float(parts[2])
            # Avg cost is parts[3]; dividend parts[4] ('-'); total cost parts[5]
            price = _to_float(parts[6])
            value = _to_float(parts[-2])
            acct_pct = _to_float(parts[-1])
            gain_pct_raw = parts[-3]
            gain_pct = _to_float(re.sub(r"[↑↓]", "", gain_pct_raw))
            holdings.append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "avg_cost": _to_float(parts[3]),
                    "price": price,
                    "total_cost": _to_float(parts[5]),
                    "value": value,
                    "acct_pct": acct_pct,
                    "gain_pct": gain_pct,
                }
            )
        except (IndexError, ValueError):
            continue

    total_value = round(sum(h["value"] for h in holdings) + cash_balance, 2)
    return {
        "account_no": account_no,
        "statement_from": str(stmt_from) if stmt_from else None,
        "statement_to": str(stmt_to) if stmt_to else None,
        "cash_balance": cash_balance,
        "total_value": total_value,
        "holdings": holdings,
    }


def parse_pdf_bytes(data: bytes) -> dict:
    import pdfplumber

    with pdfplumber.open(__import__("io").BytesIO(data)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    return parse_holdings_text(text)


def weekly_verdicts(snapshot: dict) -> list[dict]:
    """Simple Saturday rules over the parsed snapshot (Phase 1 heuristics)."""
    out = []
    for h in snapshot.get("holdings", []):
        s, g, w = h["symbol"], h.get("gain_pct", 0), h.get("acct_pct", 0)
        if w < 0.5 and abs(h.get("value", 0)) < 2000:
            out.append({"symbol": s, "verdict": "TIDY-UP CANDIDATE",
                        "reason": f"Only ₦{h.get('value', 0):,.0f} ({w}% of account) — adds clutter, consider consolidating."})
        elif g <= -25:
            out.append({"symbol": s, "verdict": "PAUSE ADDING",
                        "reason": f"Down {g:.1f}% from cost — hold existing, don't average down blindly until thesis re-checks."})
        elif g <= -8:
            out.append({"symbol": s, "verdict": "HOLD / WATCH",
                        "reason": f"Down {abs(g):.1f}% — watch next earnings/disclosure before adding."})
        elif w >= 25:
            out.append({"symbol": s, "verdict": "HOLD / PAUSE ADDING",
                        "reason": f"Concentrated at {w}% — great winner, but pause fresh buys to avoid over-concentration."})
        elif g >= 50:
            out.append({"symbol": s, "verdict": "HOLD",
                        "reason": f"Up {g:.1f}% — let the winner run; fresh cash better diversifies elsewhere."})
        else:
            out.append({"symbol": s, "verdict": "HOLD",
                        "reason": "Within normal range — no action."})
    return out
