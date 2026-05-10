"""
data/smart_money.py — Curated seed list of well-known institutional fund managers.

This is a SEED FILE. CIKs were sourced from public SEC EDGAR filings and
should be re-verified periodically (funds restructure, merge, shut down,
and occasionally rename their filing entities).

Why a seed file at all: 13F-based new-initiation screening only works if
we know whose 13Fs to read. Crawling all 5,000+ 13F filers per quarter is
infeasible on a free SEC API tier, and most of them are uninformative
(passive indexers, market makers, prop desks). This list focuses on
funds that publish concentrated, conviction-driven books — the ones whose
new positions are alpha signal rather than rebalancing noise.

Verification path: SEC EDGAR's full-text search at
https://efts.sec.gov/LATEST/search-index?q=%22<fund_name>%22&forms=13F-HR
returns the canonical CIK for any fund name. The `verify_funds()` helper
below can be wired into a periodic job to confirm each entry still files.

Editing this file:
  - Keep the entries sorted by `fund_name` for easy diffing.
  - Set `verified: True` only after manually confirming via EDGAR.
  - When a fund shuts down, set `active: False` rather than deleting so
    historical 13F lookups still work.
"""

from __future__ import annotations

from typing import TypedDict


class SmartMoneyFund(TypedDict):
    """One curated institutional fund entry for 13F new-initiation screening."""
    cik: str
    fund_name: str
    manager: str
    style: str
    active: bool
    verified: bool


# Seed list. CIKs are zero-padded 10-digit strings — matches SEC EDGAR's
# canonical format. The `style` tag is descriptive only — funds drift.
SMART_MONEY_FUNDS: list[SmartMoneyFund] = [
    {"cik": "0001112520", "fund_name": "Akre Capital Management",            "manager": "Chuck Akre",      "style": "quality_compounders",   "active": True, "verified": False},
    {"cik": "0001061165", "fund_name": "Baupost Group",                       "manager": "Seth Klarman",    "style": "deep_value",            "active": True, "verified": False},
    {"cik": "0001067983", "fund_name": "Berkshire Hathaway",                  "manager": "Warren Buffett",  "style": "concentrated_value",    "active": True, "verified": True},
    {"cik": "0001350694", "fund_name": "Bridgewater Associates",              "manager": "Ray Dalio",       "style": "macro_systematic",      "active": True, "verified": False},
    {"cik": "0001423053", "fund_name": "Citadel Advisors",                    "manager": "Ken Griffin",     "style": "multistrat",            "active": True, "verified": False},
    {"cik": "0001135730", "fund_name": "Coatue Management",                   "manager": "Philippe Laffont","style": "tech_growth",           "active": True, "verified": False},
    {"cik": "0001029160", "fund_name": "Duquesne Family Office",              "manager": "Stanley Druckenmiller","style": "macro_eclectic",   "active": True, "verified": False},
    {"cik": "0001079114", "fund_name": "Greenlight Capital",                  "manager": "David Einhorn",   "style": "long_short_value",      "active": True, "verified": False},
    {"cik": "0001138138", "fund_name": "Glenview Capital Management",         "manager": "Larry Robbins",   "style": "long_short_fundamental","active": True, "verified": False},
    {"cik": "0001061768", "fund_name": "Lone Pine Capital",                   "manager": "Stephen Mandel",  "style": "long_short_growth",     "active": True, "verified": False},
    {"cik": "0001101418", "fund_name": "Maverick Capital",                    "manager": "Lee Ainslie",     "style": "long_short_growth",     "active": True, "verified": False},
    {"cik": "0001370838", "fund_name": "Pabrai Investment Funds",             "manager": "Mohnish Pabrai",  "style": "concentrated_value",    "active": True, "verified": False},
    {"cik": "0001336528", "fund_name": "Pershing Square Capital",             "manager": "Bill Ackman",     "style": "activist_concentrated", "active": True, "verified": True},
    {"cik": "0001037389", "fund_name": "Renaissance Technologies",            "manager": "Jim Simons (founder)","style": "systematic_quant",  "active": True, "verified": False},
    {"cik": "0001040273", "fund_name": "Third Point",                         "manager": "Daniel Loeb",     "style": "event_driven_activist", "active": True, "verified": False},
    {"cik": "0001167483", "fund_name": "Tiger Global Management",             "manager": "Chase Coleman",   "style": "tech_growth",           "active": True, "verified": False},
    {"cik": "0001179392", "fund_name": "Two Sigma Investments",               "manager": "Siegel / Overdeck","style": "systematic_quant",     "active": True, "verified": False},
    {"cik": "0001418814", "fund_name": "ValueAct Capital",                    "manager": "Mason Morfit",    "style": "activist_value",        "active": True, "verified": False},
    {"cik": "0001103804", "fund_name": "Viking Global Investors",             "manager": "Andreas Halvorsen","style": "long_short_fundamental","active": True, "verified": False},
    {"cik": "0001029160", "fund_name": "Soros Fund Management",               "manager": "Robert Soros",    "style": "macro_discretionary",   "active": True, "verified": False},
]


def get_active_funds() -> list[SmartMoneyFund]:
    """Return only currently-active funds."""
    return [f for f in SMART_MONEY_FUNDS if f.get("active", True)]


def get_verified_funds() -> list[SmartMoneyFund]:
    """Return only manually-verified entries — use when CIK correctness matters."""
    return [f for f in SMART_MONEY_FUNDS if f.get("verified", False)]


def get_fund_by_cik(cik: str) -> SmartMoneyFund | None:
    """Lookup helper. Accepts CIK with or without zero-padding."""
    normalized = str(cik).strip().lstrip("0").zfill(10)
    for f in SMART_MONEY_FUNDS:
        if f["cik"] == normalized:
            return f
    return None


def get_funds_by_style(style: str) -> list[SmartMoneyFund]:
    """Filter by style tag (e.g., 'long_short_growth', 'activist_value')."""
    s = style.strip().lower()
    return [f for f in SMART_MONEY_FUNDS if f["style"].lower() == s]
