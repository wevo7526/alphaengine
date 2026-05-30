"""Free-tier Alpha Vantage: OVERVIEW normalization, budget guard, and the
consensus-gap wiring. No live calls — the HTTP boundary is monkeypatched."""

from __future__ import annotations

import data.alpha_vantage_client as av
from data.market_client import MarketDataClient


_RAW_OVERVIEW = {
    "Symbol": "AAPL",
    "AnalystTargetPrice": "240.50",
    "AnalystRatingStrongBuy": "10",
    "AnalystRatingBuy": "15",
    "AnalystRatingHold": "8",
    "AnalystRatingSell": "2",
    "AnalystRatingStrongSell": "0",
    "PERatio": "32.5",
    "EVToEBITDA": "24.1",
    "Beta": "1.21",
    "EPS": "6.42",
    "QuarterlyRevenueGrowthYOY": "0.08",
    "Sector": "TECHNOLOGY",
}


def _reset():
    av._overview_cache.clear()
    av._calls_today = 0
    av._calls_date = None


def test_overview_normalizes_and_derives_recommendation(monkeypatch):
    _reset()
    monkeypatch.setattr(av.settings, "ALPHA_VANTAGE_KEY", "k", raising=False)
    monkeypatch.setattr(av.settings, "ALPHA_VANTAGE_DAILY_BUDGET", 20, raising=False)
    monkeypatch.setattr(av, "http_get_json", lambda *a, **k: dict(_RAW_OVERVIEW))

    ov = av.get_overview("AAPL")
    assert ov["analyst_target_price"] == 240.50
    assert ov["beta"] == 1.21
    assert ov["num_analysts"] == 35
    # mostly buys -> buy/strong_buy
    assert ov["recommendation_key"] in ("buy", "strong_buy")


def test_daily_budget_guard_blocks_over_cap(monkeypatch):
    _reset()
    monkeypatch.setattr(av.settings, "ALPHA_VANTAGE_KEY", "k", raising=False)
    monkeypatch.setattr(av.settings, "ALPHA_VANTAGE_DAILY_BUDGET", 2, raising=False)
    calls = {"n": 0}

    def _http(*a, **k):
        calls["n"] += 1
        return dict(_RAW_OVERVIEW, Symbol=f"T{calls['n']}")

    monkeypatch.setattr(av, "http_get_json", _http)
    # 2 distinct tickers allowed, 3rd is over budget -> {} and no HTTP call.
    assert av.get_overview("AAA")
    assert av.get_overview("BBB")
    assert av.get_overview("CCC") == {}
    assert calls["n"] == 2


def test_overview_empty_without_key(monkeypatch):
    _reset()
    monkeypatch.setattr(av.settings, "ALPHA_VANTAGE_KEY", "", raising=False)
    assert av.get_overview("AAPL") == {}


def test_get_consensus_fills_analyst_fields_from_av(monkeypatch):
    """With AV available, get_consensus fills target + recommendation that
    Massive cannot provide; implied upside is computed from current price."""
    _reset()
    from data import massive_client
    monkeypatch.setattr(massive_client, "last_price", lambda t: 200.0)
    monkeypatch.setattr(massive_client, "financials", lambda t, limit=8: [])
    monkeypatch.setattr(av.settings, "ALPHA_VANTAGE_KEY", "k", raising=False)
    monkeypatch.setattr(av.settings, "ALPHA_VANTAGE_DAILY_BUDGET", 20, raising=False)
    monkeypatch.setattr(av, "http_get_json", lambda *a, **k: dict(_RAW_OVERVIEW))

    c = MarketDataClient().get_consensus("AAPL")
    assert c["target_mean"] == 240.50
    assert c["recommendation_key"] in ("buy", "strong_buy")
    assert c["num_analysts"] == 35
    # implied = (240.50 - 200)/200 * 100
    assert c["implied_upside_pct"] == 20.25
