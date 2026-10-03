"""Signal collector — disclosures + press RSS, ticker-tagged, classified, stored.

Sources (all free, polite rate limits):
- Tier 1: NGX corporate disclosures page (filings)
- Tier 2: NGX Pulse disclosures feed (grouped filings)
- Tier 3: press RSS — Nairametrics, BusinessDay, Punch business (env-overridable)

Pipeline per item: fetch -> ticker-tag (symbol or company alias in
title/summary) -> classify (keyword rules -> event type) -> store (dedupe).
Rule-based by design (planning contract): collects + links with receipts,
human judges. Returns counts; never raises — scheduler must survive.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime

log = logging.getLogger("ngx-collector")

RSS_FEEDS = [f.strip() for f in os.getenv(
    "NEWS_RSS_FEEDS",
    "https://nairametrics.com/feed/,https://businessday.ng/feed/,https://punchng.com/topic/business/feed/",
).split(",") if f.strip()]

NGX_DISCLOSURES_URL = "https://ngxgroup.com/exchange/data/corporate-disclosures/"
NGXPULSE_DISCLOSURES_URL = "https://ngxpulse.ng/disclosures"

# Symbol -> aliases matched in headlines (extend as encountered).
ALIASES = {
    "FIRSTHOLDCO": ("firstbank", "first bank", "firstholdco", "fbn"),
    "ZENITHBANK": ("zenith",),
    "GTCO": ("gtco", "gtbank", "gt bank", "guaranty trust"),
    "MTNN": ("mtn nigeria", "mtnn"),
    "ARADEL": ("aradel",),
    "SEPLAT": ("seplat",),
    "BUAFOODS": ("bua foods",),
    "BUACEMENT": ("bua cement",),
    "DANGCEM": ("dangote cement",),
    "TRANSCORP": ("transcorp",),
    "TRANSPOWER": ("transpower", "transcorp power"),
    "OKOMUOIL": ("okomu",),
    "PRESCO": ("presco",),
    "FCMB": ("fcmb",),
    "UBA": ("uba ", "united bank for africa"),
    "ACCESSCORP": ("access bank", "accesscorp"),
    "NESTLE": ("nestle nigeria",),
    "GUINNESS": ("guinness nigeria",),
    "NB": ("nigerian breweries",),
    "AIRTELAFRI": ("airtel africa",),
    "ETRANZACT": ("etranzact",),
    "CHAMS": ("chams",),
    "CWG": ("cwg ",),
    "JBERGER": ("julius berger",),
}

# Ordered rules: first match wins. (keywords, event_type)
RULES = [
    (("acquisition", "acquires", "acquire", "merger", "takeover", "buyout", "completes purchase"), "M&A_DEAL"),
    (("insider", "stake", "accumulates", "increases stake", "acquires shares", "otedola", "director dealing"), "INSIDER_BUYING"),
    (("profit jumps", "profit surges", "beats", "record profit", "growth of", "q1", "q2", "q3", "full year", "results"), "EARNINGS_BEAT"),
    (("loss", "profit falls", "profit drops", "misses", "decline in profit"), "EARNINGS_MISS"),
    (("dividend", "payout", "final dividend", "interim dividend"), "DIVIDEND_DECLARED"),
    (("bonus issue", "share split", "stock split"), "BONUS_SPLIT"),
    (("lists on ngx", "listing by introduction", "ipo", "public offer"), "NEW_LISTING"),
    (("sec approves", "approval", "license", "regulatory"), "REGULATORY_APPROVAL"),
    (("appoints", "resigns", "new ceo", "new chairman", "board"), "MANAGEMENT_CHANGE"),
]


def tag_tickers(text: str) -> list[str]:
    t = f" {text.lower()} "
    found = []
    for sym, aliases in ALIASES.items():
        if sym.lower() in t or any(a in t for a in aliases):
            found.append(sym)
    return found


def classify(text: str) -> str:
    t = text.lower()
    for keywords, evt in RULES:
        if any(k in t for k in keywords):
            return evt
    return "OTHER"


def _parse_date(value) -> date | None:
    try:
        import email.utils as _eu
        if isinstance(value, str):
            return _eu.parsedate_to_datetime(value).date()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
    except Exception:
        pass
    return None


def collect_rss(max_items: int = 60) -> list[dict]:
    import feedparser

    import store

    fresh = 0
    items: list[dict] = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            src = getattr(feed.feed, "title", url)
            for e in (feed.entries or [])[:max_items]:
                title = getattr(e, "title", "") or ""
                summary = re.sub(r"<[^>]+>", " ", getattr(e, "summary", "") or "")[:500]
                link = getattr(e, "link", "") or None
                pub = _parse_date(getattr(e, "published", None) or getattr(e, "updated", None))
                for sym in tag_tickers(f"{title} {summary}"):
                    evt = classify(f"{title} {summary}")
                    sig = {"symbol": sym, "event_type": evt, "title": title[:300],
                           "url": link, "source": src, "source_tier": 3,
                           "published": pub, "confidence": "low"}
                    items.append(sig)
                    if store.add_signal(sig):
                        fresh += 1
        except Exception as exc:
            log.warning("rss %s failed: %s", url, exc)
    log.info("rss: %d tagged items, %d new", len(items), fresh)
    return items


def collect_disclosures() -> list[dict]:
    """Scrape NGX + Pulse disclosure listings for filing headlines (tier 1/2)."""
    import httpx
    from bs4 import BeautifulSoup

    import store

    items: list[dict] = []
    for url, tier, src in ((NGX_DISCLOSURES_URL, 1, "NGX disclosures"),
                           (NGXPULSE_DISCLOSURES_URL, 2, "NGX Pulse")):
        try:
            r = httpx.get(url, timeout=30.0, follow_redirects=True,
                          headers={"User-Agent": "ngx-advisor/0.2 (personal research)"})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True)[:200]:
                title = a.get_text(" ", strip=True)
                if len(title) < 25:
                    continue
                syms = tag_tickers(title)
                if not syms:
                    continue
                href = a["href"]
                link = href if href.startswith("http") else url.rstrip("/") + "/" + href.lstrip("/")
                for sym in syms:
                    sig = {"symbol": sym, "event_type": classify(title), "title": title[:300],
                           "url": link, "source": src, "source_tier": tier,
                           "published": date.today(),
                           "confidence": "high" if tier == 1 else "medium"}
                    items.append(sig)
                    store.add_signal(sig)
        except Exception as exc:
            log.warning("disclosures %s failed: %s", url, exc)
    log.info("disclosures: %d tagged items", len(items))
    return items


def run_all() -> dict:
    d = collect_disclosures()
    r = collect_rss()
    return {"disclosure_items": len(d), "rss_items": len(r)}
