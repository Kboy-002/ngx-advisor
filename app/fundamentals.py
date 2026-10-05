"""Free fundamentals: NGX official P/E PDFs + topchor per-stock pages.

1. NGX doclib publishes "Current Equity P/E Ratios" PDFs (weekly, Fridays):
   https://doclib.ngxgroup.com/DownloadsContent/P.E%20RATIO%20FOR%20DD-MM-YYYY.pdf
   Columns: Symbol | Security Name | Capitalisation | P/E Ratio | Ratio.
   Authoritative, no login, no bot-wall. Primary source for P/E + market cap.
2. topchor.com/stocks/<SYMBOL>/ — server-rendered prose with P/E, EPS (₦),
   dividend yield, RSI. Secondary source + fills div yield/RSI.

Both best-effort. A weekly Friday-evening job runs this (fresh P/E PDFs
drop on Fridays). Respectful pace: ~1.5s between page fetches.
"""
from __future__ import annotations

import io
import logging
import re
import time
from datetime import date, timedelta

log = logging.getLogger("ngx-fundamentals")

UA = {"User-Agent": "ngx-advisor/0.4 (personal research; weekly fundamentals)"}
PE_URL = "https://doclib.ngxgroup.com/DownloadsContent/P.E%20RATIO%20FOR%20{}.pdf"

ROW_RE = re.compile(
    r"^([A-Z][A-Z0-9]{2,14})\s+(.+?)\s+([\d,]+\.\d{2})"
    r"(?:\s+([\d,]+\.\d+))?(?:\s+([\d.]+))?\s*$"
)

# topchor renders a metrics strip: "P/E Ratio 5.8900 EPS 22.4000 Dividend Yield 9.6700% …"
# plus prose fallbacks ("P/E ratio of 5.8900", "dividend yield of 9.67%").
LABEL_RE = re.compile(
    r"(P/E Ratio|EPS|Dividend Yield|Price to Book|ROE|RSI|MACD Signal|MACD)"
    r"\s+([₦\d,.\-—–%]+)"
)
PROSE_RES = {
    "pe": [re.compile(r"P/E ratio of\s+([\d,.]+)", re.I)],
    "eps": [re.compile(r"\bEPS of\s+₦?\s*([\d,.]+)", re.I)],
    "div_yield": [re.compile(r"dividend yield of\s+([\d,.]+)\s*%", re.I)],
    "roe": [re.compile(r"\bROE of\s+([\d,.]+)\s*%", re.I)],
}

KEYMAP = {"P/E Ratio": "pe", "EPS": "eps", "Dividend Yield": "div_yield",
          "ROE": "roe", "RSI": "rsi"}


def _num(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def fetch_ngx_pe_pdf(day: date | None = None, lookback: int = 8) -> tuple[dict, str | None]:
    """Download the latest weekly P/E PDF. Returns ({symbol: {pe, mcap}}, date_str)."""
    import httpx
    import pdfplumber

    day = day or date.today()
    with httpx.Client(timeout=40.0, headers=UA) as c:
        for back in range(lookback):
            d = day - timedelta(days=back)
            tag = d.strftime("%d-%m-%Y")
            url = PE_URL.format(tag).replace(" ", "%20")
            try:
                r = c.get(url)
                if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                    continue
                out: dict = {}
                with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                    for page in pdf.pages:
                        for line in (page.extract_text() or "").splitlines():
                            line = line.strip()
                            if not line or "Total" in line or line.startswith(("Symbol", "Market", "Copyright")):
                                continue
                            m = ROW_RE.match(line)
                            if not m:
                                continue
                            sym = m.group(1)
                            if sym.startswith(("FG", "FGS", "FGB")) or len(sym) > 14:
                                continue
                            out[sym] = {"pe": _num(m.group(4)), "mcap": _num(m.group(3))}
                if out:
                    log.info("ngx pe pdf %s: %d symbols", tag, len(out))
                    return out, tag
            except Exception as exc:
                log.warning("pe pdf %s failed: %s", tag, exc)
    return {}, None


def fetch_topchor(symbol: str) -> dict:
    """Scrape one topchor stock page. Returns {pe, eps, div_yield, roe, rsi} (sparse)."""
    import httpx
    from bs4 import BeautifulSoup

    try:
        r = httpx.get(f"https://topchor.com/stocks/{symbol}/", timeout=25.0,
                      headers=UA, follow_redirects=True)
        if r.status_code != 200:
            return {}
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        out: dict = {}
        for m in LABEL_RE.finditer(text):
            key = KEYMAP.get(m.group(1))
            if not key or key in out:
                continue
            raw = m.group(2).strip("₦% ")
            if raw in ("—", "–", "-", ""):
                continue
            v = _num(raw)
            if v is None:
                continue
            # sanity bands
            if key == "pe" and not (-5 <= v <= 500):
                continue
            if key == "rsi" and not (0 <= v <= 100):
                continue
            if key in ("div_yield", "roe") and not (0 <= v <= 150):
                continue
            out[key] = v
        if not out:  # prose fallback
            for key, pats in PROSE_RES.items():
                for pat in pats:
                    mm = pat.search(text)
                    if mm and _num(mm.group(1)) is not None:
                        out[key] = _num(mm.group(1))
                        break
        return out
    except Exception as exc:
        log.warning("topchor %s failed: %s", symbol, exc)
        return {}


def run_fundamentals(symbols: list[str] | None = None, pace: float = 1.5) -> dict:
    """Full weekly refresh: NGX P/E PDF + topchor pages. Persists to DB.

    P/E policy (the NGX PDF column is polluted by micro/negative earnings):
    primary = live price / topchor EPS (same methodology, current price);
    fallback = NGX PDF value only when 0 < pe <= 60.
    """
    import store

    store.ensure_schema()
    pe_map, pe_date = fetch_ngx_pe_pdf()
    live = {p["symbol"]: p["close"] for p in store.latest_prices()}
    pe_n = div_n = eps_n = 0
    if symbols is None:
        symbols = sorted({p["symbol"] for p in store.latest_prices()})
    for i, sym in enumerate(symbols):
        fields: dict = {}
        tc = fetch_topchor(sym)
        if tc.get("eps"):
            fields["eps"] = tc["eps"]
            eps_n += 1
            if live.get(sym):
                try:
                    fields["pe"] = round(float(live[sym]) / float(tc["eps"]), 3)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
        if fields.get("pe") is None:
            pdf_pe = (pe_map.get(sym) or {}).get("pe")
            if pdf_pe is not None and 0 < pdf_pe <= 60:
                fields["pe"] = pdf_pe
        for k in ("div_yield", "roe"):
            if tc.get(k) is not None:
                fields[k] = tc[k]
        if fields:
            keep = {k: v for k, v in fields.items() if k in
                    ("pe", "eps", "div_yield", "roe", "revenue_growth", "eps_growth",
                     "profit_margin", "debt_equity", "pb", "dividend_yield")}
            if "div_yield" in keep and "dividend_yield" not in keep:
                keep["dividend_yield"] = keep.pop("div_yield")
            if keep:
                store.upsert_fundamentals(sym, "latest", keep, source="free_fund")
                if "pe" in keep:
                    pe_n += 1
                if "dividend_yield" in keep:
                    div_n += 1
        if pe_map.get(sym, {}).get("mcap"):
            store.upsert_meta(sym, None, None, pe_map[sym]["mcap"])
        if i < len(symbols) - 1:
            time.sleep(pace)
    return {"pe_pdf_date": pe_date, "pe_symbols": len(pe_map),
            "stored_with_pe": pe_n, "stored_with_yield": div_n,
            "stored_with_eps": eps_n, "universe": len(symbols)}
