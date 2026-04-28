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

# Style / factor ETFs (used for FF5 + Momentum proxy + style tilts)
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


# ============================================================================
# SECONDARY (NON-MEGA-CAP) CANDIDATE POOL — by sector / theme
# ============================================================================
# Hand-curated mid/small-cap and second-tier large-cap candidates per sector.
# These are what the Research Analyst pulls from when the Interpreter assigns
# a sector or theme. Used to break mega-cap monoculture in the trade ideas.
# Quality filter: all are USD-listed, daily volume > 1M shares typical, real
# franchises (not penny stocks). Curated from S&P 400/600 + select theme leaders.

SECONDARY_BY_SECTOR: dict[str, list[str]] = {
    "Technology": [
        # Software - SaaS / platforms beyond MSFT/CRM
        "PLTR", "SNOW", "DDOG", "NET", "CRWD", "ZS", "PANW", "FTNT",
        "MDB", "TEAM", "WDAY", "NOW", "OKTA", "S", "SHOP", "SQ", "AFRM",
        # Semis beyond NVDA/AMD/AVGO
        "MU", "ANET", "MRVL", "QCOM", "TXN", "AMAT", "LRCX", "KLAC",
        "ON", "MCHP", "ENPH", "CDNS", "SNPS", "TER", "MPWR", "ASML",
        # Hardware / IT services
        "DELL", "HPQ", "NTAP", "STX", "WDC", "JNPR", "F5",
    ],
    "Communication Services": [
        # Telecoms beyond T/VZ
        "TMUS", "CHTR", "CMCSA", "LBRDA", "SIRI",
        # Media / streaming beyond NFLX
        "DIS", "PARA", "WBD", "ROKU", "FOXA", "NWSA",
        # Interactive / gaming
        "EA", "TTWO", "RBLX", "NTES", "PINS", "SNAP", "MTCH",
        # Ad-tech / smaller
        "TTD", "APP", "DV",
    ],
    "Consumer Cyclical": [
        # Retail beyond AMZN/HD
        "TGT", "LOW", "BBY", "DG", "DLTR", "ROST", "TJX", "ULTA", "ORLY", "AZO",
        "DKS", "GPS", "KSS", "M", "JWN", "BURL", "FIVE", "PVH", "RL", "TPR",
        # Restaurants / consumer brands
        "MCD", "SBUX", "CMG", "DPZ", "QSR", "WING", "DRI", "YUM",
        # Travel / leisure
        "BKNG", "MAR", "HLT", "ABNB", "NCLH", "RCL", "CCL", "EXPE",
        # Autos / EV beyond TSLA
        "GM", "F", "RIVN", "LCID", "NIO", "LI", "XPEV",
        # Homebuilders
        "DHI", "LEN", "PHM", "TOL", "NVR",
    ],
    "Consumer Defensive": [
        "WMT", "COST", "PG", "KO", "PEP", "MDLZ", "MO", "PM", "CL", "KMB",
        "GIS", "K", "HSY", "SJM", "CAG", "HRL", "STZ", "TAP", "TSN", "ADM",
        "KR", "SYY", "WBA", "CVS", "DEO",
    ],
    "Healthcare": [
        # Big pharma beyond JNJ/LLY/PFE
        "MRK", "ABBV", "BMY", "GILD", "AMGN", "REGN", "VRTX", "BIIB", "ALNY",
        # Biotech
        "MRNA", "BNTX", "INCY", "ILMN", "EXEL", "SGEN", "RPRX",
        # Devices / tools
        "TMO", "DHR", "ABT", "SYK", "MDT", "BSX", "EW", "ISRG", "BDX", "ZBH",
        "IDXX", "IQV", "A",
        # Insurers / managed care
        "UNH", "ELV", "CI", "HUM", "CNC", "MOH",
        # GLP-1 / obesity stack
        "NVO", "BHVN", "SMMT",
    ],
    "Financial Services": [
        # Banks beyond JPM/BAC
        "WFC", "C", "USB", "PNC", "TFC", "MTB", "FITB", "CFG", "RF", "KEY",
        "CMA", "ZION", "HBAN", "BPOP",
        # Investment banks / asset managers
        "GS", "MS", "BLK", "SCHW", "AXP", "BX", "KKR", "APO", "ARES", "BAM",
        "AMP", "TROW", "BEN",
        # Payments / fintech
        "V", "MA", "PYPL", "FI", "FIS", "GPN", "WU", "COIN", "HOOD", "SOFI",
        # Insurance
        "PGR", "ALL", "TRV", "CB", "AIG", "PRU", "MET", "AFL", "HIG", "CINF",
        # Exchanges / data
        "ICE", "CME", "MCO", "MSCI", "SPGI", "NDAQ",
    ],
    "Industrials": [
        # Defense / aerospace beyond LMT/NOC
        "GD", "RTX", "BA", "HII", "TXT", "TDG", "HEI", "CW", "LDOS",
        # Heavy machinery / construction
        "CAT", "DE", "PCAR", "PH", "ETN", "EMR", "ROK", "DOV",
        # Transports
        "UNP", "CSX", "NSC", "ODFL", "JBHT", "CHRW", "EXPD", "FDX", "UPS",
        "LUV", "DAL", "UAL", "AAL", "ALK",
        # Industrials / engineering
        "HON", "MMM", "GE", "ITW", "CMI", "PWR", "URI", "RSG", "WM",
    ],
    "Energy": [
        # Majors beyond XOM/CVX
        "COP", "EOG", "PSX", "VLO", "MPC", "OXY", "DVN", "FANG", "PXD", "HES",
        "MRO", "APA", "CTRA", "OVV",
        # Services / equipment
        "SLB", "HAL", "BKR", "FTI", "NOV", "TDW",
        # Midstream
        "KMI", "WMB", "OKE", "ET", "EPD", "MPLX", "TRGP",
        # Renewables / nuclear / battery
        "NEE", "FSLR", "ENPH", "SEDG", "RUN", "PLUG", "BE", "BLDP",
        "CCJ", "URA", "UEC",
    ],
    "Utilities": [
        "NEE", "DUK", "SO", "AEP", "D", "EXC", "XEL", "ED", "PEG", "WEC",
        "ES", "SRE", "EIX", "AWK", "DTE", "AEE", "PPL", "PNW", "CMS", "ETR",
    ],
    "Real Estate": [
        "PLD", "AMT", "CCI", "EQIX", "PSA", "WELL", "SPG", "O", "DLR", "AVB",
        "EQR", "VTR", "EXR", "MAA", "ESS", "UDR", "INVH", "ARE", "BXP", "VNO",
        "REG", "FRT", "KIM",
    ],
    "Basic Materials": [
        # Chemicals
        "LIN", "APD", "SHW", "ECL", "DD", "DOW", "PPG", "RPM", "ALB", "FMC",
        # Metals & mining
        "FCX", "NEM", "NUE", "STLD", "X", "CLF", "AA", "MP", "TECK", "RIO", "BHP",
        # Containers / paper
        "IP", "WRK", "BALL", "PKG", "AMCR",
    ],
}


# Theme-driven secondary candidates. Used when the Interpreter detects a theme
# that doesn't map cleanly to one sector (e.g., "AI capex" spans semis +
# software + utilities for power; "energy transition" spans materials + utilities + industrials).
SECONDARY_BY_THEME: dict[str, list[str]] = {
    "ai_capex": ["VRT", "ETN", "EATON", "PWR", "DELL", "ANET", "VST", "TLN", "CEG", "NRG", "SMCI", "MU"],
    "ai_inference": ["MRVL", "AVGO", "QCOM", "AMD", "MU", "VRT", "ANET", "CRWD", "PLTR"],
    "ai_software": ["PLTR", "SNOW", "DDOG", "NET", "CRWD", "PANW", "MDB", "S", "AI"],
    "energy_transition": ["VST", "TLN", "CEG", "NEE", "FSLR", "ENPH", "ALB", "MP", "TECK", "URA", "CCJ"],
    "obesity_glp1": ["LLY", "NVO", "BHVN", "SMMT", "REGN", "VKTX", "AMGN"],
    "cybersecurity": ["CRWD", "PANW", "ZS", "FTNT", "S", "OKTA", "CYBR", "RPD", "TENB"],
    "biotech_innovation": ["VRTX", "REGN", "BIIB", "ALNY", "MRNA", "EXEL", "INCY", "BMRN", "BLUE", "ARWR"],
    "fintech_disruptors": ["SQ", "AFRM", "SOFI", "HOOD", "COIN", "PYPL", "NU", "MELI", "PAGS"],
    "cloud_software": ["NOW", "WDAY", "TEAM", "DDOG", "SNOW", "MDB", "OKTA", "ZS", "FTNT"],
    "semiconductors": ["NVDA", "AMD", "AVGO", "MU", "MRVL", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "ON", "MCHP", "MPWR", "ENPH", "QCOM", "TXN"],
    "ev_supply_chain": ["ALB", "LIT", "TSLA", "RIVN", "LCID", "NIO", "LI", "XPEV", "MP", "BLDP", "ENPH"],
    "uranium_nuclear": ["CCJ", "UEC", "URA", "NXE", "UUUU", "DNN", "VST", "TLN", "CEG"],
    "data_centers_power": ["VRT", "ETN", "PWR", "VST", "TLN", "CEG", "NRG", "EQIX", "DLR"],
    "consumer_quality_value": ["TJX", "COST", "ROST", "DG", "DLTR", "ULTA", "WMT", "AZO", "ORLY"],
    "healthcare_value": ["UNH", "JNJ", "PFE", "ABBV", "BMY", "MRK", "CVS"],
    "regional_banks": ["MTB", "FITB", "CFG", "RF", "KEY", "HBAN", "ZION", "CMA", "PNC", "USB"],
    "oil_services": ["SLB", "HAL", "BKR", "FTI", "NOV", "TDW", "WHD"],
    "homebuilders": ["DHI", "LEN", "PHM", "TOL", "NVR", "KBH", "MTH"],
    "small_cap_quality": ["IWM", "VBR", "VBK", "AVUV", "CALF"],
}


def secondary_candidates(
    sectors: list[str] | None = None,
    themes: list[str] | None = None,
    exclude: list[str] | None = None,
    cap: int = 12,
) -> list[str]:
    """
    Return up to `cap` non-mega-cap candidates that aren't already in `exclude`.
    Pulls from sector and theme buckets, deduplicates, and de-prioritizes
    mega-caps (which the Interpreter has likely already named in `tickers`).
    """
    excluded = set((t or "").upper() for t in (exclude or []))
    excluded |= set(MEGA_CAPS)  # Always remove mega-caps from secondary pool by default

    out: list[str] = []
    seen = set()

    def _add(tk: str) -> None:
        u = tk.upper()
        if u in excluded or u in seen:
            return
        seen.add(u)
        out.append(u)

    # Themes are more specific, prefer them first
    for t in themes or []:
        key = (t or "").lower().strip().replace(" ", "_").replace("-", "_")
        if key in SECONDARY_BY_THEME:
            for tk in SECONDARY_BY_THEME[key]:
                if len(out) >= cap:
                    return out
                _add(tk)

    for s in sectors or []:
        if s in SECONDARY_BY_SECTOR:
            for tk in SECONDARY_BY_SECTOR[s]:
                if len(out) >= cap:
                    return out
                _add(tk)

    return out
