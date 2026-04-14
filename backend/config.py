from pydantic_settings import BaseSettings
from pathlib import Path

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

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/alphaengine"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # App Config
    BACKEND_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    ENV: str = "development"

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
    }


settings = Settings()
