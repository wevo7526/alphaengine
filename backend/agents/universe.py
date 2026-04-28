"""
Default scan universe — the tickers the desk's tools fall back to when the
user query doesn't pin a specific name. Curated to cover broad asset class
exposure (equities, rates, credit, commodities, FX) so cross-asset analysis
and hedge construction have something to draw from.

Free-tier API budgets are tight, so we cap the size at ~80 tickers across
all buckets — anything wider would burn through Alpha Vantage / NewsAPI
within a single session.
"""

# Broad-market ETFs (US equity benchmarks)
BROAD_MARKET = [
    "SPY",   # S&P 500
    "QQQ",   # Nasdaq 100
    "IWM",   # Russell 2000 (small-cap)
    "DIA",   # Dow Jones
    "MDY",   # Mid-cap 400
    "VTI",   # Total US Market
]

# Sector ETFs — full GICS coverage
SECTOR_ETFS = [
    "XLK",   # Technology
    "XLC",   # Communication Services
    "XLY",   # Consumer Cyclical
    "XLP",   # Consumer Defensive
    "XLV",   # Healthcare
    "XLF",   # Financial Services
    "XLI",   # Industrials
    "XLE",   # Energy
    "XLU",   # Utilities
    "XLRE",  # Real Estate
    "XLB",   # Basic Materials
]

# Style / factor ETFs (used for FF5+Mom proxy + style tilts)
STYLE_ETFS = [
    "MTUM",  # Momentum
    "QUAL",  # Quality
    "USMV",  # Min-vol
    "IWD",   # Russell value
    "IWF",   # Russell growth
    "VLUE",  # Value factor
    "SIZE",  # Size factor
]

# International / EM equity
INTL_ETFS = [
    "EFA",   # Developed ex-US
    "VEA",   # Developed ex-US (Vanguard)
    "EEM",   # Emerging markets
    "VWO",   # Emerging markets (Vanguard)
    "FXI",   # China large-cap
    "MCHI",  # MSCI China
    "EWZ",   # Brazil
    "INDA",  # India
    "EWJ",   # Japan
]

# Rates / duration
RATES_ETFS = [
    "TLT",   # 20+ year treasuries
    "IEF",   # 7-10 year treasuries
    "SHY",   # 1-3 year treasuries
    "TIP",   # TIPS
    "BND",   # Total bond
    "AGG",   # Aggregate bond
]

# Credit — high-yield + IG
CREDIT_ETFS = [
    "HYG",   # iShares HY corporate
    "JNK",   # SPDR HY
    "LQD",   # Investment grade
    "EMB",   # EM bonds
]

# Commodities + precious metals
COMMODITY_ETFS = [
    "GLD",   # Gold
    "SLV",   # Silver
    "USO",   # Crude oil
    "UNG",   # Natural gas
    "DBC",   # Diversified commodities
    "GDX",   # Gold miners
    "GDXJ",  # Junior gold miners
    "URA",   # Uranium
    "LIT",   # Lithium
]

# FX — dollar + crosses
FX_ETFS = [
    "UUP",   # Long USD
    "FXE",   # Long EUR
    "FXY",   # Long JPY
    "FXB",   # Long GBP
    "CYB",   # Long CNY
]

# Vol / tail products
VOL_ETFS = [
    "VXX",   # VIX short-term futures
    "UVXY",  # 1.5x VIX
    "SVXY",  # Short VIX (-0.5x)
]

# Mega-cap single names — liquid, widely followed
MEGA_CAPS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "BRK-B", "JPM", "V",
    "UNH", "WMT", "JNJ", "XOM", "PG",
    "MA", "HD", "AVGO", "CVX", "MRK",
    "LLY", "ORCL", "COST", "BAC", "PEP",
]

# Mid / small-cap representatives — for less-crowded ideas
MID_SMALL_CAPS = [
    "IWM", "MDY", "VBR", "VBK",  # ETFs covering the broad universe
]

# Default scan universe — diversified across all asset classes.
# Deduplicated; preserves first-seen order for deterministic iteration.
DEFAULT_UNIVERSE = list(dict.fromkeys(
    BROAD_MARKET
    + SECTOR_ETFS
    + STYLE_ETFS
    + INTL_ETFS
    + RATES_ETFS
    + CREDIT_ETFS
    + COMMODITY_ETFS
    + FX_ETFS
    + VOL_ETFS
    + MEGA_CAPS
    + MID_SMALL_CAPS
))


def universe_by_class() -> dict[str, list[str]]:
    """Inspector helper — returns the universe organized by asset class."""
    return {
        "broad_market": list(BROAD_MARKET),
        "sectors": list(SECTOR_ETFS),
        "styles": list(STYLE_ETFS),
        "international": list(INTL_ETFS),
        "rates": list(RATES_ETFS),
        "credit": list(CREDIT_ETFS),
        "commodities": list(COMMODITY_ETFS),
        "fx": list(FX_ETFS),
        "vol": list(VOL_ETFS),
        "mega_caps": list(MEGA_CAPS),
        "mid_small": list(MID_SMALL_CAPS),
    }
