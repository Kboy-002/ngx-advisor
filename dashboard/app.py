"""NGX Advisor dashboard — monthly pick + Saturday portfolio check.

Pages (tabs): This Month | Portfolio | History (stub).
Run: streamlit run app.py  (or via docker compose, http://localhost:8501)
"""
from __future__ import annotations

import os

import httpx
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="NGX Advisor", layout="wide")
st.title("NGX Advisor — monthly growth picks (NGX)")

tab_pick, tab_port, tab_hist = st.tabs(["This month's pick", "Portfolio (Saturday check)", "History (pick vs ASI)"])

with tab_pick:
    st.subheader("1. How much do you have this month?")
    cash = st.number_input("Cash available (₦)", min_value=0.0, value=100000.0, step=5000.0,
                           help="Type this month's investable cash — nothing is fixed. Allocation maths reruns on this number.")
    st.caption("Single-stock default: the engine goes 100% into the best idea unless a split is earned (close scores + diversification, concentration cap, or idle-cash lots).")

    st.subheader("2. Candidate snapshot (MVP: paste or fetch)")
    if st.button("Fetch live NGX price list (free scrape)"):
        try:
            r = httpx.get(f"{API}/ingest/status", timeout=60.0)
            r.raise_for_status()
            data = r.json()
            st.success(f"Fetched {data['symbols']} symbols")
            st.json(data["sample"])
        except Exception as exc:
            st.error(f"Fetch failed (scrape is best-effort): {exc}")

    st.subheader("3. Rank + allocate (demo with your numbers)")
    st.caption("MVP demo: paste up to 5 candidates with price + factor inputs; full auto-feed wires to Postgres in Phase 2.")
    demo = [
        {"symbol": "GTCO", "price": 132.8,
         "momentum": {"ret_3m": 18, "vs_asi_3m": 9, "pos_52w": 0.8},
         "quality": {"rev_growth": 25, "roe": 28, "debt_equity": 0.4},
         "value": {"pe": 4.1, "sector_pe": 6.8}, "risk": {"beta": 0.8, "drawdown": -12, "daily_value": 800_000_000},
         "dividend": {}},
        {"symbol": "PRESCO", "price": 2070.0,
         "momentum": {"ret_3m": 30, "vs_asi_3m": 20, "pos_52w": 0.9},
         "quality": {"rev_growth": 35, "roe": 37, "debt_equity": 0.3},
         "value": {"pe": 19.6, "sector_pe": 15.0}, "risk": {"beta": 0.5, "drawdown": -15, "daily_value": 300_000_000},
         "dividend": {}},
    ]
    if st.button("Rank demo + allocate"):
        try:
            rr = httpx.post(f"{API}/rank", json={"candidates": demo}, timeout=30.0)
            rr.raise_for_status()
            ranked = rr.json()["ranked"]
            ar = httpx.post(f"{API}/allocate", json={"cash": cash, "ranked": ranked}, timeout=30.0)
            ar.raise_for_status()
            allocs = ar.json()["allocations"]
            st.write("### Recommended buy")
            for a in allocs:
                st.write(f"**{a['symbol']}** — {a['units']} units @ ₦{a['est_price']:,.2f} "
                         f"= ₦{a['allocation_ngn']:,.2f} (fees ~₦{a['est_fees']:,.2f}). {a.get('note','')}")
                with st.expander(f"Evidence — {a['symbol']} (score {a['score']})"):
                    st.json(a.get("evidence", {}))
        except Exception as exc:
            st.error(f"Rank/allocate failed — is the API up at {API}? {exc}")

    st.subheader("4. Generate & save this month's pick (uses stored DB feed)")
    st.caption("Runs the full pipeline: DB prices → momentum from history → fundamentals → signals → rank → allocate → save. Needs a few daily EOD runs first.")
    if st.button("Generate this month's pick"):
        try:
            r = httpx.post(f"{API}/picks/generate", json={"cash": cash}, timeout=120.0)
            r.raise_for_status()
            res = r.json()
            if "error" in res:
                st.warning(res["error"])
            else:
                st.success(f"Saved pick for {res['month']} (universe: {res['universe']} symbols)")
                st.write(res.get("rationale", ""))
                for a in res["picks"]:
                    st.write(f"**{a['symbol']}** — {a['units']} units @ ₦{a['est_price']:,.2f} "
                             f"= ₦{a['allocation_ngn']:,.2f} (score {a['score']}). {a.get('note','')}")
                    with st.expander(f"Evidence — {a['symbol']}"):
                        st.json(a.get("evidence", {}))
        except Exception as exc:
            st.error(f"Generate failed — is the API + DB up? {exc}")

with tab_hist:
    st.subheader("Past picks vs the market (ASI)")
    try:
        r = httpx.get(f"{API}/picks", timeout=30.0)
        data = r.json().get("picks", [])
        if not data:
            st.info("No stored picks yet — generate one from the first tab.")
        for p in data:
            with st.expander(f"{p['month']} — ₦{p['cash']:,.0f} (ASI at pick: {p.get('asi_at_pick') or 'n/a'})"):
                st.write(p.get("rationale", ""))
                for leg in p["picks"]:
                    st.write(f"**{leg['symbol']}** — {leg['units']} units @ ₦{leg['est_price']:,.2f} (score {leg['score']})")
                try:
                    pr = httpx.get(f"{API}/picks/{p['month']}/performance", timeout=30.0).json()
                    if "asi_return_pct" in pr:
                        st.write(f"ASI since pick: {pr['asi_return_pct']:+.2f}%")
                    for leg in pr.get("legs", []):
                        if "return_pct" in leg:
                            st.write(f"{leg['symbol']}: {leg['return_pct']:+.2f}% (now ₦{leg['now_price']:,.2f})")
                        else:
                            st.write(f"{leg['symbol']}: awaiting fresh prices")
                except Exception:
                    st.caption("Performance unavailable (DB/prices still warming).")
    except Exception as exc:
        st.error(f"Could not load picks — is the API up at {API}? {exc}")

with tab_port:
    st.subheader("Saturday check — upload your Afrinvest Valuation Statement (PDF)")
    up = st.file_uploader("Drop this week's PDF", type=["pdf"])
    if up is not None:
        try:
            files = {"file": (up.name, up.getvalue(), "application/pdf")}
            r = httpx.post(f"{API}/portfolio/parse", files=files, timeout=60.0)
            r.raise_for_status()
            snap = r.json()
            st.success(f"Parsed {len(snap['holdings'])} holdings — account {snap.get('account_no','?')} "
                       f"{snap.get('statement_from','?')} → {snap.get('statement_to','?')}")
            st.write(f"Cash: ₦{snap.get('cash_balance', 0):,.2f} | Total: ₦{snap.get('total_value', 0):,.2f}")
            st.dataframe(snap["holdings"])
            st.write("### Verdicts")
            for v in snap.get("verdicts", []):
                st.write(f"**{v['symbol']}** — {v['verdict']}: {v['reason']}")
        except Exception as exc:
            st.error(f"Parse failed: {exc}")
