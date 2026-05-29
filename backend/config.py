from pydantic_settings import BaseSettings
from pathlib import Path
import base64
import logging

logger = logging.getLogger(__name__)

# Resolve .env from project root (one level above backend/)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # LLM
    ANTHROPIC_API_KEY: str = ""

    # Model tiering (Cost Discipline — Build Plan). Bulk extraction /
    # classification routes to the cheap tier; final memo synthesis to the
    # reasoning tier. Env-overridable so model IDs can be corrected without
    # a code change. Defaults keep the historically-pinned synthesis model
    # so existing behavior is unchanged.
    LLM_MODEL_SYNTHESIS: str = "claude-sonnet-4-20250514"
    LLM_MODEL_EXTRACTION: str = "claude-haiku-4-5-20251001"
    LLM_MODEL_HEAVY: str = "claude-opus-4-8"
    # Toggle Anthropic prompt caching on large static system blocks. ~90% off
    # cache reads; harmless if the SDK ignores the cache_control marker.
    LLM_PROMPT_CACHE: bool = True

    # Phase 1 provenance pipeline (Build Plan): build a Fact Sheet, feed it to
    # the narration LLM with [[ev:n]] citation guidance, validate the memo
    # against it, and persist evidence receipts + claim links. Reversible
    # kill-switch — set false to fall back to the legacy citation-only path.
    PROVENANCE_PIPELINE: bool = True
    # When the validator finds orphan numbers post-narration, re-prompt the
    # narrator once to cite or remove them (hard-fail + auto-repair).
    PROVENANCE_AUTO_REPAIR: bool = True

    # Phase 2 filing NLP (Build Plan §2.1). OFF by default so development never
    # spends the scarce sec-api free-tier calls; flip on for a real run.
    # Strategy: Firecrawl scrapes the public filing HTML (heavy fetch), sec-api
    # is used only to resolve the latest/prior filing pair (1 call/ticker) and
    # as an extraction fallback. SEC_CALL_BUDGET is a hard per-process ceiling
    # so a runaway loop can't drain the quota; the evidence store caches each
    # filing section permanently (filings are immutable).
    FILING_NLP_ENABLED: bool = False
    FILING_NLP_LLM: bool = False          # run Haiku change-categorization pass
    FILING_NLP_FORM: str = "10-K"
    FILING_NLP_MAX_NAMES: int = 3         # cap names per memo run
    SEC_CALL_BUDGET: int = 25             # hard ceiling on live sec-api calls/process

    # Earnings-call transcript NLP (Build Plan §2.2) — Firecrawl-only, no
    # sec-api. OFF by default so dev doesn't spend Firecrawl credits.
    TRANSCRIPT_NLP_ENABLED: bool = False

    # Universe breadth — how many non-mega-cap candidates the desk actually
    # considers. Raised from the old 8/12 so the Strategist evaluates a wide
    # field of under-covered mid/small caps instead of coalescing on big names.
    # Prices are cached (1h) so repeated queries are cheap; first run fetches
    # up to STRATEGIST_PRICING_CAP quotes in parallel.
    SECONDARY_UNIVERSE_CAP: int = 50      # candidates the Interpreter surfaces
    STRATEGIST_PRICING_CAP: int = 50      # candidates priced + handed to the Strategist
    PRICING_MAX_WORKERS: int = 12
    PRICING_TIMEOUT_S: float = 30.0

    # Data Sources
    SEC_API_KEY: str = ""
    FRED_API_KEY: str = ""
    NEWS_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""
    ALPHA_VANTAGE_KEY: str = ""
    FIRECRAWL_API_KEY: str = ""

    # Clerk Auth.
    # CLERK_ISSUER and CLERK_SECRET_KEY are optional — if either CLERK_ISSUER
    # or CLERK_PUBLISHABLE_KEY (or NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) is set,
    # we derive the issuer URL and verify JWTs against Clerk's public JWKS.
    CLERK_ISSUER: str = ""
    CLERK_SECRET_KEY: str = ""
    CLERK_AUDIENCE: str = ""
    CLERK_PUBLISHABLE_KEY: str = ""
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: str = ""

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/alphaengine"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # App Config
    BACKEND_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    ENV: str = "development"
    CORS_ORIGINS: str = ""

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


def _derive_clerk_issuer(publishable_key: str) -> str:
    """
    Clerk publishable keys encode the FAPI hostname:
        pk_test_<base64(hostname$)>   →  https://<hostname>
        pk_live_<base64(hostname$)>   →  https://<hostname>
    Returns "" if the key is empty or malformed.
    """
    if not publishable_key:
        return ""
    for prefix in ("pk_test_", "pk_live_"):
        if publishable_key.startswith(prefix):
            try:
                encoded = publishable_key[len(prefix):]
                # Pad to a multiple of 4 for base64
                padding = (-len(encoded)) % 4
                decoded = base64.b64decode(encoded + "=" * padding).decode("ascii")
                host = decoded.rstrip("$").strip()
                if host:
                    return f"https://{host}"
            except Exception as e:
                logger.warning("Could not decode Clerk publishable key: %s", e)
            return ""
    return ""


settings = Settings()

# If CLERK_ISSUER isn't explicitly set, derive it from whichever publishable
# key is available. This mirrors how the frontend resolves its FAPI host.
if not settings.CLERK_ISSUER:
    pub_key = (
        settings.CLERK_PUBLISHABLE_KEY
        or settings.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
    )
    derived = _derive_clerk_issuer(pub_key)
    if derived:
        settings.CLERK_ISSUER = derived
        logger.info("Derived CLERK_ISSUER from publishable key: %s", derived)


REQUIRED_IN_PRODUCTION = ("ANTHROPIC_API_KEY", "CLERK_ISSUER")
RECOMMENDED = (
    "SEC_API_KEY", "FRED_API_KEY", "NEWS_API_KEY",
    "FINNHUB_API_KEY", "ALPHA_VANTAGE_KEY", "FIRECRAWL_API_KEY",
)


def validate_startup() -> list[str]:
    """
    Inspect required/recommended secrets at startup.

    Returns a list of fatal errors (empty = OK). Recommended-but-missing keys
    are logged as warnings so operators can see degraded capabilities without
    the app refusing to boot.
    """
    errors: list[str] = []

    if settings.ENV == "production":
        for key in REQUIRED_IN_PRODUCTION:
            if not getattr(settings, key, ""):
                errors.append(f"{key} is required in production but is empty")

    for key in RECOMMENDED:
        if not getattr(settings, key, ""):
            logger.warning(
                "Optional secret %s is not set — the dependent data source will be "
                "skipped and agents will degrade accordingly.", key,
            )

    return errors
