"""
Provided-data seam (backend): the full desk runs over supplied data and is
blocked from fetching commercial data.
"""

import pytest

from infra.provided_data import (
    FetchForbidden,
    install_provided_mode,
    is_provided_mode,
    provided_session,
    uninstall_provided_mode,
)


@pytest.fixture(autouse=True)
def _seam():
    install_provided_mode()
    yield
    uninstall_provided_mode()


def test_serves_provided_and_blocks_fetch():
    from data.market_client import MarketDataClient
    with provided_session({"fundamentals": {"AAPL": {"current_price": 191.2}}}):
        assert is_provided_mode() is True
        assert MarketDataClient().get_fundamentals("AAPL")["current_price"] == 191.2
        with pytest.raises(FetchForbidden):
            MarketDataClient().get_fundamentals("MSFT")
    assert is_provided_mode() is False


def test_macro_snapshot_served():
    from data.fred_client import FREDDataClient
    snap = {"vix": {"value": 18.0}}
    with provided_session({"macro_snapshot": snap}):
        assert FREDDataClient().get_macro_snapshot() == snap


def test_filings_blocked_when_not_provided():
    from data.sec_client import SECDataClient
    with provided_session({}):
        with pytest.raises(FetchForbidden):
            SECDataClient().get_recent_filings("AAPL")
