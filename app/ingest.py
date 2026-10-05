"""Free-first ingestion: NGX price-list scrape + NGN Market free tier.

MVP posture: never crash on source failure — scrape problems return []
and the scorer degrades to neutral rather than blocking the report.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from config import KOBO_API_KEY, KOBO_BASE, NGNMARKET_API_KEY, NGNMARKET_BASE, NGX_PRICE_LIST_URL, SUSPENDED_TAGS


def fetch_kobo_stocks() -> tuple[list[dict], dict | None]:
    """Kobo Terminal (ex NGX Pulse) — full NGX snapshot in 2 calls.

    GET /api/ngxdata/stocks  -> all 150+ equities (price, change, volume, sector, PE)
    GET /api/ngxdata/market  -> ASI + breadth. Personal (free) tier: 100 req/day.
    Returns (rows, market). Empty rows = no key or failure (caller falls back).
    """
    if not KOBO_API_KEY:
        return [], None
    headers = {"X-API-Key": KOBO_API_KEY}
    try:
        with httpx.Client(timeout=25.0, headers=headers) as c:
            rs = c.get(f"{KOBO_BASE}/api/ngxdata/stocks")
            if rs.status_code != 200:
                return [], None
            payload = rs.json()
            items = payload if isinstance(payload, list) else payload.get("data", payload.get("stocks", []))
            rows = []
            for it in items:
                sym = str(it.get("symbol", "")).strip().upper()
                if not sym or sym.startswith(("FG", "FGS")):
                    continue
                try:
                    close = float(it.get("current_price"))
                except (TypeError, ValueError):
                    continue
                rows.append({"symbol": sym, "close": close,
                             "change_pct": it.get("change_percent"),
                             "volume": it.get("volume"),
                             "sector": it.get("sector"), "name": it.get("name"),
                             "pe": it.get("pe_ratio"), "suspended": False, "tag": ""})
            market = None
            try:
                rm = c.get(f"{KOBO_BASE}/api/ngxdata/market")
                if rm.status_code == 200:
                    m = rm.json()
                    market = {"asi": m.get("asi"), "source": "kobo"}
            except Exception:
                pass
            return rows, market
    except Exception:
        return [], None


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


def fetch_asi() -> dict | None:
    """Best-effort ASI: NGN Market snapshot first (needs key), else NGX homepage regex."""
    import re as _re

    if NGNMARKET_API_KEY:
        try:
            r = httpx.get(f"{NGNMARKET_BASE}/market/snapshot", timeout=20.0,
                          headers={"Authorization": f"Bearer {NGNMARKET_API_KEY}"})
            if r.status_code == 200:
                j = r.json()
                asi = j.get("asi") or (j.get("data") or {}).get("asi")
                if asi:
                    return {"asi": float(asi), "source": "ngnmarket"}
        except Exception:
            pass
    try:
        r = httpx.get("https://ngxgroup.com/", timeout=30.0, follow_redirects=True,
                      headers={"User-Agent": "ngx-advisor/0.2 (personal research)"})
        m = _re.search(r"All.?Share Index[^0-9]*([\d,]+\.\d{2})", r.text, _re.I)
        if m:
            return {"asi": float(m.group(1).replace(",", "")), "source": "ngx_homepage"}
    except Exception:
        pass
    return None


def run_and_store() -> dict:
    """Daily EOD job body: prices + ASI into Postgres. Returns counts."""
    from datetime import date as _date

    import store

    today = _date.today()
    rows, market = fetch_kobo_stocks()
    source = "kobo"
    if not rows:
        rows = fetch_ngx_price_list()
        source = "ngx_scrape"
    n = store.upsert_prices(rows, today, source=source) if rows else 0
    # Sectors + P/E ride along with the Kobo snapshot — persist for scoring/guardrails.
    for r in rows:
        if r.get("sector") or r.get("name"):
            store.upsert_meta(r["symbol"], r.get("sector"), r.get("name"))
        if r.get("pe") is not None:
            try:
                store.upsert_fundamentals(r["symbol"], "latest", {"pe": float(r["pe"])}, source="kobo")
            except (TypeError, ValueError):
                pass
    asi = None
    if market and market.get("asi"):
        asi = market
    else:
        asi = fetch_asi()
    if asi and asi.get("asi"):
        store.save_market_snapshot(today, asi["asi"], asi.get("source", "auto"))
    # Best-effort fundamentals refresh for a rotating slice (free-quota friendly).
    if NGNMARKET_API_KEY and rows:
        import datetime as _dt
        day = _dt.date.today().timetuple().tm_yday
        universe = sorted({r["symbol"] for r in rows})
        part = [universe[(day + i) % len(universe)] for i in range(min(20, len(universe)))]
        snap = fetch_ngnmarket_snapshot(part)
        for sym, payload in snap.items():
            data = payload.get("data", payload) if isinstance(payload, dict) else {}
            fields = {k: data.get(k) for k in
                      ("pe", "pb", "eps", "roe", "profit_margin", "revenue_growth",
                       "eps_growth", "debt_equity", "dividend_yield") if data.get(k) is not None}
            if fields:
                store.upsert_fundamentals(sym, "latest", fields)
    return {"prices": n, "asi": asi}


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
