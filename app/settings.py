"""Environment-driven configuration (pydantic-settings).

Every variable is documented in `.env.example` and `_docs/operations.md`
-> *Configuration*. The app runs with none of the optional ones set.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Default points at the Compose `db` service published on the host, so
    # `uv run uvicorn` and the integration tests work with no `.env`.
    database_url: str = "postgresql+psycopg://ciw:ciw@localhost:5432/ciw"
    # Seconds psycopg waits for a TCP connection before giving up. Keeps
    # `/api/health` answering fast while the database is unreachable.
    database_connect_timeout_seconds: int = 2

    # The worker claims alerts only when true; the app reports it on /api/health.
    agent_enabled: bool = False

    # Baked into the image from the APP_VERSION build argument; "dev" elsewhere.
    app_version: str = "dev"

    # Where the built SPA lives (produced by the Dockerfile; git-ignored).
    static_dir: Path = PACKAGE_DIR / "static"


@lru_cache
def get_settings() -> Settings:
    return Settings()
