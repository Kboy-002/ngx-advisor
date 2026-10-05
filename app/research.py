"""Afrinvest Research weekly ingestion + ASI archive backfill.

Sources (free, public):
- RSS: https://afrinvest.substack.com/feed (latest ~20 editions)
- Archive API: https://afrinvest.substack.com/api/v1/archive?sort=new&limit=N&offset=M
  (paginable JSON — used once for the ~1yr ASI backfill)

Each edition's ASI close is regex-extracted ("ASI ... 98,233.76 points") and
also stored into market_snapshots so pick-vs-ASI has a real baseline.
Everything is best-effort: returns counts, never raises.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

log = logging.getLogger("ngx-research")

FEED_URL = "https://afrinvest.substack.com/feed"
ARCHIVE_URL = "https://afrinvest.substack.com/api/v1/archive"

ASI_PATTERNS = [
    # "…to 98,233.76 points" — Afrinvest's house style; first in-band hit wins.
    re.compile(r"([\d,]+\.\d{1,2})\s*points?", re.I),
    re.compile(r"(?:NGX-ASI|ASI|All-Share|All Share)[^\n]{0,120}?([\d,]+\.\d{2})", re.I),
    re.compile(r"(?:shed|rose|gained|lost|declined|advanced|closed|to)\s+([\d,]+\.\d{2})\s*points", re.I),
]


def extract_asi(text: str) -> float | None:
    for pat in ASI_PATTERNS:
        for m in pat.finditer(text or ""):
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if 20000 <= v <= 500000:  # plausible ASI band, guards false positives
                return v
    return None


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


def _store(published: date | None, title: str, url: str, summary: str) -> bool:
    import store

    asi = extract_asi(f"{title} {summary}")
    new = store.save_research_note(published, title[:300], url, (summary or "")[:4000], asi)
    if asi and published:
        try:
            store.save_market_snapshot(published, asi, "afrinvest_weekly")
        except Exception:
            pass
    return new


def fetch_weekly(max_items: int = 25) -> dict:
    """Pull the Substack RSS feed (recent editions)."""
    import feedparser

    fresh = seen = 0
    try:
        feed = feedparser.parse(FEED_URL)
        for e in (feed.entries or [])[:max_items]:
            seen += 1
            title = getattr(e, "title", "") or ""
            summary = re.sub(r"<[^>]+>", " ", getattr(e, "summary", "") or "")
            link = getattr(e, "link", "") or ""
            if not link:
                continue
            if _store(_parse_date(getattr(e, "published", None)), title, link, summary):
                fresh += 1
    except Exception as exc:
        log.warning("afrinvest rss failed: %s", exc)
    return {"seen": seen, "new": fresh}


def _fetch_page_text(url: str) -> str:
    import httpx
    from bs4 import BeautifulSoup

    r = httpx.get(url, timeout=30.0, follow_redirects=True,
                  headers={"User-Agent": "ngx-advisor/0.3 (personal research)"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    art = soup.find("article") or soup
    return art.get_text(" ", strip=True)[:12000]


def backfill_archive(max_editions: int = 60) -> dict:
    """Walk the public Substack archive, fetch each edition page, extract ASI.

    One-off (or rare) job: ~60 page fetches. Only editions whose title smells
    like the weekly market roundup are fetched.
    """
    import httpx

    fresh = checked = 0
    try:
        offset = 0
        posts: list[dict] = []
        while len(posts) < max_editions:
            r = httpx.get(ARCHIVE_URL, params={"sort": "new", "limit": 50, "offset": offset},
                          timeout=30.0)
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            posts.extend(batch)
            offset += len(batch)
            if len(batch) < 50:
                break
        for p in posts[:max_editions]:
            title = p.get("title", "") or ""
            low = title.lower()
            if not any(k in low for k in ("weekly", "market report", "round up", "roundup",
                                          "equities", "asi", "domestic")):
                continue
            url = p.get("canonical_url") or ("https://afrinvest.substack.com" + (p.get("slug") or ""))
            pub = None
            try:
                pub = datetime.fromisoformat((p.get("post_date") or "").replace("Z", "+00:00")).date()
            except (ValueError, AttributeError):
                pass
            checked += 1
            try:
                text = _fetch_page_text(url)
            except Exception as exc:
                log.warning("backfill page failed %s: %s", url, exc)
                continue
            if _store(pub, title, url, text):
                fresh += 1
    except Exception as exc:
        log.warning("backfill archive failed: %s", exc)
    log.info("backfill: %d weekly editions checked, %d new", checked, fresh)
    return {"checked": checked, "new": fresh}
