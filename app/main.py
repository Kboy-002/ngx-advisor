"""NGX Advisor API — ingest status, Afrinvest parse, scoring demo, allocation."""
from __future__ import annotations

from fastapi import FastAPI, File, UploadFile
from pydantic import BaseModel, Field

import allocator
import ingest
import scoring
from parser_afrinvest import parse_pdf_bytes, weekly_verdicts
from signals import overlay_for

app = FastAPI(title="NGX Advisor", version="0.1.0")


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
    return {**snap, "verdicts": weekly_verdicts(snap)}


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
