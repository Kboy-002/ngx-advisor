"""Earnings-results extractor — turns press coverage into quality factors.

Pipeline: recent EARNINGS-tagged signals with URLs -> fetch article text ->
LLM extracts stated figures ONLY (revenue, PAT, EPS, YoY changes, period) ->
upsert into fundamentals (revenue_growth, eps_growth, profit_margin).
Deduped by URL. Weekly job; ~10 articles max per run (cost control).
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("ngx-earnings")

EXTRACT_RULES = """Extract ONLY figures explicitly stated in the article.
Return STRICT JSON: {"revenue_both": "e.g. ₦500bn or null", "revenue_yoy_pct": number|null,
"pat": "e.g. ₦50bn or null", "pat_yoy_pct": number|null, "eps": "e.g. ₦2.50 or null",
"period": "e.g. Q3 2026 / H1 2026 / FY2025 or null"}.
Numbers only, no commentary. If a figure is not stated, use null. No markdown fences."""


def _article_text(url: str) -> str:
    import httpx
    from bs4 import BeautifulSoup

    r = httpx.get(url, timeout=30.0, follow_redirects=True,
                  headers={"User-Agent": "ngx-advisor/0.4 (personal research)"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    art = soup.find("article") or soup
    return art.get_text(" ", strip=True)[:8000]


def _already_done(url: str) -> bool:
    import db as _db

    with _db.conn() as c:
        cur = c.execute("SELECT 1 FROM earnings_extracts WHERE url=%s", (url,))
        return cur.fetchone() is not None


def _mark_done(url: str, symbol: str, payload: dict) -> None:
    import json

    import db as _db

    with _db.conn() as c:
        c.execute(
            """INSERT INTO earnings_extracts (url, symbol, payload) VALUES (%s,%s,%s)
               ON CONFLICT (url) DO NOTHING""",
            (url, symbol, json.dumps(payload)),
        )


def run_earnings(max_articles: int = 10) -> dict:
    import db as _db
    import llm
    import store

    if not llm.is_configured():
        return {"skipped": "LLM_API_KEY not set"}
    store.ensure_schema()
    with _db.conn() as c:
        cur = c.execute(
            """SELECT symbol, title, url FROM signals
               WHERE event_type IN ('EARNINGS_BEAT','EARNINGS_MISS','EARNINGS')
               AND url IS NOT NULL AND created_at > now() - INTERVAL '30 days'
               ORDER BY created_at DESC LIMIT %s""", (max_articles * 3,))
        rows = cur.fetchall()
    done = extracted = 0
    for sym, title, url in rows:
        if done >= max_articles or _already_done(url):
            continue
        try:
            text = _article_text(url)
        except Exception as exc:
            log.warning("earnings fetch failed %s: %s", url, exc)
            continue
        if len(text) < 500 or not re.search(r"(revenue|profit|eps|earnings)", text, re.I):
            _mark_done(url, sym, {"skipped": "no figures"})
            continue
        try:
            data = llm.chat_json(EXTRACT_RULES,
                                 f"COMPANY: {sym}\nHEADLINE: {title}\n\n{text[:6000]}",
                                 max_tokens=400, temperature=0.0)
        except Exception as exc:
            log.warning("earnings extract failed %s: %s", url, exc)
            continue
        done += 1
        _mark_done(url, sym, data)
        fields: dict = {}
        if isinstance(data.get("revenue_yoy_pct"), (int, float)):
            fields["revenue_growth"] = float(data["revenue_yoy_pct"])
        yoy = data.get("pat_yoy_pct")
        if isinstance(yoy, (int, float)):
            fields["eps_growth"] = float(yoy)
        try:
            rev = _to_bn(data.get("revenue_both", data.get("revenue")))
            pat = _to_bn(data.get("pat"))
            if rev and pat:
                fields["profit_margin"] = round(pat / rev * 100, 1)
        except (TypeError, ValueError):
            pass
        if data.get("eps") is not None:
            try:
                fields["eps"] = float(str(data["eps"]).replace("₦", "").replace(",", ""))
            except (TypeError, ValueError):
                pass
        if fields:
            store.upsert_fundamentals(sym, "latest", fields, source="earnings_llm")
            extracted += 1
    return {"articles_read": done, "symbols_updated": extracted}


def _to_bn(raw) -> float | None:
    """'₦500bn' / '500 billion' / '500m' -> billions float."""
    if raw is None:
        return None
    s = str(raw).lower().replace("₦", "").replace(",", "").strip()
    m = re.search(r"([\d.]+)\s*(trn|trillion|bn|billion|m|million)?", s)
    if not m:
        return None
    v = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit.startswith("tr"):
        return v * 1000
    if unit.startswith("m"):
        return v / 1000
    return v
