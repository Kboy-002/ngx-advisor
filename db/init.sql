-- NGX Advisor schema (Postgres 16). Idempotent: safe to re-run on fresh volumes.
CREATE TABLE IF NOT EXISTS prices_eod (
  symbol TEXT NOT NULL,
  trade_date DATE NOT NULL,
  close NUMERIC, open NUMERIC, high NUMERIC, low NUMERIC,
  volume BIGINT, value NUMERIC, day_change_pct NUMERIC, week_change_pct NUMERIC,
  source TEXT DEFAULT 'ngx_scrape',
  PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS fundamentals (
  symbol TEXT NOT NULL,
  period TEXT NOT NULL,            -- e.g. 'FY2024', 'Q3-2025'
  pe NUMERIC, pb NUMERIC, eps NUMERIC,
  roe NUMERIC, profit_margin NUMERIC, revenue_growth NUMERIC, eps_growth NUMERIC,
  debt_equity NUMERIC, dividend_yield NUMERIC, fcf_margin NUMERIC,
  source TEXT DEFAULT 'ngnmarket_free',
  updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (symbol, period)
);

CREATE TABLE IF NOT EXISTS holdings_snapshots (
  id SERIAL PRIMARY KEY,
  uploaded_at TIMESTAMPTZ DEFAULT now(),
  statement_from DATE, statement_to DATE,
  account_no TEXT,
  total_value NUMERIC, cash_balance NUMERIC,
  holdings JSONB NOT NULL           -- [{symbol, quantity, avg_cost, price, value, acct_pct, gain_pct}]
);

CREATE TABLE IF NOT EXISTS cash_inputs (
  id SERIAL PRIMARY KEY,
  month TEXT NOT NULL UNIQUE,       -- 'YYYY-MM'
  amount NUMERIC NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
  id SERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  event_type TEXT NOT NULL,         -- M&A_DEAL, INSIDER_BUYING, EARNINGS_BEAT, ...
  title TEXT NOT NULL,
  url TEXT, source TEXT, source_tier INT DEFAULT 3,  -- 1=NGX filing, 2=company IR, 3=press
  published DATE,
  confidence TEXT DEFAULT 'medium', -- low|medium|high
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);

CREATE TABLE IF NOT EXISTS market_snapshots (
  trade_date DATE PRIMARY KEY,
  asi NUMERIC,
  volume BIGINT,
  value NUMERIC,
  deals BIGINT,
  source TEXT DEFAULT 'auto'
);
CREATE TABLE IF NOT EXISTS symbol_meta (
  symbol TEXT PRIMARY KEY,
  sector TEXT,
  name TEXT,
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS research_notes (
  id SERIAL PRIMARY KEY,
  published DATE,
  title TEXT NOT NULL,
  url TEXT UNIQUE,
  summary TEXT,
  asi_close NUMERIC,
  source TEXT DEFAULT 'afrinvest_substack',
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analyses (
  id SERIAL PRIMARY KEY,
  month TEXT NOT NULL UNIQUE,
  payload JSONB NOT NULL,
  model TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS digests (
  id SERIAL PRIMARY KEY,
  week TEXT NOT NULL UNIQUE,
  payload JSONB NOT NULL,
  model TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS picks (
  id SERIAL PRIMARY KEY,
  month TEXT NOT NULL UNIQUE,       -- 'YYYY-MM'
  cash_amount NUMERIC NOT NULL,
  picks JSONB NOT NULL,             -- [{symbol, allocation_ngn, units, est_price, est_fees, score, evidence[], risks[]}]
  rationale TEXT,
  asi_at_pick NUMERIC,
  created_at TIMESTAMPTZ DEFAULT now()
);
