from pydantic_settings import BaseSettings
from pathlib import Path
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

    # Clerk Auth
    CLERK_ISSUER: str = ""  # e.g. https://your-app.clerk.accounts.dev
    CLERK_SECRET_KEY: str = ""
    CLERK_AUDIENCE: str = ""  # Optional: restrict JWT audience claim

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/alphaengine"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # App Config
    BACKEND_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    ENV: str = "development"
    CORS_ORIGINS: str = ""  # Comma-separated extra origins for production

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()


# Secrets whose absence is only logged (agents degrade gracefully) vs. those
# that MUST be present in production. Keep this list conservative — a missing
# ANTHROPIC_API_KEY means the product can't function; a missing NEWS_API_KEY
# degrades one signal source.
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
    the app refusing to boot. Fatal misconfigurations are logged as errors;
    the caller decides whether to exit (prod) or continue (dev).
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
