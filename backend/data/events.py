"""
data/events.py — Curated economic event calendar for macro & rates PMs.

This is a SEED file. Event dates are sourced from official central bank
and government statistical agency schedules. ALL DATES MUST BE RE-VERIFIED
ANNUALLY against the canonical sources:

    FOMC meetings:    federalreserve.gov/monetarypolicy/fomccalendars.htm
    CPI releases:     bls.gov/schedule/news_release/cpi.htm
    NFP releases:     bls.gov/schedule/news_release/empsit.htm
    ECB meetings:     ecb.europa.eu/press/calendars/mgcgc/html/
    OPEC meetings:    opec.org/opec_web/en/press_room/9.htm

Why a seed file at all: macro events trigger sharp position-level P&L
shifts that don't show up in standard volatility models. A PM running a
long-duration trade book wants to know "is there an FOMC in my time
horizon?" before sizing. Scraping live calendars is brittle; a curated
seed refreshed annually is reliable and auditable.

To extend / update:
  - Add entries to ECONOMIC_EVENTS sorted by date ascending.
  - Set `tier` based on typical market impact (1 = high, 2 = medium, 3 = low).
  - When an event passes, do not delete — keep for historical queries.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TypedDict

logger = logging.getLogger(__name__)


class EconomicEvent(TypedDict):
    date: str                      # YYYY-MM-DD, the event/release date
    time_et: str                   # HH:MM ET (24h), or "" for date-only events
    event_type: str                # FOMC | CPI | NFP | OPEC | ECB | PCE | RetailSales | GDP | JOLTS
    description: str               # Short PM-facing label
    market_impact_tier: int        # 1 (high), 2 (medium), 3 (low) — typical realized vol on day
    region: str                    # US | EU | OPEC | UK | JP | CN
    source: str                    # canonical URL


# ─── 2026 Calendar ───────────────────────────────────────────────────────
# Verified to be re-checked: 2026 dates may shift; the structure is what
# matters here. Update annually from the canonical sources listed above.

ECONOMIC_EVENTS: list[EconomicEvent] = [
    # --- January 2026 ---
    {"date": "2026-01-09", "time_et": "08:30", "event_type": "NFP",
     "description": "December nonfarm payrolls report",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-01-13", "time_et": "08:30", "event_type": "CPI",
     "description": "December CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},
    {"date": "2026-01-28", "time_et": "14:00", "event_type": "FOMC",
     "description": "FOMC rate decision + SEP + press conference",
     "market_impact_tier": 1, "region": "US",
     "source": "federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"date": "2026-01-30", "time_et": "08:30", "event_type": "PCE",
     "description": "December core PCE (Fed's preferred inflation gauge)",
     "market_impact_tier": 1, "region": "US",
     "source": "bea.gov/news/schedule"},

    # --- February 2026 ---
    {"date": "2026-02-06", "time_et": "08:30", "event_type": "NFP",
     "description": "January nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-02-11", "time_et": "08:30", "event_type": "CPI",
     "description": "January CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},

    # --- March 2026 ---
    {"date": "2026-03-06", "time_et": "08:30", "event_type": "NFP",
     "description": "February nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-03-11", "time_et": "08:30", "event_type": "CPI",
     "description": "February CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},
    {"date": "2026-03-12", "time_et": "07:45", "event_type": "ECB",
     "description": "ECB Governing Council monetary policy decision",
     "market_impact_tier": 2, "region": "EU",
     "source": "ecb.europa.eu/press/calendars/mgcgc/html/"},
    {"date": "2026-03-18", "time_et": "14:00", "event_type": "FOMC",
     "description": "FOMC rate decision + SEP + press conference",
     "market_impact_tier": 1, "region": "US",
     "source": "federalreserve.gov/monetarypolicy/fomccalendars.htm"},

    # --- April 2026 ---
    {"date": "2026-04-03", "time_et": "08:30", "event_type": "NFP",
     "description": "March nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-04-10", "time_et": "08:30", "event_type": "CPI",
     "description": "March CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},
    {"date": "2026-04-16", "time_et": "07:45", "event_type": "ECB",
     "description": "ECB Governing Council monetary policy decision",
     "market_impact_tier": 2, "region": "EU",
     "source": "ecb.europa.eu/press/calendars/mgcgc/html/"},
    {"date": "2026-04-29", "time_et": "14:00", "event_type": "FOMC",
     "description": "FOMC rate decision + press conference",
     "market_impact_tier": 1, "region": "US",
     "source": "federalreserve.gov/monetarypolicy/fomccalendars.htm"},

    # --- May 2026 ---
    {"date": "2026-05-01", "time_et": "08:30", "event_type": "NFP",
     "description": "April nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-05-13", "time_et": "08:30", "event_type": "CPI",
     "description": "April CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},

    # --- June 2026 ---
    {"date": "2026-06-04", "time_et": "07:45", "event_type": "ECB",
     "description": "ECB Governing Council monetary policy decision",
     "market_impact_tier": 2, "region": "EU",
     "source": "ecb.europa.eu/press/calendars/mgcgc/html/"},
    {"date": "2026-06-05", "time_et": "08:30", "event_type": "NFP",
     "description": "May nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-06-10", "time_et": "08:30", "event_type": "CPI",
     "description": "May CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},
    {"date": "2026-06-17", "time_et": "14:00", "event_type": "FOMC",
     "description": "FOMC rate decision + SEP + press conference",
     "market_impact_tier": 1, "region": "US",
     "source": "federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"date": "2026-06-26", "time_et": "00:00", "event_type": "OPEC",
     "description": "OPEC Ordinary Ministerial Meeting (production policy)",
     "market_impact_tier": 1, "region": "OPEC",
     "source": "opec.org/opec_web/en/press_room/9.htm"},

    # --- July 2026 ---
    {"date": "2026-07-02", "time_et": "08:30", "event_type": "NFP",
     "description": "June nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-07-15", "time_et": "08:30", "event_type": "CPI",
     "description": "June CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},
    {"date": "2026-07-23", "time_et": "07:45", "event_type": "ECB",
     "description": "ECB Governing Council monetary policy decision",
     "market_impact_tier": 2, "region": "EU",
     "source": "ecb.europa.eu/press/calendars/mgcgc/html/"},
    {"date": "2026-07-29", "time_et": "14:00", "event_type": "FOMC",
     "description": "FOMC rate decision + press conference",
     "market_impact_tier": 1, "region": "US",
     "source": "federalreserve.gov/monetarypolicy/fomccalendars.htm"},

    # --- August 2026 ---
    {"date": "2026-08-07", "time_et": "08:30", "event_type": "NFP",
     "description": "July nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-08-12", "time_et": "08:30", "event_type": "CPI",
     "description": "July CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},

    # --- September 2026 ---
    {"date": "2026-09-04", "time_et": "08:30", "event_type": "NFP",
     "description": "August nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-09-10", "time_et": "07:45", "event_type": "ECB",
     "description": "ECB Governing Council monetary policy decision",
     "market_impact_tier": 2, "region": "EU",
     "source": "ecb.europa.eu/press/calendars/mgcgc/html/"},
    {"date": "2026-09-11", "time_et": "08:30", "event_type": "CPI",
     "description": "August CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},
    {"date": "2026-09-16", "time_et": "14:00", "event_type": "FOMC",
     "description": "FOMC rate decision + SEP + press conference",
     "market_impact_tier": 1, "region": "US",
     "source": "federalreserve.gov/monetarypolicy/fomccalendars.htm"},

    # --- October 2026 ---
    {"date": "2026-10-02", "time_et": "08:30", "event_type": "NFP",
     "description": "September nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-10-14", "time_et": "08:30", "event_type": "CPI",
     "description": "September CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},
    {"date": "2026-10-29", "time_et": "14:00", "event_type": "FOMC",
     "description": "FOMC rate decision + press conference",
     "market_impact_tier": 1, "region": "US",
     "source": "federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"date": "2026-10-29", "time_et": "07:45", "event_type": "ECB",
     "description": "ECB Governing Council monetary policy decision",
     "market_impact_tier": 2, "region": "EU",
     "source": "ecb.europa.eu/press/calendars/mgcgc/html/"},

    # --- November 2026 ---
    {"date": "2026-11-06", "time_et": "08:30", "event_type": "NFP",
     "description": "October nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-11-12", "time_et": "08:30", "event_type": "CPI",
     "description": "October CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},
    {"date": "2026-11-30", "time_et": "00:00", "event_type": "OPEC",
     "description": "OPEC Ordinary Ministerial Meeting (year-end policy)",
     "market_impact_tier": 1, "region": "OPEC",
     "source": "opec.org/opec_web/en/press_room/9.htm"},

    # --- December 2026 ---
    {"date": "2026-12-04", "time_et": "08:30", "event_type": "NFP",
     "description": "November nonfarm payrolls",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/empsit.htm"},
    {"date": "2026-12-10", "time_et": "08:30", "event_type": "CPI",
     "description": "November CPI release",
     "market_impact_tier": 1, "region": "US",
     "source": "bls.gov/schedule/news_release/cpi.htm"},
    {"date": "2026-12-10", "time_et": "07:45", "event_type": "ECB",
     "description": "ECB Governing Council monetary policy decision",
     "market_impact_tier": 2, "region": "EU",
     "source": "ecb.europa.eu/press/calendars/mgcgc/html/"},
    {"date": "2026-12-16", "time_et": "14:00", "event_type": "FOMC",
     "description": "FOMC rate decision + SEP + press conference",
     "market_impact_tier": 1, "region": "US",
     "source": "federalreserve.gov/monetarypolicy/fomccalendars.htm"},
]


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def get_upcoming_events(
    lookforward_days: int = 30,
    event_types: list[str] | None = None,
    region: str | None = None,
    today: date | None = None,
) -> list[EconomicEvent]:
    """
    Return events occurring within `lookforward_days` of `today` (default
    = current UTC date), sorted by date ascending.

    Filters:
      event_types: list of event_type strings to keep ("FOMC", "CPI", ...).
                   None = all types.
      region:      single region code ("US", "EU", "OPEC", etc.). None = all.

    Returns [] when no upcoming events match — never None.

    Coverage gap detection: if the seed file ends before
    today + lookforward_days, the result is correctly empty AND the
    caller can detect this by checking the seed's coverage end date.
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=int(max(0, lookforward_days)))

    out: list[EconomicEvent] = []
    for evt in ECONOMIC_EVENTS:
        d = _parse_date(evt["date"])
        if d is None:
            continue
        if d < today or d > cutoff:
            continue
        if event_types and evt["event_type"] not in event_types:
            continue
        if region and evt["region"] != region:
            continue
        out.append(evt)

    out.sort(key=lambda e: (e["date"], e.get("time_et", "")))
    return out


def get_events_in_window(
    start: date, end: date,
    event_types: list[str] | None = None,
    region: str | None = None,
) -> list[EconomicEvent]:
    """Return all events between start and end (inclusive), sorted ascending."""
    out: list[EconomicEvent] = []
    for evt in ECONOMIC_EVENTS:
        d = _parse_date(evt["date"])
        if d is None:
            continue
        if d < start or d > end:
            continue
        if event_types and evt["event_type"] not in event_types:
            continue
        if region and evt["region"] != region:
            continue
        out.append(evt)
    out.sort(key=lambda e: (e["date"], e.get("time_et", "")))
    return out


def coverage_end_date() -> date | None:
    """The latest event date in the seed. Use to detect when the file is stale."""
    dates = [_parse_date(e["date"]) for e in ECONOMIC_EVENTS]
    valid = [d for d in dates if d is not None]
    return max(valid) if valid else None


def time_horizon_days(horizon: str) -> int:
    """
    Map a TradeIdea.time_horizon string ("days", "weeks", "months", "intraday")
    to a numeric lookforward window. Used by Risk Manager to flag events
    within a position's expected holding period.
    """
    h = (horizon or "").strip().lower()
    if h.startswith("intra"):
        return 1
    if h.startswith("day"):
        return 5
    if h.startswith("week"):
        return 21
    if h.startswith("month"):
        return 60
    if h.startswith("quarter"):
        return 90
    return 30  # sensible default for an unspecified horizon
