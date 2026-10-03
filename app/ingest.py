"""Free-first ingestion: NGX price-list scrape + NGN Market free tier.

MVP posture: never crash on source failure — scrape problems return []
and the scorer degrades to neutral rather than blocking the report.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from config import NGNMARKET_API_KEY, NGNMARKET_BASE, NGX_PRICE_LIST_URL, SUSPENDED_TAGS


def fetch_ngx_price_list(url: str = NGX_PRICE_LIST_URL, timeout: float = 30.0) -> list[dict]:
    """Scrape the public NGX equities price list. Returns [{symbol, close, change_pct, suspended}]."""
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "ngx-advisor/0.1 (personal research)"})
        r.raise_for_status()
    except Exception:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    # Pattern like: SYMBOL N123.45 +1.23 %  (also handles [TAGS] after symbol)
    pat = re.compile(r"([A-Z][A-Z0-9.\-]{1,20}(?:\s*\[[A-Z]+\])?)\s+N([\d,]+\.\d{2})\s+([+-]?[\d.]+)\s*%")
    out: list[dict] = []
    for m in pat.finditer(text):
        raw_sym = m.group(1)
        tag = ""
        tm = re.search(r"\[([A-Z]+)\]", raw_sym)
        if tm:
            tag = f"[{tm.group(1)}]"
        symbol = re.sub(r"\s*\[[A-Z]+\]", "", raw_sym).strip()
        if len(symbol) > 15 or symbol.startswith("FG") or symbol.startswith("FGS"):
            continue  # skip bonds/savings series on the same page
        out.append({"symbol": symbol,
                    "close": float(m.group(2).replace(",", "")),
                    "change_pct": float(m.group(3)),
                    "suspended": tag in SUSPENDED_TAGS or bool(tag and tag not in ("",)),
                    "tag": tag})
    # Dedupe keeping last.
    seen: dict[str, dict] = {}
    for row in out:
        seen[row["symbol"]] = row
    return sorted(seen.values(), key=lambda x: x["symbol"])


def fetch_ngnmarket_snapshot(symbols: list[str]) -> dict:
    """Best-effort NGN Market fetch (needs free API key). Returns {symbol: {...}}."""
    if not NGNMARKET_API_KEY or not symbols:
        return {}
    out: dict = {}
    try:
        with httpx.Client(timeout=20.0, headers={"Authorization": f"Bearer {NGNMARKET_API_KEY}"}) as c:
            for s in symbols[:60]:  # stay inside the free quota
                try:
                    r = c.get(f"{NGNMARKET_BASE}/companies/{s}")
                    if r.status_code == 200:
                        out[s] = r.json()
                except Exception:
                    continue
    except Exception:
        return {}
    return out
