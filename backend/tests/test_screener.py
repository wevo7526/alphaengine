"""Live market screener — pure filter/mapping tests (no network)."""

from data.market_screener import _passes_quality, _quote_to_candidate, _run_alpha_vantage_movers


def test_quality_keeps_liquid_us_equity():
    assert _passes_quality({
        "symbol": "RPAY", "exchange": "NMS", "regularMarketPrice": 9.0,
        "quoteType": "EQUITY", "averageDailyVolume3Month": 500_000,
    })


def test_quality_drops_otc_foreign_penny_and_etf():
    # OTC pink-sheet, 5-letter F-suffix foreign ordinary
    assert not _passes_quality({"symbol": "TRUHF", "exchange": "PNK", "regularMarketPrice": 1.2, "quoteType": "EQUITY"})
    # sub-$3 penny
    assert not _passes_quality({"symbol": "PENNY", "exchange": "NMS", "regularMarketPrice": 0.8, "quoteType": "EQUITY"})
    # thin volume
    assert not _passes_quality({"symbol": "THIN", "exchange": "NMS", "regularMarketPrice": 12, "quoteType": "EQUITY", "averageDailyVolume3Month": 1000})
    # ETF, not a single name
    assert not _passes_quality({"symbol": "SPY", "exchange": "PCX", "regularMarketPrice": 500, "quoteType": "ETF"})


def test_quote_to_candidate_shape():
    c = _quote_to_candidate({"symbol": "tygo", "shortName": "Tigo", "marketCap": 4.2e8,
                             "regularMarketPrice": 7.1, "sector": "Technology",
                             "averageDailyVolume3Month": 300_000})
    assert c["ticker"] == "TYGO" and c["source"] == "yfinance_screener"
    assert c["market_cap"] == 4.2e8 and c["sector"] == "Technology"


def test_av_movers_never_raises_without_key(monkeypatch):
    # With no AV key the client returns {} → movers is an empty list, never raises.
    from config import settings
    monkeypatch.setattr(settings, "ALPHA_VANTAGE_KEY", "", raising=False)
    assert _run_alpha_vantage_movers() == []
