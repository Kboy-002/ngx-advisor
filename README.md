# NGX Advisor — personal Nigerian stock monitor & monthly buy guide

A home-PC Docker system that watches the **Nigerian Exchange (NGX)** and, every month around the
**27th–28th**, recommends **1 stock (default) or at most 2** for that month's cash — with a
traceable evidence trail for every pick. A **Saturday check** reviews your Afrinvest portfolio
from the weekly Valuation Statement PDF.

> Decision support, not financial advice. Past momentum ≠ future returns. Small-caps can be illiquid.

## How it works

```
Daily 16:30 WAT: scrape NGX price list (+ NGN Market free tier if key set)
Saturday 08:00: nudge → you upload Afrinvest PDF → HOLD / PAUSE / TRIM verdicts
27th 08:00:    monthly pick — you type that month's cash (₦100k, ₦150k…) → units + fees + evidence
```

**Growth-first scoring** (age 21, building): Momentum 30 / Quality-growth 25 / Value 20 /
Risk-Liquidity 20 / Dividend 5 (tie-break only). News events (M&A, insider buying like the
Seplat–ExxonMobil or Otedola–FirstBank type signals) attach as a **±10 pt overlay with source
URL + tier** — Tier 1 NGX filing, Tier 2 company IR, Tier 3 press. Machine links with receipts,
you judge.

**Allocator:** 100% into the best idea unless a split is earned (scores within ~10 pts *and*
diversifies sector, or single-ticker >35% / sector >45% guardrail, or one name's lots leave
>25% cash idle). Converts ₦ → whole units after ~1.4% est. buy fees.

## Quickstart (Windows, Docker Desktop)

```powershell
cd C:\Users\ofolayan\Documents\projects\ngx-advisor
Copy-Item .env.example .env
# edit .env -> set POSTGRES_PASSWORD (and optional NGNMARKET_API_KEY from ngnmarket.com/developer)
docker compose up -d --build
```

- Dashboard: http://localhost:8501
- API docs: http://localhost:8000/docs
- If the PC was off on the 27th/Saturday, jobs catch up on next boot — open the dashboard.

## Using it

1. **This month's pick:** open dashboard → type cash → Rank + allocate. Shows units, est. price,
   est. fees, remainder, and evidence bullets per factor + linked signals.
2. **Saturday check:** dashboard → Portfolio tab → drop the Afrinvest Valuation Statement PDF.
   Verifies the parsed table (Symbol, Quantity, Avg Cost, Price, Value, Acct %) before saving.
3. **History:** picks + cash inputs persist in Postgres (`picks`, `cash_inputs`, `holdings_snapshots`).

## API (for hackers)

| Method | Endpoint | What |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/ingest/status` | live NGX scrape probe |
| POST | `/portfolio/parse` | upload Afrinvest PDF → holdings + verdicts |
| POST | `/ingest/run` | run daily EOD now (prices + ASI + fundamentals slice) |
| POST | `/signals/collect` | run disclosure + RSS collector now |
| POST | `/picks/generate` | full pipeline: rank universe, allocate cash, persist pick |
| GET | `/picks` | stored monthly picks |
| GET | `/picks/{YYYY-MM}/performance` | pick legs vs ASI since purchase |
| POST | `/rank` | score candidates (growth weights + signal overlay) |
| POST | `/allocate` | cash → 1-or-2 buy plan |

## Project layout

```
docker-compose.yml   # db + app + scheduler + dashboard
app/                 # FastAPI: scoring, allocator, parser_afrinvest, ingest, signals, scheduler
dashboard/           # Streamlit: amount box, PDF upload, pick card
db/init.sql          # Postgres schema
```

## Data sources (free-first)

- Kobo Terminal Personal key (free, 100 req/day): all 150+ NGX prices + ASI + sectors — the live path
- NGX official weekly P/E PDFs (free, open doclib): P/E + market caps, sanity-gated
- topchor.com per-stock pages (free): EPS, dividend yield, ROE, RSI → our P/E is computed as live price ÷ EPS
- CardinalStone research PDFs (free portal): ROE, P/B, debt/equity, target prices, ratings ("street view")
- Afrinvest Research Substack (free): weekly outlook + ASI archive backfill
- Nairametrics / BusinessDay / Punch RSS: tagged signals + earnings extraction
- NGX website scrape: deprecated fallback (bot-walled since day one; kept in code, not relied upon)

## Roadmap

- [x] Phase 1 (this repo): Docker stack, growth scoring, allocator, Afrinvest parser, dashboard
- [x] Phase 2: Postgres-backed auto-feed, signal collector cron, performance tracking (pick vs ASI)
- [ ] Phase 3: paid API switch, email/WhatsApp nudge, backtests

## Disclaimer

Educational tooling for one investor's monthly discipline. Not a recommendation to buy/sell any
security. Verify prices with your broker before placing orders.
