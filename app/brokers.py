"""Broker research ingestion — free CardinalStone PDFs (Ticket 1).

The portal (research.cardinalstone.com/reports) server-renders report records
as embedded JSON: report_name, date, company_name, report_type, preview
(often with target price), file_url (direct PDF, no login). We take the
newest company updates/earnings first, download (capped), and LLM-extract
ratio tables: ROE, P/B, debt/equity, EPS, target price, recommendation.
Deduped by URL. Weekly Saturday job.
"""
from __future__ import annotations

import io
import json
import logging
import re

log = logging.getLogger("ngx-brokers")

UA = {"User-Agent": "ngx-advisor/0.5 (personal research; weekly broker notes)"}
REPORTS_URL = "https://research.cardinalstone.com/reports"
BROKER = "cardinalstone"

OBJ_RE = re.compile(r"\{[^{}]*?\"file_url\":\"(.*?)\"[^{}]*?\}")
FIELD_RES = {
    "report_name": re.compile(r"\"report_name\":\"(.*?)\"(?=,\"|\"\})"),
    "date": re.compile(r"\"date\":\"(\d{4}-\d{2}-\d{2})\""),
    "company": re.compile(r"\"company_name\":\"(.*?)\""),
    "rtype": re.compile(r"\"report_type\":\"(.*?)\""),
    "preview": re.compile(r"\"preview\":\"(.*?)\"(?=,\"|\"\})"),
}
TICKER_RE = re.compile(r"NGX:\s*([A-Z][A-Z0-9]{1,13})")

SKIP_TITLE_RES = [
    re.compile(p, re.I) for p in
    ("model equity portfolio", r"\bmpr\b", "inflation", "macro", "market report",
     "daily", "weekly", "flashnote", "pre-earnings", "outlook 20", "strategy 20",
     "fixed income", "bond", "treasury")
]
KEEP_TITLE_RES = [
    re.compile(p, re.I) for p in
    ("company update", "earnings update", "initiation", "coverage", "update", "results")
]


def _is_company_note(rep: dict) -> bool:
    title = rep.get("title") or ""
    if rep.get("ticker"):
        return True
    if any(p.search(title) for p in SKIP_TITLE_RES):
        return False
    return any(p.search(title) for p in KEEP_TITLE_RES)

EXTRACT_RULES = """From this broker research note, extract ONLY stated figures.
Look everywhere INCLUDING trailing 'Ratio Analysis' and 'Valuation' tables.
Return STRICT JSON: {"symbol": "NGX ticker", "period": "e.g. H1'26 / FY2025 or null",
"roe_pct": number|null, "pb": number|null, "debt_equity": number|null,
"eps": number|null (naira), "target_price": number|null (naira),
"recommendation": "BUY"|"HOLD"|"SELL"|null,
"revenue_growth_pct": number|null, "pat_growth_pct": number|null}.
No commentary, no invented numbers, no markdown fences."""


def _unescape(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except Exception:
        return s.replace("\\/", "/").replace("\\'", "'")


def list_reports() -> list[dict]:
    import httpx

    r = httpx.get(REPORTS_URL, timeout=40.0, headers=UA)
    r.raise_for_status()
    out: list[dict] = []
    for m in OBJ_RE.finditer(r.text):
        raw_obj = m.group(0)
        try:
            rec = json.loads(raw_obj.replace("\\'", "'"))
        except Exception:
            rec = {}
            for k, pat in FIELD_RES.items():
                mm = pat.search(raw_obj)
                rec[k] = _unescape(mm.group(1)) if mm else None
            f = re.search(r"\"file_url\":\"(.*?)\"", raw_obj)
            rec["file_url"] = _unescape(f.group(1)) if f else None
        if not rec.get("file_url"):
            continue
        url = rec["file_url"].replace("\\/", "/")
        ticker = None
        for txt in (rec.get("preview") or "", rec.get("report_name") or ""):
            mm = TICKER_RE.search(txt)
            if mm:
                ticker = mm.group(1)
                break
        out.append({"url": url, "title": rec.get("report_name"),
                    "date": rec.get("date"), "company": rec.get("company_name"),
                    "rtype": rec.get("rtype"), "preview": rec.get("preview"),
                    "ticker": ticker})
    # newest first; company-specific research before model portfolios
    def _key(x):
        generic = 1 if not x["ticker"] else 0
        return (generic, x.get("date") or "")
    return sorted(out, key=_key, reverse=True)


def _pdf_text(url: str, limit: int = 40000) -> str:
    import httpx
    import pdfplumber

    r = httpx.get(url, timeout=60.0, headers=UA, follow_redirects=True)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise ValueError("not a PDF")
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    text = text[:limit]
    # Ratio tables live at the END of broker notes — keep head + tail.
    if len(text) > 12000:
        text = text[:3000] + "\n...[middle trimmed]...\n" + text[-9000:]
    return text


def run_brokers(max_pdfs: int = 8, retry_empty: bool = True) -> dict:
    import llm
    import store

    if not llm.is_configured():
        return {"skipped": "LLM_API_KEY not set"}
    store.ensure_schema()
    if retry_empty:
        try:
            import db as _db
            with _db.conn() as c:
                cur = c.execute(
                    """DELETE FROM broker_views
                       WHERE (payload->>'symbol') IS NULL
                       AND payload::text NOT LIKE '%download failed%'
                       AND payload::text NOT LIKE '%no text%'""")
                log.info("broker retry: cleared %s empty rows", cur.rowcount)
        except Exception as exc:
            log.warning("broker retry clear failed: %s", exc)
    try:
        reports = list_reports()
    except Exception as exc:
        return {"error": f"listing failed: {exc}"}
    done = updated = 0
    skipped_macro = 0
    for rep in reports:
        if done >= max_pdfs:
            break
        if not _is_company_note(rep):
            skipped_macro += 1
            continue
        if store.has_broker_view(rep["url"]):
            continue
        try:
            text = _pdf_text(rep["url"])
        except Exception as exc:
            log.warning("broker pdf failed %s: %s", rep["url"], exc)
            store.save_broker_view(rep["url"], BROKER, rep["ticker"], None, None, None, {"error": "download failed"})
            continue
        if len(text) < 800:
            store.save_broker_view(rep["url"], BROKER, rep["ticker"], None, None, None, {"error": "no text"})
            continue
        try:
            data = llm.chat_json(EXTRACT_RULES,
                                 f"SOURCE: {rep['title']} ({rep['date']})\n\n{text[:10000]}",
                                 max_tokens=600, temperature=0.0)
        except Exception as exc:
            log.warning("broker extract failed %s: %s", rep["url"], exc)
            continue
        done += 1
        sym = (data.get("symbol") or rep["ticker"] or "").upper() or None
        rec = data.get("recommendation")
        tp = _num(data.get("target_price"))
        store.save_broker_view(rep["url"], BROKER, sym, data.get("period"), rec, tp, data)
        fields: dict = {}
        if isinstance(data.get("roe_pct"), (int, float)):
            fields["roe"] = float(data["roe_pct"])
        if isinstance(data.get("pb"), (int, float)):
            fields["pb"] = float(data["pb"])
        if isinstance(data.get("debt_equity"), (int, float)):
            fields["debt_equity"] = float(data["debt_equity"])
        if isinstance(data.get("eps"), (int, float)):
            fields["eps"] = float(data["eps"])
        if isinstance(data.get("revenue_growth_pct"), (int, float)):
            fields["revenue_growth"] = float(data["revenue_growth_pct"])
        if isinstance(data.get("pat_growth_pct"), (int, float)):
            fields["eps_growth"] = float(data["pat_growth_pct"])
        if sym and fields:
            store.upsert_fundamentals(sym, "latest", fields, source="broker_cardinalstone")
            updated += 1
    return {"reports_seen": len(reports), "pdfs_read": done, "symbols_updated": updated,
            "macro_skipped": skipped_macro}


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "")) if v is not None else None
    except (TypeError, ValueError):
        return None
