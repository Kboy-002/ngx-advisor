"""Shared config — env-driven, free-first defaults."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "")
NGNMARKET_API_KEY = os.getenv("NGNMARKET_API_KEY", "")
NGNMARKET_BASE = "https://api.ngnmarket.com/v1"
NGX_PRICE_LIST_URL = os.getenv(
    "NGX_PRICE_LIST_URL", "https://ngxgroup.com/exchange/data/equities-price-list/"
)

# Growth-first weights (locked in planning): momentum 30 / quality 25 /
# value 20 / risk-liquidity 20 / dividend 5.
WEIGHTS = {
    "momentum": 0.30,
    "quality": 0.25,
    "value": 0.20,
    "risk_liquidity": 0.20,
    "dividend": 0.05,
}

# Tags seen on the NGX price list marking suspended/restricted names.
SUSPENDED_TAGS = ("[MRF]", "[RST]", "[DWL]", "[BMF]", "[BLS]", "[DIP]", "[MRS]")

# Concentration guardrails (fraction of total portfolio incl. new buy).
MAX_SINGLE_TICKER_PCT = 0.35
MAX_SECTOR_PCT = 0.45

# Rough NGX buy-side cost used for unit math: brokerage ~1.0% + SEC 0.3% + stamp 0.08%.
EST_BUY_FEE_RATE = 0.014

# Minimal sector map for guardrails (extend as needed).
SECTORS = {
    "MTNN": "telecom", "AIRTELAFRI": "telecom", "CHAMS": "tech", "CWG": "tech",
    "ETRANZACT": "tech",
    "FIRSTHOLDCO": "banking", "ZENITHBANK": "banking", "GTCO": "banking",
    "FCMB": "banking", "UBA": "banking", "ACCESSCORP": "banking",
    "STERLINGNG": "banking", "JAIZBANK": "banking", "WEMABANK": "banking",
    "STANBIC": "banking", "FIDELITYBK": "banking", "ETI": "banking",
    "ARADEL": "oil_gas", "SEPLAT": "oil_gas", "OANDO": "oil_gas",
    "CONOIL": "oil_gas", "ETERNA": "oil_gas", "TOTAL": "oil_gas",
    "BUAFOODS": "consumer", "BUACEMENT": "industrial", "DANGCEM": "industrial",
    "NESTLE": "consumer", "GUINNESS": "consumer", "NB": "consumer",
    "INTBREW": "consumer", "CADBURY": "consumer", "UNILEVER": "consumer",
    "PZ": "consumer", "NASCON": "consumer", "DANGSUGAR": "consumer",
    "TRANSCORP": "conglomerate", "UACN": "conglomerate", "TRANSPOWER": "power",
    "GEREGU": "power", "TRANSCOHOT": "hospitality",
    "OKOMUOIL": "agri", "PRESCO": "agri", "ELLHALAKES": "agri",
    "ELLAHLAKES": "agri", "LIVESTOCK": "agri",
    "JBERGER": "industrial", "BERGER": "industrial",
    "INTENEGINS": "insurance", "AIICO": "insurance", "MANSARD": "insurance",
    "NEM": "insurance", "CUSTODIAN": "insurance",
}
