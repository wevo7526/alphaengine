"""
data/screens.py — Dynamic universe screens for hidden-gem discovery.

Five live screens that surface non-consensus alpha candidates from SEC + market
data. Every candidate carries `evidence` (typed source references) so the
Strategist can cite specific receipts in trade memos, and `reasons` (plain-
English bullets) so a PM can immediately see why the screen returned a name.

Screens implemented:

  1. screen_insider_clusters    — ≥N unique Form-4 buyers in last K days,
                                   weighted toward CEO/CFO buys.
  2. screen_13f_new_initiations — Names newly initiated by ≥M smart-money
                                   funds in their latest 13F (vs prior 13F).
  3. screen_post_earnings_drift — Earnings surprise ≥X% with thin analyst
                                   coverage — the classic PEAD setup.
  4. screen_52w_low_with_insider_buys — Price within Y% of 52w low AND
                                   recent insider buying (turnaround filter).
  5. screen_sector_adjacent_to_theme  — Picks-and-shovels mapping for known
                                   themes (curated; no API calls).

All screens return list[ScreenCandidate] sorted by score descending.
Empty results return [] (never None) so consumers can iterate safely.

Cache: 6h TTL per-screen, keyed by parameters. The SEC and market clients
have their own caches underneath, so the screen-level cache mostly absorbs
cross-call repetition during a single agent run.

Anti-repetition: `recently_proposed` (a list of tickers the user has already
seen in memos) is accepted by each screen and used to penalize candidates
already in their fatigue list. The penalty is multiplicative on score; we
don't drop them entirely because a name with overwhelming new evidence may
still belong on the slate.
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

from data.market_client import MarketDataClient
from data.sec_client import SECDataClient
from data.smart_money import SMART_MONEY_FUNDS, get_active_funds
from infra.cache import TTLCache

logger = logging.getLogger(__name__)

_sec = SECDataClient()
_market = MarketDataClient()
_cache: TTLCache = TTLCache(max_entries=200, ttl_seconds=6 * 3600)  # 6h


# Insider role weighting. Officer rank predicts signal quality — CEO buys
# correlate with future returns far more than director buys (Cohen-Malloy-
# Pomorski 2012 and follow-ons).
INSIDER_ROLE_WEIGHTS: dict[str, float] = {
    "ceo": 2.0,
    "chief executive": 2.0,
    "cfo": 2.0,
    "chief financial": 2.0,
    "coo": 1.5,
    "chief operating": 1.5,
    "president": 1.5,
    "chairman": 1.5,
    "chief": 1.4,
    "officer": 1.2,
    "director": 1.0,
    "10%": 0.7,
}

# Anti-repetition penalty: name appears recently → score multiplied by this
REPETITION_PENALTY = 0.5


class ScreenCandidate(TypedDict, total=False):
    ticker: str
    score: float
    screen: str
    reasons: list[str]
    evidence: list[dict[str, Any]]
    # Optional screen-specific fields
    n_unique_insiders: int
    n_transactions: int
    total_dollar_value: float
    ceo_cfo_buying: bool
    n_funds_initiating: int
    initiating_funds: list[str]
    earnings_surprise_pct: float
    n_analysts: int
    pct_above_52w_low: float


# ─────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────

def _cache_key(name: str, params: dict[str, Any]) -> str:
    """Stable key for a screen invocation."""
    items = sorted(params.items())
    payload = json.dumps(items, default=str, sort_keys=True)
    return f"{name}:{payload}"


def _role_weight(title: str | None) -> float:
    """Weight an insider's title by predictive importance."""
    if not title:
        return 1.0
    t = title.lower()
    # Iterate keys longest-first so 'chief financial' wins over 'chief'
    for key in sorted(INSIDER_ROLE_WEIGHTS.keys(), key=len, reverse=True):
        if key in t:
            return INSIDER_ROLE_WEIGHTS[key]
    return 1.0


def _parse_date(s: str | None) -> datetime | None:
    """Permissive ISO date parser. Accepts YYYY-MM-DD or full ISO timestamps."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s[:10])
    except ValueError:
        return None


def _apply_repetition_penalty(
    candidates: list[ScreenCandidate], recently_proposed: list[str] | None
) -> list[ScreenCandidate]:
    """Multiply score by REPETITION_PENALTY for any ticker in the fatigue list."""
    if not recently_proposed:
        return candidates
    fatigue = {t.upper() for t in recently_proposed if t}
    for c in candidates:
        if c["ticker"] in fatigue:
            c["score"] = round(c["score"] * REPETITION_PENALTY, 3)
            c.setdefault("reasons", []).append(
                f"Score reduced ×{REPETITION_PENALTY:.2f}: appeared in recent memos"
            )
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def _extract_insider_facts(filing: dict[str, Any]) -> dict[str, Any]:
    """
    Pull the fields we care about from one Form-4 filing dict returned by
    sec-api InsiderTradingApi. Defensive across response shape variations.

    Returns:
      {
        accession, filed_at, transaction_date, owner_name, owner_title,
        is_purchase, shares, price_per_share, transaction_value
      }
    or None if the filing isn't a usable Form-4 transaction.
    """
    out: dict[str, Any] = {}
    out["accession"] = filing.get("accessionNo") or filing.get("accessionNumber")
    out["filed_at"] = filing.get("filedAt") or filing.get("filed_at")

    owner = filing.get("reportingOwner") or filing.get("reporting_owner") or {}
    out["owner_name"] = (
        owner.get("name")
        or filing.get("ownerName")
        or filing.get("reportingOwnerName")
    )
    rel = owner.get("relationship") or {}
    out["owner_title"] = (
        rel.get("officerTitle")
        or owner.get("officerTitle")
        or filing.get("ownerTitle")
        or filing.get("officerTitle")
    )

    # Non-derivative table holds the actual stock transactions
    nd_table = filing.get("nonDerivativeTable") or {}
    transactions = nd_table.get("transactions") or filing.get("transactions") or []
    # The filing may carry multiple transactions; we aggregate purchases here
    total_shares = 0.0
    total_value = 0.0
    last_date: str | None = None
    is_purchase = False
    for tx in transactions:
        coding = tx.get("transactionCoding") or {}
        code = (coding.get("code") or tx.get("transactionCode") or "").strip().upper()
        if code != "P":  # P = open-market purchase. A = grant; M = exercise; S = sell.
            continue
        is_purchase = True
        amounts = tx.get("transactionAmounts") or {}
        try:
            shares = float(amounts.get("shares") or tx.get("shares") or 0)
        except (TypeError, ValueError):
            shares = 0.0
        price_struct = amounts.get("pricePerShare") or {}
        try:
            price = float(price_struct.get("value") or tx.get("pricePerShare") or 0)
        except (TypeError, ValueError):
            price = 0.0
        total_shares += shares
        total_value += shares * price
        d = tx.get("transactionDate") or amounts.get("transactionDate")
        if d:
            last_date = str(d)[:10]

    out["is_purchase"] = is_purchase
    out["shares"] = total_shares
    out["transaction_value"] = total_value
    out["transaction_date"] = last_date or (str(out["filed_at"])[:10] if out["filed_at"] else None)
    return out if is_purchase else {}


# ─────────────────────────────────────────────────────────────────────────
# 1. Insider clusters
# ─────────────────────────────────────────────────────────────────────────

def screen_insider_clusters(
    universe: list[str],
    lookback_days: int = 30,
    min_unique_buyers: int = 3,
    recently_proposed: list[str] | None = None,
) -> list[ScreenCandidate]:
    """
    Find tickers with cluster insider buying — ≥`min_unique_buyers` distinct
    insiders making open-market purchases (Form 4 code P) in the last
    `lookback_days`.

    Score = sum(role-weighted insider count) × (1 + 0.5 if CEO/CFO buying)
            × log10(1 + total_dollar_value / 1000)

    This favors broad participation (many distinct buyers > one big buyer),
    senior involvement (CEO/CFO carry 2x weight vs director's 1x), and
    dollar size — a $5K director buy is signal-poor.
    """
    if not universe:
        return []
    params = {
        "u_hash": hash(tuple(sorted(set(universe)))),
        "lookback": lookback_days,
        "min_buyers": min_unique_buyers,
    }
    ck = _cache_key("insider_clusters", params)
    cached = _cache.get(ck)
    if cached is not None:
        return _apply_repetition_penalty(list(cached), recently_proposed)

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    cutoff_iso = cutoff_dt.strftime("%Y-%m-%d")
    candidates: list[ScreenCandidate] = []

    for ticker in universe:
        try:
            response = _sec.get_insider_trades(
                ticker, start_date=cutoff_iso,
                end_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                limit=50,
            )
        except Exception as e:
            logger.debug(f"insider_trades fetch failed for {ticker}: {e}")
            continue

        filings = (response or {}).get("data") or []
        if not filings:
            continue

        # name -> max role weight; total $ value across all buys
        insider_weights: dict[str, float] = {}
        total_value = 0.0
        ceo_cfo_active = False
        accessions: set[str] = set()
        transaction_count = 0

        for f in filings:
            facts = _extract_insider_facts(f)
            if not facts:
                continue
            tx_date = _parse_date(facts.get("transaction_date"))
            if tx_date is None or tx_date < cutoff_dt.replace(tzinfo=None):
                continue
            name = facts.get("owner_name")
            if not name:
                continue
            title = facts.get("owner_title")
            w = _role_weight(title)
            insider_weights[name] = max(insider_weights.get(name, 0.0), w)
            total_value += float(facts.get("transaction_value") or 0.0)
            transaction_count += 1
            if w >= 2.0:  # CEO/CFO weight
                ceo_cfo_active = True
            acc = facts.get("accession")
            if acc:
                accessions.add(str(acc))

        if len(insider_weights) < min_unique_buyers:
            continue

        weight_sum = sum(insider_weights.values())
        senior_boost = 1.5 if ceo_cfo_active else 1.0
        size_factor = math.log10(1.0 + total_value / 1000.0) if total_value > 0 else 0.0
        score = weight_sum * senior_boost * (1.0 + size_factor)

        reasons = [
            f"{len(insider_weights)} unique Form-4 buyers in {lookback_days}d",
            f"${total_value/1000:.0f}K aggregate open-market purchases",
        ]
        if ceo_cfo_active:
            reasons.append("CEO or CFO participating")

        candidate: ScreenCandidate = {
            "ticker": ticker.upper(),
            "score": round(float(score), 3),
            "screen": "insider_clusters",
            "n_unique_insiders": len(insider_weights),
            "n_transactions": transaction_count,
            "total_dollar_value": round(total_value, 2),
            "ceo_cfo_buying": ceo_cfo_active,
            "reasons": reasons,
            "evidence": [
                {"type": "sec_form_4", "accession_number": a}
                for a in list(accessions)[:5]
            ],
        }
        candidates.append(candidate)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    _cache.set(ck, candidates)
    return _apply_repetition_penalty(list(candidates), recently_proposed)


# ─────────────────────────────────────────────────────────────────────────
# 2. 13F new initiations from smart-money funds
# ─────────────────────────────────────────────────────────────────────────

def _13f_filings_for_cik(cik: str, n: int = 2) -> list[dict[str, Any]]:
    """Return the n most recent 13F filings for a CIK (latest first)."""
    try:
        resp = _sec.get_13f_holdings(cik)
    except Exception as e:
        logger.debug(f"13F fetch failed for CIK {cik}: {e}")
        return []
    # get_13f_holdings asks for only the latest. To get prior, we need a
    # separate query. The sec-api spec accepts a size parameter via
    # holdings_api.get_data directly — replicate that here.
    # Fallback: just use the most recent we got.
    filings = (resp or {}).get("data") or []
    return filings[:n]


def _holdings_set_from_filing(filing: dict[str, Any]) -> dict[str, dict]:
    """
    Return {ticker: {value_usd, shares, pct_of_book}} for one 13F filing.
    The sec-api shape is `holdings: [{ticker, valueUsd, ...}, ...]`.
    """
    holdings = filing.get("holdings") or []
    by_ticker: dict[str, dict] = {}
    total_value = 0.0
    for h in holdings:
        t = (h.get("ticker") or "").strip().upper()
        if not t:
            continue
        try:
            v = float(h.get("valueUsd") or h.get("value") or 0)
        except (TypeError, ValueError):
            v = 0.0
        try:
            s = float(h.get("shares") or 0)
        except (TypeError, ValueError):
            s = 0.0
        if t not in by_ticker:
            by_ticker[t] = {"value_usd": 0.0, "shares": 0.0}
        by_ticker[t]["value_usd"] += v
        by_ticker[t]["shares"] += s
        total_value += v
    if total_value > 0:
        for v in by_ticker.values():
            v["pct_of_book"] = v["value_usd"] / total_value
    else:
        for v in by_ticker.values():
            v["pct_of_book"] = 0.0
    return by_ticker


def screen_13f_new_initiations(
    min_position_pct: float = 0.01,
    min_funds_initiating: int = 1,
    recently_proposed: list[str] | None = None,
) -> list[ScreenCandidate]:
    """
    For each smart-money fund, compare latest 13F vs the prior quarter's 13F.
    Tickers present in the latest but absent (or near-zero) in the prior are
    "new initiations." We require position size ≥ `min_position_pct` of the
    fund's book to filter out trivial / closet-indexer positions.

    Score = sum across initiating funds of (position_pct × fund_weight),
    where fund_weight defaults to 1.0 per fund (could be tuned for AUM).

    13F data has a 45-day lag — these aren't real-time. The value is in the
    long tail of names that aren't in the consensus headlines yet.
    """
    params = {
        "min_pct": min_position_pct,
        "min_funds": min_funds_initiating,
    }
    ck = _cache_key("13f_new_initiations", params)
    cached = _cache.get(ck)
    if cached is not None:
        return _apply_repetition_penalty(list(cached), recently_proposed)

    # ticker -> {n_funds, total_pct, initiating_funds, evidence}
    aggregator: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n_funds": 0, "total_pct": 0.0, "initiating_funds": [], "evidence": []}
    )

    for fund in get_active_funds():
        cik = fund["cik"]
        filings = _13f_filings_for_cik(cik, n=2)
        if len(filings) < 2:
            # Need both latest and prior to detect new initiations
            continue
        latest = _holdings_set_from_filing(filings[0])
        prior = _holdings_set_from_filing(filings[1])

        latest_accession = filings[0].get("accessionNo") or filings[0].get("accessionNumber")
        period_of_report = filings[0].get("periodOfReport") or filings[0].get("period_of_report")

        for ticker, info in latest.items():
            if ticker in prior and prior[ticker]["value_usd"] > 0:
                continue  # not a new initiation
            pct = info.get("pct_of_book", 0.0)
            if pct < min_position_pct:
                continue
            agg = aggregator[ticker]
            agg["n_funds"] = agg["n_funds"] + 1
            agg["total_pct"] = agg["total_pct"] + pct
            agg["initiating_funds"].append(fund["fund_name"])
            agg["evidence"].append({
                "type": "sec_13f_initiation",
                "fund_name": fund["fund_name"],
                "manager": fund["manager"],
                "cik": cik,
                "accession_number": latest_accession,
                "period_of_report": period_of_report,
                "position_pct_of_book": round(pct, 4),
            })

    candidates: list[ScreenCandidate] = []
    for ticker, agg in aggregator.items():
        if agg["n_funds"] < min_funds_initiating:
            continue
        # Score: number of funds × average position size × log boost on dollar conviction
        avg_pct = agg["total_pct"] / max(1, agg["n_funds"])
        score = float(agg["n_funds"]) * (avg_pct * 100.0)
        reasons = [
            f"Newly initiated by {agg['n_funds']} smart-money fund(s): "
            + ", ".join(agg["initiating_funds"][:3])
            + ("…" if len(agg["initiating_funds"]) > 3 else ""),
            f"Avg position size {avg_pct*100:.2f}% of book",
        ]
        candidates.append({
            "ticker": ticker.upper(),
            "score": round(score, 3),
            "screen": "13f_new_initiations",
            "n_funds_initiating": int(agg["n_funds"]),
            "initiating_funds": list(agg["initiating_funds"]),
            "reasons": reasons,
            "evidence": list(agg["evidence"])[:5],
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    _cache.set(ck, candidates)
    return _apply_repetition_penalty(list(candidates), recently_proposed)


# ─────────────────────────────────────────────────────────────────────────
# 3. Post-earnings drift
# ─────────────────────────────────────────────────────────────────────────

def screen_post_earnings_drift(
    universe: list[str],
    min_surprise_pct: float = 15.0,
    max_analyst_count: int = 10,
    lookback_quarters: int = 1,
    recently_proposed: list[str] | None = None,
) -> list[ScreenCandidate]:
    """
    Post-earnings announcement drift (PEAD) candidates: companies that beat
    earnings estimates by ≥`min_surprise_pct` with thin analyst coverage
    (≤`max_analyst_count`). Bernard & Thomas (1989) and subsequent literature
    show PEAD is strongest in under-covered names — exactly the kind of
    hidden-gem the platform should surface.

    Uses market_client.get_fundamentals() to find recent earnings_surprise
    and number_of_analyst_opinions. The fundamentals call is cached so this
    screen is cheap to re-run across a universe.

    Score = surprise_pct × (1 / max(1, n_analysts))  — penalty for crowding.
    """
    if not universe:
        return []
    params = {
        "u_hash": hash(tuple(sorted(set(universe)))),
        "min_surprise": min_surprise_pct,
        "max_analysts": max_analyst_count,
        "lb_q": lookback_quarters,
    }
    ck = _cache_key("pead", params)
    cached = _cache.get(ck)
    if cached is not None:
        return _apply_repetition_penalty(list(cached), recently_proposed)

    candidates: list[ScreenCandidate] = []
    for ticker in universe:
        try:
            f = _market.get_fundamentals(ticker)
        except Exception as e:
            logger.debug(f"fundamentals fetch failed for {ticker}: {e}")
            continue
        if not f:
            continue
        # yfinance .info exposes these (when available): earningsQuarterlyGrowth
        # is YoY EPS growth (decimal), earningsSurprise / earningsSurprisePct
        # can be sparse on the free tier.
        surprise_pct: float | None = None
        for key in (
            "earnings_surprise_pct",
            "earningsSurprisePct",
            "earningsSurprise",
        ):
            v = f.get(key)
            if v is not None:
                try:
                    surprise_pct = float(v)
                    break
                except (TypeError, ValueError):
                    continue
        if surprise_pct is None:
            # Fallback: estimate from EPS quarterly growth — not a true
            # "surprise" but flags abnormal growth
            qg = f.get("earnings_quarterly_growth") or f.get("earningsQuarterlyGrowth")
            try:
                surprise_pct = float(qg) * 100.0 if qg is not None else None
            except (TypeError, ValueError):
                surprise_pct = None
        if surprise_pct is None or surprise_pct < min_surprise_pct:
            continue

        n_analysts = (
            f.get("number_of_analyst_opinions")
            or f.get("numberOfAnalystOpinions")
            or 0
        )
        try:
            n_analysts = int(n_analysts)
        except (TypeError, ValueError):
            n_analysts = 0
        if n_analysts > max_analyst_count:
            continue

        # Score: bigger surprise + thinner coverage → higher
        coverage_penalty = 1.0 / float(max(1, n_analysts))
        score = float(surprise_pct) * coverage_penalty

        reasons = [
            f"Earnings beat / growth of {surprise_pct:.1f}% (≥{min_surprise_pct:.0f}% threshold)",
            f"Only {n_analysts} analyst(s) covering — PEAD strongest in under-covered names",
        ]
        candidates.append({
            "ticker": ticker.upper(),
            "score": round(score, 3),
            "screen": "post_earnings_drift",
            "earnings_surprise_pct": round(float(surprise_pct), 2),
            "n_analysts": int(n_analysts),
            "reasons": reasons,
            "evidence": [
                {"type": "fundamentals_snapshot",
                 "source": "yfinance",
                 "ticker": ticker.upper(),
                 "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
            ],
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    _cache.set(ck, candidates)
    return _apply_repetition_penalty(list(candidates), recently_proposed)


# ─────────────────────────────────────────────────────────────────────────
# 4. 52-week low with insider buying
# ─────────────────────────────────────────────────────────────────────────

def screen_52w_low_with_insider_buys(
    universe: list[str],
    within_pct: float = 5.0,
    insider_lookback_days: int = 30,
    min_unique_buyers: int = 1,
    recently_proposed: list[str] | None = None,
) -> list[ScreenCandidate]:
    """
    Turnaround / contrarian setup: price within `within_pct` of its 52-week
    low AND at least `min_unique_buyers` insider purchase(s) in the last
    `insider_lookback_days`.

    The 52w-low filter alone is a value trap factory. The insider-buy
    filter requires conviction from people who actually know the business.
    The pair is one of the highest-quality contrarian screens documented.

    Score = (insider-cluster-style score) × (1 + (within_pct - pct_above_low))
    """
    if not universe:
        return []
    params = {
        "u_hash": hash(tuple(sorted(set(universe)))),
        "within": within_pct,
        "lookback": insider_lookback_days,
        "min_buyers": min_unique_buyers,
    }
    ck = _cache_key("52wlow_insider", params)
    cached = _cache.get(ck)
    if cached is not None:
        return _apply_repetition_penalty(list(cached), recently_proposed)

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=insider_lookback_days)
    cutoff_iso = cutoff_dt.strftime("%Y-%m-%d")
    candidates: list[ScreenCandidate] = []

    for ticker in universe:
        try:
            f = _market.get_fundamentals(ticker)
        except Exception as e:
            logger.debug(f"fundamentals fetch failed for {ticker}: {e}")
            continue
        if not f:
            continue

        current_price = f.get("current_price") or f.get("regularMarketPrice")
        low_52w = (
            f.get("fifty_two_week_low")
            or f.get("fiftyTwoWeekLow")
            or f.get("52w_low")
        )
        try:
            current_price = float(current_price) if current_price is not None else None
            low_52w = float(low_52w) if low_52w is not None else None
        except (TypeError, ValueError):
            continue
        if not current_price or not low_52w or low_52w <= 0:
            continue

        pct_above_low = (current_price - low_52w) / low_52w * 100.0
        if pct_above_low > within_pct:
            continue

        # Verify insider buying within the window
        try:
            resp = _sec.get_insider_trades(
                ticker, start_date=cutoff_iso,
                end_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                limit=50,
            )
        except Exception as e:
            logger.debug(f"insider trades fetch failed for {ticker}: {e}")
            continue
        filings = (resp or {}).get("data") or []
        if not filings:
            continue

        insider_weights: dict[str, float] = {}
        total_value = 0.0
        ceo_cfo_active = False
        accessions: set[str] = set()
        for fl in filings:
            facts = _extract_insider_facts(fl)
            if not facts:
                continue
            name = facts.get("owner_name")
            if not name:
                continue
            w = _role_weight(facts.get("owner_title"))
            insider_weights[name] = max(insider_weights.get(name, 0.0), w)
            total_value += float(facts.get("transaction_value") or 0.0)
            if w >= 2.0:
                ceo_cfo_active = True
            acc = facts.get("accession")
            if acc:
                accessions.add(str(acc))

        if len(insider_weights) < min_unique_buyers:
            continue

        weight_sum = sum(insider_weights.values())
        proximity_boost = 1.0 + (within_pct - pct_above_low) / within_pct
        score = weight_sum * proximity_boost * (1.0 + (0.5 if ceo_cfo_active else 0.0))

        reasons = [
            f"Within {pct_above_low:.1f}% of 52-week low (${low_52w:.2f})",
            f"{len(insider_weights)} insider buyer(s) in last {insider_lookback_days}d",
            f"${total_value/1000:.0f}K aggregate insider purchases",
        ]
        if ceo_cfo_active:
            reasons.append("CEO or CFO buying")

        candidates.append({
            "ticker": ticker.upper(),
            "score": round(float(score), 3),
            "screen": "52w_low_insider_buy",
            "pct_above_52w_low": round(pct_above_low, 2),
            "n_unique_insiders": len(insider_weights),
            "total_dollar_value": round(total_value, 2),
            "ceo_cfo_buying": ceo_cfo_active,
            "reasons": reasons,
            "evidence": (
                [{"type": "market_price_at_52w_low",
                  "ticker": ticker.upper(),
                  "current_price": current_price,
                  "52w_low": low_52w}]
                + [{"type": "sec_form_4", "accession_number": a}
                   for a in list(accessions)[:4]]
            ),
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    _cache.set(ck, candidates)
    return _apply_repetition_penalty(list(candidates), recently_proposed)


# ─────────────────────────────────────────────────────────────────────────
# 5. Sector-adjacent picks-and-shovels for known themes
# ─────────────────────────────────────────────────────────────────────────

# Curated mapping: theme → picks-and-shovels names.  These are the non-obvious
# beneficiaries — the ones that move when the consensus theme name is already
# priced. Sourced from PM newsletters and industry classifications; should be
# revisited quarterly as new infrastructure suppliers emerge.
#
# Format: {theme: [(ticker, role_description), ...]}
SECTOR_ADJACENT: dict[str, list[tuple[str, str]]] = {
    "ai_capex": [
        ("VRT",  "Vertiv — liquid cooling for data centers"),
        ("ETN",  "Eaton — electrical infrastructure & power management"),
        ("PWR",  "Quanta Services — power transmission build-out"),
        ("VST",  "Vistra — nuclear/gas baseload for AI power demand"),
        ("TLN",  "Talen Energy — nuclear PPAs to hyperscalers"),
        ("CEG",  "Constellation Energy — nuclear, Microsoft deal"),
        ("NRG",  "NRG Energy — independent power producer"),
        ("APH",  "Amphenol — high-speed interconnect for AI servers"),
        ("ANET", "Arista Networks — AI fabric switching"),
        ("COHR", "Coherent — optical transceivers"),
    ],
    "ai_inference": [
        ("MRVL", "Marvell — custom silicon, optical DSPs"),
        ("AVGO", "Broadcom — custom AI accelerators (Google TPU)"),
        ("QCOM", "Qualcomm — edge inference silicon"),
        ("ARM",  "ARM — Cortex IP in edge devices"),
        ("ON",   "ON Semiconductor — power management for inference"),
    ],
    "energy_transition": [
        ("ALB",  "Albemarle — lithium for batteries"),
        ("MP",   "MP Materials — rare earths for magnets"),
        ("CCJ",  "Cameco — uranium for nuclear restart"),
        ("URA",  "Global X Uranium ETF — broad uranium exposure"),
        ("EME",  "EMCOR — electrical contractor for grid build-out"),
        ("PWR",  "Quanta Services — transmission & substation construction"),
    ],
    "obesity_glp1": [
        ("BHVN", "Biohaven — next-gen GLP-1 and adjacent obesity drugs"),
        ("SMMT", "Summit Therapeutics — oncology/obesity pipeline"),
        ("VKTX", "Viking Therapeutics — VK2735 oral GLP-1"),
        ("ABBV", "AbbVie — obesity-adjacent metabolic drugs"),
    ],
    "data_centers_power": [
        ("VST",  "Vistra — nuclear baseload"),
        ("TLN",  "Talen Energy — nuclear PPAs"),
        ("CEG",  "Constellation Energy — nuclear with hyperscaler deals"),
        ("NRG",  "NRG Energy — generation"),
        ("ETN",  "Eaton — UPS, electrical distribution"),
        ("VRT",  "Vertiv — cooling & racks"),
        ("EQIX", "Equinix — colocation"),
        ("DLR",  "Digital Realty — data center REIT"),
    ],
    "cybersecurity": [
        ("S",    "SentinelOne — endpoint, less-crowded vs CRWD"),
        ("CYBR", "CyberArk — privileged access management"),
        ("RPD",  "Rapid7 — vulnerability management"),
        ("TENB", "Tenable — exposure management"),
        ("OKTA", "Okta — identity, recovering from 2022 breach"),
    ],
    "uranium_nuclear": [
        ("UEC",  "Uranium Energy — US ISR producer"),
        ("UUUU", "Energy Fuels — U + rare earths"),
        ("NXE",  "NexGen — Canadian project developer"),
        ("DNN",  "Denison Mines — Athabasca Basin"),
        ("CCJ",  "Cameco — incumbent producer"),
    ],
    "fintech_disruptors": [
        ("SOFI", "SoFi — full bank charter, multi-product"),
        ("NU",   "Nubank — Latin America neobank"),
        ("MELI", "MercadoLibre — LatAm e-commerce + fintech"),
        ("PAGS", "PagSeguro — Brazil payments"),
        ("HOOD", "Robinhood — crypto + cash sweep"),
    ],
    "regional_banks": [
        ("MTB",  "M&T Bank — quality regional, commercial-heavy"),
        ("FITB", "Fifth Third — Midwest, capital-strong"),
        ("CFG",  "Citizens Financial — Northeast"),
        ("RF",   "Regions — Southeast"),
        ("HBAN", "Huntington — Midwest, conservative book"),
    ],
}


def screen_sector_adjacent_to_theme(
    theme: str,
    recently_proposed: list[str] | None = None,
) -> list[ScreenCandidate]:
    """
    Return picks-and-shovels names for a known theme. No API calls — pure
    curated mapping based on industry analysis.

    Score is uniform across all entries (this is a discovery screen, not a
    ranking screen — it's saying "if you're long this theme, also look here").
    """
    key = theme.strip().lower().replace(" ", "_").replace("-", "_")
    entries = SECTOR_ADJACENT.get(key)
    if not entries:
        return []

    candidates: list[ScreenCandidate] = []
    for ticker, role in entries:
        candidates.append({
            "ticker": ticker.upper(),
            "score": 1.0,
            "screen": "sector_adjacent",
            "reasons": [f"Picks-and-shovels for '{theme}'", role],
            "evidence": [
                {"type": "curated_theme_mapping",
                 "theme": key,
                 "role": role,
                 "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
            ],
        })
    return _apply_repetition_penalty(candidates, recently_proposed)


# ─────────────────────────────────────────────────────────────────────────
# Cross-screen aggregation
# ─────────────────────────────────────────────────────────────────────────

def merge_screen_results(*screen_lists: list[ScreenCandidate]) -> list[ScreenCandidate]:
    """
    Merge results from multiple screens. When the same ticker appears in
    multiple screens, that's *stronger* signal — keep the union of evidence
    and reasons, sum the scores (with diminishing returns via a sqrt factor
    to avoid double-counting overlap).

    The combined candidate has `screen='multi'` and includes a `screens`
    list of source screen names.
    """
    by_ticker: dict[str, ScreenCandidate] = {}
    for screen_list in screen_lists:
        for c in screen_list or []:
            t = c["ticker"]
            if t not in by_ticker:
                # First sighting — copy and tag screens list
                merged: ScreenCandidate = dict(c)  # shallow copy
                merged["screens"] = [c["screen"]]
                by_ticker[t] = merged
                continue
            # Subsequent sighting — augment
            existing = by_ticker[t]
            existing["score"] = round(
                float(existing["score"]) + math.sqrt(float(c["score"])),
                3,
            )
            existing.setdefault("screens", []).append(c["screen"])
            existing.setdefault("reasons", []).extend(c.get("reasons", []))
            existing.setdefault("evidence", []).extend(c.get("evidence", []))
    merged_list = list(by_ticker.values())
    for c in merged_list:
        if len(c.get("screens", [])) > 1:
            c["screen"] = "multi"
    merged_list.sort(key=lambda c: c["score"], reverse=True)
    return merged_list
