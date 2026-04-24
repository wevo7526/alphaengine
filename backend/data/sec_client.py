"""
SEC EDGAR data client via sec-api.io

Provides access to SEC filings, full-text search, section extraction,
insider trading (Forms 3/4/5), and institutional holdings (13F).

Used primarily by the Fundamental Agent and Sentiment Agent.

Stability notes:
  - The sec-api SDK is synchronous and makes HTTPS calls. All calls go
    through `run_sync_with_timeout` when invoked from async paths so
    one slow filing query can't park an event loop.
  - Per-call timeouts are capped at 30s — if SEC-API is slow, we surface
    that to the caller rather than hang.
  - All catches log with context so "Why is my filing search returning
    empty?" is answerable from logs, not a post-mortem.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sec_api import (
    ExtractorApi,
    Form13FHoldingsApi,
    FullTextSearchApi,
    InsiderTradingApi,
    QueryApi,
)

from config import settings
from infra.async_utils import run_sync_with_timeout

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0


class SECDataClient:
    def __init__(self):
        api_key = settings.SEC_API_KEY or ""
        self._configured = bool(api_key)
        if not self._configured:
            logger.debug("SEC_API_KEY not set — SECDataClient calls will return empty structures")
        # Construct APIs even without a key; calls will error but we handle it.
        self.query_api = QueryApi(api_key=api_key)
        self.fulltext_api = FullTextSearchApi(api_key=api_key)
        self.extractor_api = ExtractorApi(api_key=api_key)
        self.insider_api = InsiderTradingApi(api_key=api_key)
        self.holdings_api = Form13FHoldingsApi(api_key=api_key)

    def _empty_filings(self) -> dict:
        return {"total": {"value": 0, "relation": "eq"}, "filings": []}

    def _empty_insider(self) -> dict:
        return {"data": []}

    # ── Filing Search ────────────────────────────────────────────

    def get_recent_filings(self, ticker: str, form_type: str = "8-K", limit: int = 10) -> dict:
        if not self._configured:
            return self._empty_filings()
        query = {
            "query": {"query_string": {"query": f'ticker:"{ticker}" AND formType:"{form_type}"'}},
            "from": "0",
            "size": str(limit),
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        logger.info(f"Fetching {form_type} filings for {ticker} (limit={limit})")
        try:
            return self.query_api.get_filings(query) or self._empty_filings()
        except Exception as e:
            logger.warning(f"sec-api query failed for {ticker}/{form_type}: {e}")
            return self._empty_filings()

    def get_filings_by_date_range(
        self,
        ticker: str,
        form_type: str = "8-K",
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
    ) -> dict:
        if not self._configured:
            return self._empty_filings()
        if end_date is None:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if start_date is None:
            start_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        query = {
            "query": {
                "query_string": {
                    "query": (
                        f'ticker:"{ticker}" AND formType:"{form_type}" '
                        f'AND filedAt:[{start_date} TO {end_date}]'
                    )
                }
            },
            "from": "0",
            "size": str(limit),
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        logger.info(f"Fetching {form_type} filings for {ticker} {start_date}..{end_date}")
        try:
            return self.query_api.get_filings(query) or self._empty_filings()
        except Exception as e:
            logger.warning(f"sec-api date-range query failed: {e}")
            return self._empty_filings()

    # ── Full-Text Search ─────────────────────────────────────────

    def search_filings_fulltext(
        self,
        query_text: str,
        form_types: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        if not self._configured:
            return self._empty_filings()
        if end_date is None:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if start_date is None:
            start_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        search_query = {
            "query": query_text,
            "formTypes": form_types or ["10-K", "10-Q", "8-K"],
            "startDate": start_date,
            "endDate": end_date,
        }
        logger.info(f"Full-text search: '{query_text}' in {search_query['formTypes']}")
        try:
            return self.fulltext_api.get_filings(search_query) or self._empty_filings()
        except Exception as e:
            logger.warning(f"sec-api fulltext search failed: {e}")
            return self._empty_filings()

    # ── Section Extraction ───────────────────────────────────────

    def _extract_section(self, filing_url: str, section: str, label: str) -> str:
        if not self._configured:
            return ""
        try:
            result = self.extractor_api.get_section(filing_url, section, "text")
            return result or ""
        except Exception as e:
            logger.warning(f"sec-api {label} extract failed for {filing_url}: {e}")
            return ""

    def extract_mda(self, filing_url: str) -> str:
        logger.info(f"Extracting MD&A from {filing_url}")
        return self._extract_section(filing_url, "7", "MD&A")

    def extract_risk_factors(self, filing_url: str) -> str:
        logger.info(f"Extracting Risk Factors from {filing_url}")
        return self._extract_section(filing_url, "1A", "Risk Factors")

    def extract_financial_statements(self, filing_url: str) -> str:
        logger.info(f"Extracting Financial Statements from {filing_url}")
        return self._extract_section(filing_url, "8", "Financial Statements")

    def extract_business_description(self, filing_url: str) -> str:
        logger.info(f"Extracting Business Description from {filing_url}")
        return self._extract_section(filing_url, "1", "Business Description")

    # ── Insider Trading ──────────────────────────────────────────

    def get_insider_trades(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> dict:
        if not self._configured:
            return self._empty_insider()
        if end_date is None:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if start_date is None:
            start_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        query = {
            "query": {
                "query_string": {
                    "query": (
                        f'issuer.tradingSymbol:"{ticker}" '
                        f'AND filedAt:[{start_date} TO {end_date}]'
                    )
                }
            },
            "from": "0",
            "size": str(limit),
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        logger.info(f"Fetching insider trades for {ticker}")
        try:
            return self.insider_api.get_data(query) or self._empty_insider()
        except Exception as e:
            logger.warning(f"sec-api insider query failed: {e}")
            return self._empty_insider()

    # ── 13F Institutional Holdings ───────────────────────────────

    def get_13f_holdings(self, cik: str, date: str | None = None) -> dict:
        if not self._configured:
            return self._empty_insider()
        query = {
            "query": {"query_string": {"query": f'cik:"{cik}"'}},
            "from": "0",
            "size": "1",
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        if date:
            query["query"]["query_string"]["query"] += f' AND periodOfReport:"{date}"'
        logger.info(f"Fetching 13F holdings for CIK {cik}")
        try:
            return self.holdings_api.get_data(query) or self._empty_insider()
        except Exception as e:
            logger.warning(f"sec-api 13F query failed: {e}")
            return self._empty_insider()

    def search_13f_for_ticker(self, ticker: str, limit: int = 20) -> dict:
        if not self._configured:
            return self._empty_insider()
        query = {
            "query": {"query_string": {"query": f'holdings.ticker:"{ticker}"'}},
            "from": "0",
            "size": str(limit),
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        logger.info(f"Searching 13F filers holding {ticker}")
        try:
            return self.holdings_api.get_data(query) or self._empty_insider()
        except Exception as e:
            logger.warning(f"sec-api 13F ticker search failed: {e}")
            return self._empty_insider()

    # ── Async wrappers ────────────────────────────────────────────

    async def aget_recent_filings(self, ticker: str, form_type: str = "8-K", limit: int = 10) -> dict:
        try:
            return await run_sync_with_timeout(
                self.get_recent_filings, _DEFAULT_TIMEOUT, ticker, form_type, limit,
            )
        except TimeoutError:
            logger.warning(f"sec-api get_recent_filings timed out for {ticker}")
            return self._empty_filings()

    async def asearch_filings_fulltext(
        self,
        query_text: str,
        form_types: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        try:
            return await run_sync_with_timeout(
                self.search_filings_fulltext, _DEFAULT_TIMEOUT,
                query_text, form_types, start_date, end_date,
            )
        except TimeoutError:
            logger.warning(f"sec-api fulltext search timed out: {query_text}")
            return self._empty_filings()

    async def aget_insider_trades(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> dict:
        try:
            return await run_sync_with_timeout(
                self.get_insider_trades, _DEFAULT_TIMEOUT,
                ticker, start_date, end_date, limit,
            )
        except TimeoutError:
            logger.warning(f"sec-api insider trades timed out for {ticker}")
            return self._empty_insider()
