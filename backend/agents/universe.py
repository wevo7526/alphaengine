"""
Default scan universe — the tickers the Screening Desk scans nightly.

Kept small to respect API limits. User watchlist tickers extend this at runtime.
"""

# Core benchmarks and sector ETFs — always scanned
SECTOR_ETFS = [
    "SPY",  # S&P 500
    "QQQ",  # Nasdaq
    "IWM",  # Russell 2000
    "TLT",  # Long bonds
    "GLD",  # Gold
    "XLF",  # Financials
    "XLK",  # Technology
    "XLE",  # Energy
    "XLV",  # Healthcare
    "XLI",  # Industrials
]

# Mega-cap single names — liquid, widely followed
MEGA_CAPS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "BRK-B", "JPM", "V",
    "UNH", "WMT", "JNJ", "XOM", "PG",
    "MA", "HD", "AVGO", "CVX", "MRK",
]

# Default universe — combined, deduplicated
DEFAULT_UNIVERSE = list(dict.fromkeys(SECTOR_ETFS + MEGA_CAPS))
