"""
T5 tests — the data-provided seam.

Proves the two guarantees: (1) in provided mode the wrapped backend clients
return supplied data and NEVER fetch — a missing datum raises FetchForbidden
rather than hitting the network; (2) a defense-in-depth network guard blocks
non-local DNS while a provided session is active. conftest puts backend/ on the
path so the real data clients are importable and wrapped.
"""

import socket

import pytest

from seam import (
    FetchForbidden,
    get_provided,
    install_seam,
    is_provided_mode,
    provided_session,
    uninstall_seam,
)


@pytest.fixture(autouse=True)
def _seam():
    install_seam()
    yield
    uninstall_seam()


def test_not_provided_mode_by_default():
    assert is_provided_mode() is False
    assert get_provided("fundamentals", "AAPL") is None


def test_provided_fundamentals_returned_without_fetch():
    from data.market_client import MarketDataClient

    data = {"fundamentals": {"AAPL": {"current_price": 191.2, "sector": "Technology"}}}
    with provided_session(data, guard_network=False):
        out = MarketDataClient().get_fundamentals("AAPL")
        assert out["current_price"] == 191.2
        assert out["sector"] == "Technology"


def test_missing_datum_raises_fetch_forbidden():
    from data.market_client import MarketDataClient

    # MSFT not supplied -> the wrapper must refuse, never fetch.
    with provided_session({"fundamentals": {"AAPL": {}}}, guard_network=False):
        with pytest.raises(FetchForbidden):
            MarketDataClient().get_fundamentals("MSFT")


def test_macro_snapshot_bucket_returned():
    from data.fred_client import FREDDataClient

    snap = {"vix": {"value": 18.0}, "yield_curve_spread": {"value": 0.5}}
    with provided_session({"macro_snapshot": snap}, guard_network=False):
        assert FREDDataClient().get_macro_snapshot() == snap


def test_price_history_keyed_by_ticker():
    from data.market_client import MarketDataClient

    bars = [{"date": "2026-05-01", "close": 10.0}, {"date": "2026-05-02", "close": 10.5}]
    with provided_session({"price_history": {"ASLE": bars}}, guard_network=False):
        assert MarketDataClient().get_price_history("ASLE") == bars


def test_network_guard_blocks_nonlocal_dns():
    with provided_session({}, guard_network=True):
        with pytest.raises(FetchForbidden):
            socket.getaddrinfo("example.com", 80)


def test_network_guard_allows_localhost():
    with provided_session({}, guard_network=True):
        # Should not raise — local addresses are permitted.
        socket.getaddrinfo("127.0.0.1", 80)


def test_context_resets_after_session():
    with provided_session({"fundamentals": {}}, guard_network=False):
        assert is_provided_mode() is True
    assert is_provided_mode() is False
    # And the network guard is torn down.
    socket.getaddrinfo("example.com", 80)
