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
