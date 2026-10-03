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
