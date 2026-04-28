"""
Hardcoded GICS sector mapping for the most-traded ~250 US tickers.

Why: Yahoo Finance's `info.sector` is unreliable — for a non-trivial fraction
of tickers it returns None or "Unknown", which silently disables sector-
concentration checks in the risk gate (you can stack 100% of the book in
"Unknown" without ever tripping the 30% cap). This map is the safety net.

Lookup order in `resolve_sector(ticker, yahoo_sector=...)`:
  1. If Yahoo gave a real sector (not None / not "Unknown" / not empty), use it.
  2. Else fall back to this hardcoded map.
  3. Else return "Unknown" — but the caller can now log/alert because they
     know the fallback was exhausted.

Sectors follow GICS Level 1 conventions (matches what Yahoo returns when it
does return a sector, so the two sources are interchangeable downstream).
"""

from __future__ import annotations

# GICS Level 1 sectors. Frozen for consistency.
SECTORS = (
    "Technology",
    "Communication Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Healthcare",
    "Financial Services",
    "Industrials",
    "Energy",
    "Utilities",
    "Real Estate",
    "Basic Materials",
)


# Hand-curated map. Covers S&P 100 + sector ETFs + the most-analyzed names.
# Keep tickers UPPERCASE for direct dict lookup.
_SECTOR_MAP: dict[str, str] = {
    # Mega-cap tech
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AVGO": "Technology", "ORCL": "Technology", "ADBE": "Technology",
    "CRM": "Technology", "AMD": "Technology", "INTC": "Technology",
    "CSCO": "Technology", "QCOM": "Technology", "TXN": "Technology",
    "IBM": "Technology", "MU": "Technology", "AMAT": "Technology",
    "NOW": "Technology", "PANW": "Technology", "INTU": "Technology",
    "ADI": "Technology", "LRCX": "Technology", "KLAC": "Technology",
    "SNPS": "Technology", "CDNS": "Technology", "MRVL": "Technology",
    "ANET": "Technology", "FTNT": "Technology", "CRWD": "Technology",
    "DDOG": "Technology", "SNOW": "Technology", "PLTR": "Technology",
    "NET": "Technology", "ZS": "Technology",
    # Communication Services
    "GOOGL": "Communication Services", "GOOG": "Communication Services",
    "META": "Communication Services", "NFLX": "Communication Services",
    "DIS": "Communication Services", "T": "Communication Services",
    "VZ": "Communication Services", "TMUS": "Communication Services",
    "CMCSA": "Communication Services", "CHTR": "Communication Services",
    "WBD": "Communication Services", "EA": "Communication Services",
    "ATVI": "Communication Services", "TTWO": "Communication Services",
    "ROKU": "Communication Services", "PINS": "Communication Services",
    "SNAP": "Communication Services", "SPOT": "Communication Services",
    # Consumer Cyclical
    "AMZN": "Consumer Cyclical", "TSLA": "Consumer Cyclical",
    "HD": "Consumer Cyclical", "MCD": "Consumer Cyclical",
    "NKE": "Consumer Cyclical", "LOW": "Consumer Cyclical",
    "SBUX": "Consumer Cyclical", "TJX": "Consumer Cyclical",
    "BKNG": "Consumer Cyclical", "ABNB": "Consumer Cyclical",
    "F": "Consumer Cyclical", "GM": "Consumer Cyclical",
    "RIVN": "Consumer Cyclical", "LCID": "Consumer Cyclical",
    "MAR": "Consumer Cyclical", "HLT": "Consumer Cyclical",
    "EBAY": "Consumer Cyclical", "ETSY": "Consumer Cyclical",
    "DASH": "Consumer Cyclical", "UBER": "Consumer Cyclical",
    "LYFT": "Consumer Cyclical", "CMG": "Consumer Cyclical",
    "YUM": "Consumer Cyclical", "ROST": "Consumer Cyclical",
    "DPZ": "Consumer Cyclical", "ORLY": "Consumer Cyclical",
    "AZO": "Consumer Cyclical", "DRI": "Consumer Cyclical",
    # Consumer Defensive
    "WMT": "Consumer Defensive", "PG": "Consumer Defensive",
    "COST": "Consumer Defensive", "KO": "Consumer Defensive",
    "PEP": "Consumer Defensive", "MO": "Consumer Defensive",
    "PM": "Consumer Defensive", "MDLZ": "Consumer Defensive",
    "CL": "Consumer Defensive", "TGT": "Consumer Defensive",
    "KMB": "Consumer Defensive", "GIS": "Consumer Defensive",
    "STZ": "Consumer Defensive", "KHC": "Consumer Defensive",
    "K": "Consumer Defensive", "HSY": "Consumer Defensive",
    "MNST": "Consumer Defensive", "KDP": "Consumer Defensive",
    "DG": "Consumer Defensive", "DLTR": "Consumer Defensive",
    "TSN": "Consumer Defensive", "SYY": "Consumer Defensive",
    # Healthcare
    "UNH": "Healthcare", "JNJ": "Healthcare", "LLY": "Healthcare",
    "PFE": "Healthcare", "ABBV": "Healthcare", "MRK": "Healthcare",
    "TMO": "Healthcare", "ABT": "Healthcare", "DHR": "Healthcare",
    "BMY": "Healthcare", "AMGN": "Healthcare", "CVS": "Healthcare",
    "CI": "Healthcare", "ELV": "Healthcare", "MDT": "Healthcare",
    "GILD": "Healthcare", "ISRG": "Healthcare", "VRTX": "Healthcare",
    "REGN": "Healthcare", "BIIB": "Healthcare", "MRNA": "Healthcare",
    "BNTX": "Healthcare", "ZTS": "Healthcare", "SYK": "Healthcare",
    "BSX": "Healthcare", "BDX": "Healthcare", "HUM": "Healthcare",
    "HCA": "Healthcare", "DXCM": "Healthcare", "EW": "Healthcare",
    "IDXX": "Healthcare",
    # Financial Services
    "BRK-A": "Financial Services", "BRK-B": "Financial Services",
    "JPM": "Financial Services", "V": "Financial Services",
    "MA": "Financial Services", "BAC": "Financial Services",
    "WFC": "Financial Services", "GS": "Financial Services",
    "MS": "Financial Services", "C": "Financial Services",
    "AXP": "Financial Services", "BLK": "Financial Services",
    "SCHW": "Financial Services", "PYPL": "Financial Services",
    "USB": "Financial Services", "PNC": "Financial Services",
    "TFC": "Financial Services", "COF": "Financial Services",
    "MET": "Financial Services", "PRU": "Financial Services",
    "AIG": "Financial Services", "CB": "Financial Services",
    "TRV": "Financial Services", "PGR": "Financial Services",
    "ALL": "Financial Services", "MMC": "Financial Services",
    "AON": "Financial Services", "ICE": "Financial Services",
    "CME": "Financial Services", "SPGI": "Financial Services",
    "MCO": "Financial Services", "MSCI": "Financial Services",
    "COIN": "Financial Services", "HOOD": "Financial Services",
    "SQ": "Financial Services", "AFRM": "Financial Services",
    # Industrials
    "BA": "Industrials", "GE": "Industrials", "CAT": "Industrials",
    "HON": "Industrials", "LMT": "Industrials", "RTX": "Industrials",
    "UPS": "Industrials", "DE": "Industrials", "ETN": "Industrials",
    "EMR": "Industrials", "GD": "Industrials", "NOC": "Industrials",
    "FDX": "Industrials", "WM": "Industrials", "CSX": "Industrials",
    "NSC": "Industrials", "UNP": "Industrials", "ITW": "Industrials",
    "MMM": "Industrials", "PH": "Industrials", "CMI": "Industrials",
    "PCAR": "Industrials", "ROK": "Industrials", "TT": "Industrials",
    "OTIS": "Industrials", "GEV": "Industrials", "RSG": "Industrials",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "SLB": "Energy", "EOG": "Energy", "PSX": "Energy",
    "MPC": "Energy", "VLO": "Energy", "OXY": "Energy",
    "WMB": "Energy", "PXD": "Energy", "HES": "Energy",
    "DVN": "Energy", "FANG": "Energy", "KMI": "Energy",
    "OKE": "Energy", "BKR": "Energy", "HAL": "Energy",
    # Utilities
    "NEE": "Utilities", "SO": "Utilities", "DUK": "Utilities",
    "AEP": "Utilities", "SRE": "Utilities", "D": "Utilities",
    "EXC": "Utilities", "XEL": "Utilities", "ED": "Utilities",
    "PEG": "Utilities", "AWK": "Utilities", "WEC": "Utilities",
    "ES": "Utilities", "EIX": "Utilities", "DTE": "Utilities",
    # Real Estate
    "PLD": "Real Estate", "AMT": "Real Estate", "EQIX": "Real Estate",
    "CCI": "Real Estate", "PSA": "Real Estate", "WELL": "Real Estate",
    "SPG": "Real Estate", "O": "Real Estate", "DLR": "Real Estate",
    "EQR": "Real Estate", "AVB": "Real Estate", "VTR": "Real Estate",
    "EXR": "Real Estate", "INVH": "Real Estate", "ESS": "Real Estate",
    "ARE": "Real Estate",
    # Basic Materials
    "LIN": "Basic Materials", "SHW": "Basic Materials",
    "APD": "Basic Materials", "ECL": "Basic Materials",
    "FCX": "Basic Materials", "NEM": "Basic Materials",
    "DOW": "Basic Materials", "DD": "Basic Materials",
    "PPG": "Basic Materials", "NUE": "Basic Materials",
    "STLD": "Basic Materials", "X": "Basic Materials",
    "VMC": "Basic Materials", "MLM": "Basic Materials",
    "CTVA": "Basic Materials", "MOS": "Basic Materials",
    "ALB": "Basic Materials", "CF": "Basic Materials",

    # Sector ETFs — map to their sector for clean concentration math
    "XLK": "Technology", "VGT": "Technology",
    "XLC": "Communication Services",
    "XLY": "Consumer Cyclical",
    "XLP": "Consumer Defensive",
    "XLV": "Healthcare", "VHT": "Healthcare",
    "XLF": "Financial Services", "KRE": "Financial Services",
    "XLI": "Industrials",
    "XLE": "Energy", "USO": "Energy", "XOP": "Energy", "OIH": "Energy",
    "XLU": "Utilities",
    "XLRE": "Real Estate", "VNQ": "Real Estate",
    "XLB": "Basic Materials", "GDX": "Basic Materials", "GLD": "Basic Materials",
    "TAN": "Energy", "ICLN": "Energy",  # clean energy ETFs

    # Broad-market and country/style ETFs — flagged as "ETF/Broad" so they
    # don't roll up into a single sector and silently breach the 30% cap.
    "SPY": "ETF/Broad", "VOO": "ETF/Broad", "IVV": "ETF/Broad",
    "QQQ": "ETF/Broad", "IWM": "ETF/Broad", "DIA": "ETF/Broad",
    "VTI": "ETF/Broad", "VEA": "ETF/Broad", "VWO": "ETF/Broad",
    "EFA": "ETF/Broad", "EEM": "ETF/Broad", "FXI": "ETF/Broad",
    "EWZ": "ETF/Broad", "RSX": "ETF/Broad", "INDA": "ETF/Broad",
    "MCHI": "ETF/Broad",
    "TLT": "ETF/Bond", "IEF": "ETF/Bond", "SHY": "ETF/Bond",
    "AGG": "ETF/Bond", "BND": "ETF/Bond", "HYG": "ETF/Bond",
    "LQD": "ETF/Bond", "TIP": "ETF/Bond",
    "VIX": "ETF/Vol", "VXX": "ETF/Vol", "UVXY": "ETF/Vol",
    "SVXY": "ETF/Vol",
}


def resolve_sector(ticker: str, yahoo_sector: str | None = None) -> tuple[str, str]:
    """
    Resolve a ticker to its sector. Returns (sector, source).

    Source values: "yahoo" | "fallback" | "unresolved"
    Callers should warn-log on "unresolved" so a coverage gap surfaces.
    """
    # Trust Yahoo if it returned a real sector
    if yahoo_sector and yahoo_sector.strip() and yahoo_sector.strip().lower() not in {"unknown", "n/a", "none"}:
        return yahoo_sector.strip(), "yahoo"

    if not ticker:
        return "Unknown", "unresolved"

    key = ticker.strip().upper()
    if key in _SECTOR_MAP:
        return _SECTOR_MAP[key], "fallback"

    return "Unknown", "unresolved"


def is_known(ticker: str) -> bool:
    """True if the ticker has a hardcoded mapping (cheap pre-flight check)."""
    return bool(ticker) and ticker.strip().upper() in _SECTOR_MAP
