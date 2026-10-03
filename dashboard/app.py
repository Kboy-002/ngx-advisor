"""NGX Advisor — Lagos Terminal. Sidebar-driven: Home | This Month | Saturday Check | History."""
from __future__ import annotations

from datetime import date

import streamlit as st

import views_history
import views_home
import views_pick
import views_portfolio
from components import API, api_get, load_css, naira0

st.set_page_config(page_title="NGX Advisor", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")
load_css()

# --- sidebar ---
st.sidebar.markdown("## 📈 NGX Advisor")
st.sidebar.caption("Your monthly growth engine")

cash = st.sidebar.number_input("This month's cash (₦)", min_value=0.0, value=100000.0,
                               step=5000.0, key="cash",
                               help="What you actually have to invest right now — every calculation follows this number.")
st.sidebar.markdown('<div class="cash-note">Nothing is fixed. Change it any month.</div>',
                    unsafe_allow_html=True)

status, err = api_get("/status", timeout=15.0)
if err or not status or status.get("error"):
    st.sidebar.markdown('<span class="status-bad">● Engine offline</span>', unsafe_allow_html=True)
    st.sidebar.caption("Start Docker, then refresh.")
else:
    asi = status.get("asi")
    stale = True
    if asi and asi.get("date"):
        try:
            stale = (date.today() - date.fromisoformat(asi["date"])).days > 4
        except ValueError:
            pass
    if stale:
        st.sidebar.markdown('<span class="status-warn">● Feed warming</span>', unsafe_allow_html=True)
        st.sidebar.caption("Market data still collecting — picks are provisional.")
    else:
        st.sidebar.markdown('<span class="status-ok">● Feed live</span>', unsafe_allow_html=True)
        st.sidebar.caption(f"ASI {asi['asi']:,.0f} · {asi['date']} · {status.get('symbols', '?')} stocks tracked.")

page = st.sidebar.radio("Go to", ["Home", "This Month", "Saturday Check", "History"],
                        captions=["Wealth overview", "What to buy now", "Weekly PDF review", "You vs the market"])
st.sidebar.caption(f"Talking to {API}")

# --- pages ---
if page == "Home":
    views_home.render()
elif page == "This Month":
    views_pick.render(cash)
elif page == "Saturday Check":
    views_portfolio.render()
else:
    views_history.render()
