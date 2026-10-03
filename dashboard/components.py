"""Shared UI helpers: formatting, API access, small HTML components."""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")


def load_css() -> None:
    css = Path(__file__).parent / "style.css"
    if css.exists():
        st.markdown(f"<style>{css.read_text()}</style>", unsafe_allow_html=True)


def naira(v) -> str:
    if v is None:
        return "—"
    try:
        return f"₦{float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def naira0(v) -> str:
    if v is None:
        return "—"
    try:
        return f"₦{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def signed_pct(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):+.1f}%"
    except (TypeError, ValueError):
        return "—"


def move_class(v) -> str:
    try:
        return "up" if float(v) >= 0 else "down"
    except (TypeError, ValueError):
        return ""


def api_get(path: str, timeout: float = 30.0):
    try:
        r = httpx.get(f"{API}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:
        return None, str(exc)


def api_post(path: str, json=None, files=None, timeout: float = 90.0):
    try:
        r = httpx.post(f"{API}{path}", json=json, files=files, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:
        return None, str(exc)


TIER_LABEL = {1: ("tier1", "NGX filing"), 2: ("tier2", "Company IR"), 3: ("tier3", "Press")}


def tier_badge(tier: int) -> str:
    cls, label = TIER_LABEL.get(int(tier or 3), TIER_LABEL[3])
    return f'<span class="badge {cls}">{label}</span>'


def score_bars(scores: dict) -> None:
    order = [("momentum", "Momentum"), ("quality", "Quality"),
             ("value", "Value"), ("risk_liquidity", "Risk"), ("dividend", "Dividend")]
    rows = []
    for key, label in order:
        v = float(scores.get(key, 50) or 50)
        rows.append(
            f'<div class="score-row"><span class="name">{label}</span>'
            f'<span class="track"><span class="fill" style="display:block;width:{v:.0f}%"></span></span>'
            f'<span class="num">{v:.0f}</span></div>'
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


def verdict_class(verdict: str) -> str:
    v = (verdict or "").upper()
    if "TRIM" in v or "SELL" in v:
        return "TRIM"
    if "PAUSE" in v or "TIDY" in v:
        return "PAUSE"
    if "WATCH" in v:
        return "WATCH"
    return "HOLD"


def empty_state(title: str, body: str) -> None:
    st.markdown(f'<div class="empty"><h4>{title}</h4><p>{body}</p></div>',
                unsafe_allow_html=True)
