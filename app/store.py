"""Persistence layer — every table write goes through here.

ensure_schema() mirrors db/init.sql plus Phase-2 tables so an existing
pgdata volume (created by Phase 1) upgrades itself on next app boot.
"""
from __future__ import annotations

from datetime import date

from db import conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices_eod (
  symbol TEXT NOT NULL, trade_date DATE NOT NULL,
  close NUMERIC, open NUMERIC, high NUMERIC, low NUMERIC,
  volume BIGINT, value NUMERIC, day_change_pct NUMERIC,
  source TEXT DEFAULT 'ngx_scrape',
  PRIMARY KEY (symbol, trade_date)
);
CREATE TABLE IF NOT EXISTS fundamentals (
  symbol TEXT NOT NULL, period TEXT NOT NULL,
  pe NUMERIC, pb NUMERIC, eps NUMERIC, roe NUMERIC, profit_margin NUMERIC,
  revenue_growth NUMERIC, eps_growth NUMERIC, debt_equity NUMERIC,
  dividend_yield NUMERIC, fcf_margin NUMERIC,
  source TEXT DEFAULT 'ngnmarket_free', updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (symbol, period)
);
CREATE TABLE IF NOT EXISTS holdings_snapshots (
  id SERIAL PRIMARY KEY, uploaded_at TIMESTAMPTZ DEFAULT now(),
  statement_from DATE, statement_to DATE, account_no TEXT,
  total_value NUMERIC, cash_balance NUMERIC, holdings JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS cash_inputs (
  id SERIAL PRIMARY KEY, month TEXT NOT NULL UNIQUE,
  amount NUMERIC NOT NULL, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS signals (
  id SERIAL PRIMARY KEY, symbol TEXT NOT NULL, event_type TEXT NOT NULL,
  title TEXT NOT NULL, url TEXT, source TEXT, source_tier INT DEFAULT 3,
  published DATE, confidence TEXT DEFAULT 'medium',
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE UNIQUE INDEX IF NOT EXISTS uq_signals_dedupe
  ON signals(symbol, event_type, COALESCE(url, title));
CREATE TABLE IF NOT EXISTS market_snapshots (
  trade_date DATE PRIMARY KEY, asi NUMERIC,
  volume BIGINT, value NUMERIC, deals BIGINT, source TEXT DEFAULT 'auto'
);
CREATE TABLE IF NOT EXISTS symbol_meta (
  symbol TEXT PRIMARY KEY, sector TEXT, name TEXT, updated_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE prices_eod ADD COLUMN IF NOT EXISTS week_change_pct NUMERIC;
ALTER TABLE prices_eod ADD COLUMN IF NOT EXISTS volume BIGINT;
CREATE TABLE IF NOT EXISTS research_notes (
  id SERIAL PRIMARY KEY, published DATE, title TEXT NOT NULL,
  url TEXT UNIQUE, summary TEXT, asi_close NUMERIC,
  source TEXT DEFAULT 'afrinvest_substack', created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analyses (
  id SERIAL PRIMARY KEY, month TEXT NOT NULL UNIQUE,
  payload JSONB NOT NULL, model TEXT, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS digests (
  id SERIAL PRIMARY KEY, week TEXT NOT NULL UNIQUE,
  payload JSONB NOT NULL, model TEXT, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS picks (
  id SERIAL PRIMARY KEY, month TEXT NOT NULL UNIQUE,
  cash_amount NUMERIC NOT NULL, picks JSONB NOT NULL, rationale TEXT,
  asi_at_pick NUMERIC, created_at TIMESTAMPTZ DEFAULT now()
);
"""


def ensure_schema() -> None:
    with conn() as c:
        c.execute(SCHEMA)


# --- prices ---

def upsert_prices(rows: list[dict], trade_date: date, source: str = "ngx_scrape") -> int:
    n = 0
    with conn() as c:
        for r in rows:
            c.execute(
                """INSERT INTO prices_eod (symbol, trade_date, close, day_change_pct, week_change_pct, volume, source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (symbol, trade_date) DO UPDATE
                   SET close=EXCLUDED.close, day_change_pct=EXCLUDED.day_change_pct,
                       week_change_pct=EXCLUDED.week_change_pct,
                       volume=EXCLUDED.volume, source=EXCLUDED.source""",
                (r["symbol"], trade_date, r.get("close"), r.get("change_pct"),
                 r.get("week_change_pct"), r.get("volume"), source),
            )
            n += 1
    return n


def price_history(symbol: str, limit: int = 300) -> list[dict]:
    with conn() as c:
        cur = c.execute(
            "SELECT trade_date, close FROM prices_eod WHERE symbol=%s ORDER BY trade_date DESC LIMIT %s",
            (symbol, limit),
        )
        return [{"date": str(r[0]), "close": float(r[1])} for r in cur.fetchall()]


def latest_prices() -> list[dict]:
    """Most recent close per symbol plus its date."""
    with conn() as c:
        cur = c.execute(
            """SELECT DISTINCT ON (symbol) symbol, close, trade_date, day_change_pct, week_change_pct, volume
               FROM prices_eod ORDER BY symbol, trade_date DESC"""
        )
        return [{"symbol": r[0], "close": float(r[1]), "date": str(r[2]),
                 "change_pct": float(r[3]) if r[3] is not None else None,
                 "week_change_pct": float(r[4]) if r[4] is not None else None,
                 "volume": int(r[5]) if r[5] is not None else None}
                for r in cur.fetchall()]


# --- market / ASI ---

def save_market_snapshot(trade_date: date, asi: float | None, source: str = "auto") -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO market_snapshots (trade_date, asi, source) VALUES (%s,%s,%s)
               ON CONFLICT (trade_date) DO UPDATE SET asi=EXCLUDED.asi""",
            (trade_date, asi, source),
        )


def latest_asi() -> dict | None:
    with conn() as c:
        cur = c.execute("SELECT trade_date, asi FROM market_snapshots WHERE asi IS NOT NULL ORDER BY trade_date DESC LIMIT 1")
        r = cur.fetchone()
        return {"date": str(r[0]), "asi": float(r[1])} if r else None


# --- fundamentals ---

def upsert_fundamentals(symbol: str, period: str, fields: dict, source: str = "ngnmarket_free") -> None:
    cols = ("pe pb eps roe profit_margin revenue_growth eps_growth debt_equity dividend_yield fcf_margin").split()
    vals = [fields.get(k) for k in cols]
    with conn() as c:
        c.execute(
            f"""INSERT INTO fundamentals (symbol, period, {', '.join(cols)}, source)
                VALUES (%s,%s,{', '.join(['%s'] * len(cols))},%s)
                ON CONFLICT (symbol, period) DO UPDATE SET
                {', '.join(f'{k}=EXCLUDED.{k}' for k in cols)}, updated_at=now()""",
            (symbol, period, *vals, source),
        )


def latest_fundamentals() -> dict:
    with conn() as c:
        cur = c.execute(
            """SELECT DISTINCT ON (symbol) symbol, period, pe, pb, eps, roe, profit_margin,
               revenue_growth, eps_growth, debt_equity, dividend_yield, fcf_margin
               FROM fundamentals ORDER BY symbol, updated_at DESC"""
        )
        out = {}
        for r in cur.fetchall():
            out[r[0]] = {"period": r[1], "pe": r[2], "pb": r[3], "eps": r[4], "roe": r[5],
                         "profit_margin": r[6], "revenue_growth": r[7], "eps_growth": r[8],
                         "debt_equity": r[9], "dividend_yield": r[10], "fcf_margin": r[11]}
        return out


# --- symbol meta (sector/name from live feed) ---

def upsert_meta(symbol: str, sector: str | None, name: str | None) -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO symbol_meta (symbol, sector, name) VALUES (%s,%s,%s)
               ON CONFLICT (symbol) DO UPDATE SET sector=EXCLUDED.sector,
               name=EXCLUDED.name, updated_at=now()""",
            (symbol, sector, name),
        )


def all_meta() -> dict:
    with conn() as c:
        cur = c.execute("SELECT symbol, sector, name FROM symbol_meta")
        return {r[0]: {"sector": r[1], "name": r[2]} for r in cur.fetchall()}


# --- research / analyses / digests ---

def save_research_note(published, title: str, url: str, summary: str,
                       asi_close: float | None) -> bool:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO research_notes (published, title, url, summary, asi_close)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (url) DO UPDATE SET
               summary=EXCLUDED.summary, published=EXCLUDED.published,
               asi_close=COALESCE(EXCLUDED.asi_close, research_notes.asi_close)
               RETURNING id""",
            (published, title, url, summary, asi_close),
        )
        return cur.fetchone() is not None


def latest_research(limit: int = 3) -> list[dict]:
    with conn() as c:
        cur = c.execute(
            """SELECT published, title, url, summary, asi_close FROM research_notes
               ORDER BY published DESC NULLS LAST LIMIT %s""", (limit,))
        return [{"published": str(r[0]) if r[0] else None, "title": r[1], "url": r[2],
                 "summary": (r[3] or "")[:1500], "asi_close": float(r[4]) if r[4] else None}
                for r in cur.fetchall()]


def save_analysis(month: str, payload: dict, model: str) -> None:
    import json

    with conn() as c:
        c.execute(
            """INSERT INTO analyses (month, payload, model) VALUES (%s,%s,%s)
               ON CONFLICT (month) DO UPDATE SET payload=EXCLUDED.payload,
               model=EXCLUDED.model, created_at=now()""",
            (month, json.dumps(payload), model),
        )


def get_analysis(month: str) -> dict | None:
    with conn() as c:
        cur = c.execute("SELECT payload, model, created_at FROM analyses WHERE month=%s", (month,))
        r = cur.fetchone()
        return {"payload": r[0], "model": r[1], "created_at": str(r[2])} if r else None


def save_digest(week: str, payload: dict, model: str) -> None:
    import json

    with conn() as c:
        c.execute(
            """INSERT INTO digests (week, payload, model) VALUES (%s,%s,%s)
               ON CONFLICT (week) DO UPDATE SET payload=EXCLUDED.payload,
               model=EXCLUDED.model, created_at=now()""",
            (week, json.dumps(payload), model),
        )


def get_latest_digest() -> dict | None:
    with conn() as c:
        cur = c.execute("SELECT week, payload, model FROM digests ORDER BY week DESC LIMIT 1")
        r = cur.fetchone()
        return {"week": r[0], "payload": r[1], "model": r[2]} if r else None


def asi_series(limit: int = 60) -> list[dict]:
    with conn() as c:
        cur = c.execute(
            "SELECT trade_date, asi FROM market_snapshots WHERE asi IS NOT NULL "
            "ORDER BY trade_date DESC LIMIT %s", (limit,))
        return [{"date": str(r[0]), "asi": float(r[1])} for r in cur.fetchall()]


# --- cash / picks / holdings / signals ---

def record_cash(month: str, amount: float) -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO cash_inputs (month, amount) VALUES (%s,%s)
               ON CONFLICT (month) DO UPDATE SET amount=EXCLUDED.amount""",
            (month, amount),
        )


def save_pick(month: str, cash: float, picks: list[dict], rationale: str, asi: float | None) -> None:
    import json

    with conn() as c:
        c.execute(
            """INSERT INTO picks (month, cash_amount, picks, rationale, asi_at_pick)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (month) DO UPDATE SET cash_amount=EXCLUDED.cash_amount,
               picks=EXCLUDED.picks, rationale=EXCLUDED.rationale, asi_at_pick=EXCLUDED.asi_at_pick""",
            (month, cash, json.dumps(picks), rationale, asi),
        )


def list_picks() -> list[dict]:
    with conn() as c:
        cur = c.execute(
            "SELECT month, cash_amount, picks, rationale, asi_at_pick, created_at FROM picks ORDER BY month DESC")
        return [{"month": r[0], "cash": float(r[1]), "picks": r[2], "rationale": r[3],
                 "asi_at_pick": float(r[4]) if r[4] is not None else None,
                 "created_at": str(r[5])} for r in cur.fetchall()]


def save_holdings_snapshot(snap: dict) -> None:
    import json
    from datetime import datetime as _dt

    def _d(s):
        return _dt.strptime(s, "%Y-%m-%d").date() if s else None

    with conn() as c:
        c.execute(
            """INSERT INTO holdings_snapshots
               (statement_from, statement_to, account_no, total_value, cash_balance, holdings)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (_d(snap.get("statement_from")), _d(snap.get("statement_to")),
             snap.get("account_no"), snap.get("total_value"), snap.get("cash_balance"),
             json.dumps(snap.get("holdings", []))),
        )


def latest_holdings() -> dict | None:
    with conn() as c:
        cur = c.execute(
            """SELECT statement_from, statement_to, account_no, total_value, cash_balance, holdings
               FROM holdings_snapshots ORDER BY id DESC LIMIT 1""")
        r = cur.fetchone()
        if not r:
            return None
        return {"statement_from": str(r[0]) if r[0] else None,
                "statement_to": str(r[1]) if r[1] else None, "account_no": r[2],
                "total_value": float(r[3]) if r[3] is not None else 0,
                "cash_balance": float(r[4]) if r[4] is not None else 0,
                "holdings": r[5]}


def add_signal(s: dict) -> bool:
    """Insert unless duplicate. Returns True if new."""
    with conn() as c:
        cur = c.execute(
            """INSERT INTO signals (symbol, event_type, title, url, source, source_tier, published, confidence)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT DO NOTHING RETURNING id""",
            (s["symbol"], s.get("event_type", "OTHER"), s["title"], s.get("url"),
             s.get("source"), int(s.get("source_tier", 3)), s.get("published"),
             s.get("confidence", "medium")),
        )
        return cur.fetchone() is not None


def signals_for(symbol: str, since_days: int = 120) -> list[dict]:
    with conn() as c:
        cur = c.execute(
            """SELECT event_type, title, url, source, source_tier, published, confidence
               FROM signals WHERE symbol=%s AND (published IS NULL OR published > CURRENT_DATE - %s)
               ORDER BY published DESC NULLS LAST LIMIT 20""",
            (symbol, since_days),
        )
        return [{"event_type": r[0], "title": r[1], "url": r[2], "source": r[3],
                 "source_tier": r[4], "published": str(r[5]) if r[5] else None,
                 "confidence": r[6]} for r in cur.fetchall()]
