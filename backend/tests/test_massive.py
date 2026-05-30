"""Contract tests for the Massive data-layer migration.

These assert that the post-migration `MarketDataClient` preserves the exact
return SHAPES that downstream quant code (cointegration, factors, spreads,
backtester, optimizer, pairs, stress, curve) and the agents depend on. The
migration swapped the underlying data source (yfinance/Finnhub/NewsAPI/
Alpha Vantage -> Massive) but the contract MUST be byte-for-byte stable.

NO live network calls: we monkeypatch the single Massive HTTP boundary
(`massive_client._get`) for the price path, and the higher-level
`massive_client` functions for the computed-fundamentals path.
"""

from __future__ import annotations

import pytest

from data import massive_client
from data.market_client import MarketDataClient


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_massive_caches():
    """Module-level Massive caches persist across tests; reset them so each
    test sees its own monkeypatched data rather than a warm cache entry."""
    for c in (
        massive_client._agg_cache,
        massive_client._price_cache,
        massive_client._quote_cache,
        massive_client._reference_cache,
        massive_client._financials_cache,
        massive_client._options_cache,
        massive_client._news_cache,
        massive_client._grouped_cache,
        massive_client._beta_cache,
    ):
        c.clear()
    yield


# Two daily aggregate bars in the raw Massive/Polygon shape. `t` is epoch
# milliseconds (UTC); 1700006400000 = 2023-11-15, 1700092800000 = 2023-11-16.
_RAW_AGG_RESULTS = [
    {"t": 1700006400000, "o": 100.123, "h": 105.987, "l": 99.5, "c": 104.444, "v": 1234567, "vw": 102.5, "n": 5000},
    {"t": 1700092800000, "o": 104.5, "h": 108.2, "l": 103.1, "c": 107.77, "v": 2222222.0, "vw": 106.1, "n": 6000},
]


# ── get_price_history shape ────────────────────────────────────────────────

def test_get_price_history_exact_shape(monkeypatch):
    """get_price_history must return list[{date, open, high, low, close, volume}]
    with date 'YYYY-MM-DD', OHLC rounded floats, volume an int."""

    def fake_get(path, *, params=None, label="massive"):
        # All price data flows through the aggregates endpoint.
        assert "/v2/aggs/ticker/" in path
        return {"results": _RAW_AGG_RESULTS, "status": "OK"}

    monkeypatch.setattr(massive_client, "_get", fake_get)

    client = MarketDataClient()
    bars = client.get_price_history("AAPL", period="6mo")

    assert isinstance(bars, list)
    assert len(bars) == 2

    expected_keys = {"date", "open", "high", "low", "close", "volume"}
    for bar in bars:
        assert isinstance(bar, dict)
        # EXACT key set — no extra, no missing.
        assert set(bar.keys()) == expected_keys

        # date format: 'YYYY-MM-DD'
        assert isinstance(bar["date"], str)
        assert len(bar["date"]) == 10
        assert bar["date"][4] == "-" and bar["date"][7] == "-"
        # parse-validates the format
        import datetime as _dt
        _dt.datetime.strptime(bar["date"], "%Y-%m-%d")

        # OHLC are floats
        for k in ("open", "high", "low", "close"):
            assert isinstance(bar[k], float)

        # volume is a plain int (NOT float / numpy)
        assert type(bar["volume"]) is int

    # Sorted ascending by date and value-correct (2dp rounding, int volume).
    assert bars[0]["date"] == "2023-11-15"
    assert bars[1]["date"] == "2023-11-16"
    assert bars[0]["open"] == 100.12       # round(100.123, 2)
    assert bars[0]["high"] == 105.99       # round(105.987, 2)
    assert bars[0]["close"] == 104.44      # round(104.444, 2)
    assert bars[0]["volume"] == 1234567
    assert bars[1]["volume"] == 2222222    # 2222222.0 -> int


def test_get_price_history_empty_on_no_data(monkeypatch):
    """No bars from Massive -> empty list, never a crash."""
    monkeypatch.setattr(
        massive_client, "_get",
        lambda path, *, params=None, label="massive": {"results": [], "status": "OK"},
    )
    client = MarketDataClient()
    assert client.get_price_history("ZZZZ", period="1mo") == []


# ── get_fundamentals full key set ──────────────────────────────────────────

# Full key contract the downstream stack relies on.
_FUNDAMENTALS_KEYS = {
    "pe_ratio",
    "forward_pe",
    "pb_ratio",
    "ev_ebitda",
    "market_cap",
    "revenue_growth",
    "profit_margin",
    "debt_to_equity",
    "free_cash_flow",
    "dividend_yield",
    "beta",
    "52w_high",
    "52w_low",
    "short_ratio",
    "sector",
    "industry",
    "current_price",
    "avg_volume_10d",
    "avg_volume_3m",
    "bid",
    "ask",
    "shares_outstanding",
    "float_shares",
}


def _financials_report(revenue, net_income, ebitda, equity, debt, cash, ocf, capex):
    """Build one Massive financials report in the nested {value: ...} shape."""
    def v(x):
        return {"value": x}
    return {
        "fiscal_period": "Q1",
        "fiscal_year": "2024",
        "financials": {
            "income_statement": {
                "revenues": v(revenue),
                "net_income_loss": v(net_income),
                "ebitda": v(ebitda),
            },
            "balance_sheet": {
                "equity_attributable_to_parent": v(equity),
                "long_term_debt": v(debt),
                "cash": v(cash),
            },
            "cash_flow_statement": {
                "net_cash_flow_from_operating_activities": v(ocf),
                "capital_expenditure": v(capex),
            },
        },
    }


def test_get_fundamentals_full_key_set(monkeypatch):
    """get_fundamentals must return the full, exact key set with the right
    value TYPES for the fields Massive can populate."""

    reports = [
        # newest
        _financials_report(revenue=1000.0, net_income=200.0, ebitda=300.0,
                           equity=500.0, debt=250.0, cash=100.0,
                           ocf=180.0, capex=-40.0),
        # prior (for revenue_growth)
        _financials_report(revenue=800.0, net_income=150.0, ebitda=240.0,
                           equity=480.0, debt=240.0, cash=90.0,
                           ocf=160.0, capex=-30.0),
    ]

    monkeypatch.setattr(massive_client, "financials", lambda t, limit=8: reports)
    monkeypatch.setattr(
        massive_client, "ticker_reference",
        lambda t: {
            "market_cap": 4000.0,
            "sector": "Technology",
            "sic_description": "Electronic Computers",
            "weighted_shares_outstanding": 100.0,
        },
    )
    monkeypatch.setattr(massive_client, "last_price", lambda t: 50.0)
    monkeypatch.setattr(massive_client, "compute_beta", lambda t, benchmark="SPY", period="1y": 1.23)
    monkeypatch.setattr(
        massive_client, "price_bars",
        lambda t, period="1y", adjusted=False, round_dp=2: [
            {"date": "2024-01-02", "open": 40.0, "high": 60.0, "low": 38.0, "close": 55.0, "volume": 1000},
            {"date": "2024-01-03", "open": 55.0, "high": 62.0, "low": 50.0, "close": 58.0, "volume": 2000},
        ],
    )

    client = MarketDataClient()
    f = client.get_fundamentals("AAPL")

    assert isinstance(f, dict)
    # EXACT key set — no extra, no missing.
    assert set(f.keys()) == _FUNDAMENTALS_KEYS

    # Fields Massive CAN populate:
    assert f["market_cap"] == 4000.0
    assert f["sector"] == "Technology"
    assert f["current_price"] == 50.0
    assert f["beta"] == 1.23
    assert f["shares_outstanding"] == 100.0
    # profit_margin = 200/1000
    assert f["profit_margin"] == 0.2
    # pe = price / (net_income/shares) = 50 / (200/100) = 50/2 = 25
    assert f["pe_ratio"] == 25.0
    # pb = market_cap/equity = 4000/500 = 8
    assert f["pb_ratio"] == 8.0
    # d/e = 250/500 = 0.5
    assert f["debt_to_equity"] == 0.5
    # ev_ebitda = (4000 + 250 - 100) / 300 = 4150/300
    assert f["ev_ebitda"] == round(4150.0 / 300.0, 4)
    # fcf = ocf - abs(capex) = 180 - 40 = 140
    assert f["free_cash_flow"] == 140.0
    # revenue_growth = (1000-800)/800 = 0.25
    assert f["revenue_growth"] == 0.25
    # 52w hi/lo from the 1y bars
    assert f["52w_high"] == 62.0
    assert f["52w_low"] == 38.0
    assert type(f["avg_volume_10d"]) is int

    # Analyst/gap fields with no Massive source MUST stay None.
    for gap in ("forward_pe", "dividend_yield", "short_ratio", "bid", "ask", "float_shares"):
        assert f[gap] is None


def test_get_consensus_reduced_shape(monkeypatch):
    """get_consensus preserves its full shape but only current_price /
    revenue_growth are populated (Massive has no analyst data)."""
    monkeypatch.setattr(massive_client, "last_price", lambda t: 123.45)
    monkeypatch.setattr(massive_client, "financials", lambda t, limit=8: [])

    client = MarketDataClient()
    c = client.get_consensus("AAPL")

    expected = {
        "ticker", "current_price", "target_mean", "target_high", "target_low",
        "target_median", "num_analysts", "recommendation_mean",
        "recommendation_key", "forward_eps", "trailing_eps", "earnings_growth",
        "revenue_growth", "implied_upside_pct",
    }
    assert set(c.keys()) == expected
    assert c["current_price"] == 123.45
    # analyst-only fields are None
    assert c["target_mean"] is None
    assert c["num_analysts"] is None
    assert c["recommendation_key"] is None
