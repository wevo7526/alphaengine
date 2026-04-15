"""
SEC EDGAR data client via sec-api.io

Provides access to SEC filings, full-text search, section extraction,
insider trading (Forms 3/4/5), and institutional holdings (13F).

Used primarily by the Fundamental Agent and Sentiment Agent.
"""

from sec_api import (
    QueryApi,
    FullTextSearchApi,
    ExtractorApi,
    InsiderTradingApi,
    Form13FHoldingsApi,
)
from datetime import datetime, timedelta, timezone
import logging

from config import settings

logger = logging.getLogger(__name__)


class SECDataClient:
    def __init__(self):
        api_key = settings.SEC_API_KEY
        self.query_api = QueryApi(api_key=api_key)
        self.fulltext_api = FullTextSearchApi(api_key=api_key)
        self.extractor_api = ExtractorApi(api_key=api_key)
        self.insider_api = InsiderTradingApi(api_key=api_key)
        self.holdings_api = Form13FHoldingsApi(api_key=api_key)

    # ── Filing Search ────────────────────────────────────────────

    def get_recent_filings(
        self,
        ticker: str,
        form_type: str = "8-K",
        limit: int = 10,
    ) -> dict:
        """
        Search recent filings by ticker and form type.

        Form types that matter for Alpha Engine:
          - 8-K:  Material events (earnings, M&A, exec changes, guidance)
          - 10-K: Annual report (full financials, MD&A, risk factors)
          - 10-Q: Quarterly report (interim financials, MD&A updates)
          - SC 13D/G: Activist/institutional stake disclosures
          - DEF 14A: Proxy statements (exec comp, governance)

        Returns raw sec-api.io response with filing metadata.
        """
        query = {
            "query": {
                "query_string": {
                    "query": f'ticker:"{ticker}" AND formType:"{form_type}"'
                }
            },
            "from": "0",
            "size": str(limit),
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        logger.info(f"Fetching {form_type} filings for {ticker} (limit={limit})")
        return self.query_api.get_filings(query)

    def get_filings_by_date_range(
        self,
        ticker: str,
        form_type: str = "8-K",
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
    ) -> dict:
        """
        Search filings within a specific date range.

        Useful for comparing quarter-over-quarter MD&A language,
        or pulling all filings since a catalyst event.
        """
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
        logger.info(
            f"Fetching {form_type} filings for {ticker} "
            f"from {start_date} to {end_date}"
        )
        return self.query_api.get_filings(query)

    # ── Full-Text Search ─────────────────────────────────────────

    def search_filings_fulltext(
        self,
        query_text: str,
        form_types: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """
        Full-text search across all SEC filings.

        This is where the real alpha is in filing analysis. Search for:
          - "going concern" → companies flagged by auditors as at-risk
          - "goodwill impairment" → write-downs signal deteriorating assets
          - "material weakness" → internal control failures
          - "restatement" → prior financials were wrong
          - "strategic alternatives" → company may be for sale
          - "covenant violation" → debt trouble

        The Fundamental Agent uses this to detect red flags that
        standard financial metrics miss. A company can look fine on
        P/E and still be hiding a going concern note in the 10-K.
        """
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
        return self.fulltext_api.get_filings(search_query)

    # ── Section Extraction ───────────────────────────────────────

    def extract_mda(self, filing_url: str) -> str:
        """
        Extract Management Discussion & Analysis (Item 7) from 10-K/10-Q.

        MD&A is where management explains the *why* behind the numbers.
        Changes in language between quarters are a leading indicator:
          - New hedging phrases ("challenging environment", "headwinds")
          - Removed growth language
          - Tone shifts from confident to cautious

        The Sentiment Agent compares MD&A across quarters to detect
        narrative shifts before they show up in the stock price.
        """
        logger.info(f"Extracting MD&A from {filing_url}")
        return self.extractor_api.get_section(filing_url, "7", "text")

    def extract_risk_factors(self, filing_url: str) -> str:
        """
        Extract Risk Factors (Item 1A) from 10-K/10-Q.

        Risk factor changes between filings are material signals:
          - New risk factors added = emerging threats
          - Risk factors removed = resolved issues
          - Language changes within existing factors = shifting severity

        The Fundamental Agent diffs risk factors across quarters.
        """
        logger.info(f"Extracting Risk Factors from {filing_url}")
        return self.extractor_api.get_section(filing_url, "1A", "text")

    def extract_financial_statements(self, filing_url: str) -> str:
        """
        Extract Financial Statements (Item 8) from 10-K.

        Raw financial statements — income statement, balance sheet,
        cash flow statement. Used by the Fundamental Agent for
        ratio analysis and earnings quality assessment.
        """
        logger.info(f"Extracting Financial Statements from {filing_url}")
        return self.extractor_api.get_section(filing_url, "8", "text")

    def extract_business_description(self, filing_url: str) -> str:
        """
        Extract Business Description (Item 1) from 10-K.

        Useful for understanding what the company actually does,
        its segments, competitive landscape, and revenue drivers.
        """
        logger.info(f"Extracting Business Description from {filing_url}")
        return self.extractor_api.get_section(filing_url, "1", "text")

    # ── Insider Trading ──────────────────────────────────────────

    def get_insider_trades(
        self,
        ticker: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> dict:
        """
        Get insider trading activity (Forms 3, 4, 5) for a ticker.

        Insider trading is one of the most reliable leading indicators:
          - Cluster buying (3+ insiders buying within 30 days) is strongly
            bullish — insiders know the business better than any analyst
          - CEO/CFO buying is weighted more heavily than director buying
          - Insider selling is noisier (diversification, taxes, etc.) but
            large programmatic sells outside of 10b5-1 plans are bearish
          - The $ amount matters more than the number of shares

        The Fundamental Agent looks for:
          1. Cluster detection: multiple insiders buying in a short window
          2. Role weighting: C-suite buys > director buys
          3. Context: buying after a price drop = conviction signal
          4. Pattern breaks: insiders who never buy suddenly buying
        """
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
        return self.insider_api.get_data(query)

    # ── 13F Institutional Holdings ───────────────────────────────

    def get_13f_holdings(
        self,
        cik: str,
        date: str | None = None,
    ) -> dict:
        """
        Get 13F institutional holdings for a specific filer (by CIK).

        13F filings reveal what the smart money is doing:
          - Bridgewater, Berkshire, Renaissance, etc. file quarterly
          - New positions = institutional conviction in a name
          - Increased positions = adding on thesis confirmation
          - Liquidated positions = thesis broken or profit-taking
          - Concentration changes = portfolio conviction shifts

        The 45-day filing delay means this data is lagged, but it
        reveals structural positioning that takes quarters to unwind.
        The Fundamental Agent uses this for:
          1. "Who owns this?" — institutional quality assessment
          2. Crowding risk — too many funds in the same name
          3. Position changes — are smart-money managers adding or cutting?
        """
        query = {
            "query": {
                "query_string": {
                    "query": f'cik:"{cik}"'
                }
            },
            "from": "0",
            "size": "1",
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        if date:
            query["query"]["query_string"]["query"] += (
                f' AND periodOfReport:"{date}"'
            )
        logger.info(f"Fetching 13F holdings for CIK {cik}")
        return self.holdings_api.get_data(query)

    def search_13f_for_ticker(
        self,
        ticker: str,
        limit: int = 20,
    ) -> dict:
        """
        Find which institutional filers hold a specific ticker.

        Reverse lookup — instead of "what does Bridgewater hold?",
        this answers "who holds AAPL?" Useful for assessing
        institutional ownership breadth and crowding.
        """
        query = {
            "query": {
                "query_string": {
                    "query": f'holdings.ticker:"{ticker}"'
                }
            },
            "from": "0",
            "size": str(limit),
            "sort": [{"filedAt": {"order": "desc"}}],
        }
        logger.info(f"Searching 13F filers holding {ticker}")
        return self.holdings_api.get_data(query)
