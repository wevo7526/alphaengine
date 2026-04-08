"""
Market data client via Yahoo Finance (yfinance).

No API key required. Provides price history, fundamentals, and options chains.
Used by the Fundamental Agent, Options Flow Agent, and Quant Strategist.

yfinance throttles around ~2000 requests/hour. We cache aggressively
since price data for a given ticker doesn't change within a session.
"""

import yfinance as yf
import time
import logging

logger = logging.getLogger(__name__)

# Cache TTL in seconds
_PRICE_TTL = 900       # 15 min — prices move, but agents don't need tick-level
_FUNDAMENTALS_TTL = 3600  # 1 hour — fundamentals update at most daily
_OPTIONS_TTL = 900     # 15 min — options chains shift intraday


class MarketDataClient:
    def __init__(self):
        self._price_cache: dict[str, tuple[float, list]] = {}
        self._fundamentals_cache: dict[str, tuple[float, dict]] = {}
        self._options_cache: dict[str, tuple[float, dict]] = {}

    def get_price_history(
        self,
        ticker: str,
        period: str = "6mo",
    ) -> list[dict]:
        """
        Fetch OHLCV price history for a ticker.

        Default is 6 months — enough for the Quant Agent to compute
        momentum signals (RSI, MACD, Bollinger) and the Options Agent
        to contextualize IV with realized vol, without over-fetching.

        Valid periods: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max
        """
        now = time.time()
        cache_key = f"{ticker}:{period}"
        if cache_key in self._price_cache:
            ts, data = self._price_cache[cache_key]
            if (now - ts) < _PRICE_TTL:
                logger.debug(f"Returning cached price history for {ticker}")
                return data

        stock = yf.Ticker(ticker)
        df = stock.history(period=period)

        result = [
            {
                "date": str(idx.date()),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            }
            for idx, row in df.iterrows()
        ]

        self._price_cache[cache_key] = (now, result)
        logger.info(f"Fetched {len(result)} price bars for {ticker} ({period})")
        return result

    def get_fundamentals(self, ticker: str) -> dict:
        """
        Get key fundamental metrics for a ticker.

        Returns a focused set of ratios the Fundamental Agent needs:
          - Valuation: P/E, forward P/E, P/B, EV/EBITDA
          - Profitability: margins, ROE, FCF
          - Growth: revenue growth
          - Risk: beta, debt/equity, short ratio
          - Context: sector, industry, 52-week range

        We pull .info once and extract what we need — this is a single
        API call, not 15 separate ones.
        """
        now = time.time()
        if ticker in self._fundamentals_cache:
            ts, data = self._fundamentals_cache[ticker]
            if (now - ts) < _FUNDAMENTALS_TTL:
                logger.debug(f"Returning cached fundamentals for {ticker}")
                return data

        stock = yf.Ticker(ticker)
        info = stock.info

        result = {
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "market_cap": info.get("marketCap"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margin": info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "free_cash_flow": info.get("freeCashflow"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "short_ratio": info.get("shortRatio"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        }

        self._fundamentals_cache[ticker] = (now, result)
        logger.info(f"Fetched fundamentals for {ticker}")
        return result

    def get_options_chain(
        self,
        ticker: str,
        expiry: str | None = None,
    ) -> dict:
        """
        Get options chain for a ticker at a given expiry.

        Returns calls and puts with strike, volume, OI, IV, bid/ask.
        Default is the nearest expiration — the most liquid and
        informative for detecting unusual activity.

        The Options Flow Agent uses this to:
          - Compute put/call ratio (sentiment gauge)
          - Detect unusual volume (volume/OI > 2x = notable)
          - Read IV skew (put IV vs call IV = directional fear)
          - Extract ATM straddle price (market-implied expected move)
        """
        now = time.time()
        cache_key = f"{ticker}:{expiry or 'nearest'}"
        if cache_key in self._options_cache:
            ts, data = self._options_cache[cache_key]
            if (now - ts) < _OPTIONS_TTL:
                logger.debug(f"Returning cached options chain for {ticker}")
                return data

        stock = yf.Ticker(ticker)
        expirations = stock.options

        if not expirations:
            return {"expirations": [], "calls": [], "puts": []}

        target = expiry or expirations[0]
        chain = stock.option_chain(target)

        # Only keep the columns agents actually need — don't serialize everything
        call_cols = ["strike", "lastPrice", "bid", "ask", "volume", "openInterest", "impliedVolatility"]
        put_cols = call_cols

        calls_df = chain.calls[call_cols] if all(c in chain.calls.columns for c in call_cols) else chain.calls
        puts_df = chain.puts[put_cols] if all(c in chain.puts.columns for c in put_cols) else chain.puts

        # Trim to 30 strikes nearest ATM to keep payload manageable for LLM context
        calls_list = calls_df.to_dict(orient="records")
        puts_list = puts_df.to_dict(orient="records")
        if len(calls_list) > 30:
            mid = len(calls_list) // 2
            calls_list = calls_list[mid - 15 : mid + 15]
        if len(puts_list) > 30:
            mid = len(puts_list) // 2
            puts_list = puts_list[mid - 15 : mid + 15]

        result = {
            "expiration": target,
            "all_expirations": list(expirations[:5]),  # Cap expiry list too
            "calls": calls_list,
            "puts": puts_list,
        }

        self._options_cache[cache_key] = (now, result)
        logger.info(f"Fetched options chain for {ticker} exp={target}")
        return result
