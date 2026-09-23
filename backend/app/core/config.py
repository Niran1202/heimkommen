from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = "development"

    # SQLite keeps local development dependency-free; Docker/production set a Postgres URL.
    database_url: str = f"sqlite:///{(REPO_ROOT / 'data' / 'heimkommen.db').as_posix()}"
    redis_url: str | None = None

    jwt_secret: str = "change-me-in-production"  # noqa: S105 - overridden via env in production
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    artifacts_dir: Path = REPO_ROOT / "ml" / "artifacts"
    data_dir: Path = REPO_ROOT / "data"

    # DB API Marketplace (Timetables API, free plan)
    db_api_base_url: str = "https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1"
    db_api_client_id: str = ""
    db_api_key: str = ""
    live_cache_seconds: int = 60

    timezone: str = "Europe/Berlin"
    default_transfer_minutes: int = 4
    simulator_runs: int = 2000
    max_journey_options: int = 4
    cors_origins: str = "*"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", case_sensitive=False, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
