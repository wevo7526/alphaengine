"""Live market screener — pure filter/mapping tests (no network)."""

from data.market_screener import _passes_quality, _quote_to_candidate


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
    assert c["ticker"] == "TYGO" and c["source"] == "massive_screener"
    assert c["market_cap"] == 4.2e8 and c["sector"] == "Technology"


def test_discovery_blend_caps_megacaps_and_injects_screened():
    from agents.query_interpreter import blend_discovery_universe
    from agents.universe import MEGA_CAPS
    mega = {m.upper() for m in MEGA_CAPS}
    primary = ["MSFT", "GOOGL", "META", "ORCL", "CRM", "ADBE", "INTU", "NOW"]
    screened = ["RPAY", "TYGO", "ASYS", "RMNI", "PDYN"]
    out = blend_discovery_universe(primary, screened, keep_mega=2, target=8)
    assert len([t for t in out if t.upper() in mega]) <= 2      # mega-caps capped
    assert any(t in screened for t in out)                       # discoveries injected
    assert len(out) <= 8


def test_discovery_blend_pure_discovery_drops_all_megacaps():
    from agents.query_interpreter import blend_discovery_universe
    from agents.universe import MEGA_CAPS
    mega = {m.upper() for m in MEGA_CAPS}
    out = blend_discovery_universe(["AAPL", "MSFT"], ["RPAY", "TYGO", "ASYS"], keep_mega=0, target=6)
    assert not [t for t in out if t.upper() in mega]             # zero mega-caps
    assert set(out) <= {"RPAY", "TYGO", "ASYS"}


def test_screen_market_falls_back_to_curated_on_empty_universe(monkeypatch):
    # With no grouped tape (e.g. no key / non-trading window) the live screen
    # yields nothing and we fall back to the curated pool — never zero, never raises.
    import data.market_screener as ms
    monkeypatch.setattr(ms.massive_client, "grouped_daily", lambda *_a, **_k: [])
    out = ms.screen_market(sectors=["technology"], styles=[], exclude=[], cap=5)
    assert isinstance(out, list) and out
    assert all(c.get("source") == "curated_fallback" for c in out)
    assert all("ticker" in c for c in out)
