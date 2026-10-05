"""NGX Advisor API — ingest status, Afrinvest parse, scoring demo, allocation."""
from __future__ import annotations

from fastapi import FastAPI, File, UploadFile
from pydantic import BaseModel, Field

import allocator
import ingest
import scoring
import store
from parser_afrinvest import parse_pdf_bytes, weekly_verdicts
from signals import overlay_for

app = FastAPI(title="NGX Advisor", version="0.2.0")


@app.on_event("startup")
def _startup():
    try:
        store.ensure_schema()
    except Exception:
        pass  # DB may be down; endpoints degrade gracefully


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/ingest/status")
def ingest_status():
    rows = ingest.fetch_ngx_price_list()
    return {"symbols": len(rows), "sample": rows[:5]}


@app.post("/portfolio/parse")
async def portfolio_parse(file: UploadFile = File(...)):
    data = await file.read()
    snap = parse_pdf_bytes(data)
    try:
        store.save_holdings_snapshot(snap)
    except Exception:
        pass
    return {**snap, "verdicts": weekly_verdicts(snap)}


@app.post("/ingest/run")
def ingest_run():
    """Run the daily EOD pipeline now (prices + ASI + rotating fundamentals)."""
    try:
        return ingest.run_and_store()
    except Exception as exc:
        return {"error": str(exc), "prices": 0}


@app.post("/signals/collect")
def signals_collect():
    import collector

    try:
        return collector.run_all()
    except Exception as exc:
        return {"error": str(exc)}


class PickRequest(BaseModel):
    cash: float = Field(gt=0)
    month: str | None = None  # 'YYYY-MM', defaults to current


@app.post("/picks/generate")
def picks_generate(req: PickRequest):
    import pick as pickpipe

    try:
        return pickpipe.generate_monthly_pick(req.cash, req.month)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/picks")
def picks_list():
    try:
        return {"picks": store.list_picks()}
    except Exception as exc:
        return {"picks": [], "error": str(exc)}


@app.get("/picks/{month}/performance")
def picks_performance(month: str):
    import pick as pickpipe

    try:
        return pickpipe.pick_performance(month)
    except KeyError:
        return {"error": f"no pick stored for {month}"}
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/portfolio/latest")
def portfolio_latest():
    try:
        snap = store.latest_holdings()
        if not snap:
            return {"holdings": [], "empty": True}
        return {**snap, "empty": False, "verdicts": weekly_verdicts(snap)}
    except Exception as exc:
        return {"holdings": [], "empty": True, "error": str(exc)}


@app.get("/status")
def status():
    """Feed freshness for the sidebar dot: ASI date, symbols, signals, picks."""
    out: dict = {"api": True}
    try:
        out["asi"] = store.latest_asi()
        with __import__("db").conn() as c:
            out["symbols"] = c.execute("SELECT COUNT(DISTINCT symbol) FROM prices_eod").fetchone()[0]
            out["signals_7d"] = c.execute(
                "SELECT COUNT(*) FROM signals WHERE created_at > now() - INTERVAL '7 days'").fetchone()[0]
            out["picks"] = c.execute("SELECT COUNT(*) FROM picks").fetchone()[0]
    except Exception as exc:
        out["error"] = str(exc)
    return out


class AnalystRequest(BaseModel):
    cash: float = Field(gt=0)
    month: str | None = None


@app.post("/analyst/monthly")
def analyst_monthly(req: AnalystRequest):
    import analyst as analystmod

    try:
        return analystmod.monthly_analysis(req.cash, req.month)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/analyst/monthly/{month}")
def analyst_monthly_get(month: str):
    try:
        res = store.get_analysis(month)
        return res or {"error": f"no analysis stored for {month}"}
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/analyst/weekly")
def analyst_weekly():
    import analyst as analystmod

    try:
        return analystmod.weekly_digest()
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/analyst/weekly/latest")
def analyst_weekly_latest():
    try:
        res = store.get_latest_digest()
        return res or {"empty": True}
    except Exception as exc:
        return {"empty": True, "error": str(exc)}


@app.post("/research/fetch")
def research_fetch(backfill: bool = False):
    import research as researchmod

    try:
        out = researchmod.fetch_weekly()
        if backfill:
            out["backfill"] = researchmod.backfill_archive()
        out["editions"] = len(store.latest_research(200))
        return out
    except Exception as exc:
        return {"error": str(exc)}


class Candidate(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    momentum: dict = {}
    quality: dict = {}
    value: dict = {}
    risk: dict = {"suspended": False}
    dividend: dict = {}
    risks: list[str] = []


class RankRequest(BaseModel):
    candidates: list[Candidate]
    events_by_symbol: dict[str, list[dict]] = {}


@app.post("/rank")
def rank(req: RankRequest):
    cands = []
    for c in req.candidates:
        d = c.model_dump()
        evts = req.events_by_symbol.get(d["symbol"], [])
        adj, notes = overlay_for(evts)
        d["signal_adj"] = adj
        d["signal_notes"] = notes
        cands.append(d)
    return {"ranked": scoring.rank_candidates(cands)}


class AllocateRequest(BaseModel):
    cash: float = Field(gt=0)
    ranked: list[dict]
    portfolio: dict | None = None


@app.post("/allocate")
def allocate(req: AllocateRequest):
    return {"allocations": allocator.allocate(req.cash, req.ranked, req.portfolio)}
