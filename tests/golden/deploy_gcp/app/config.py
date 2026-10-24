from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    # Connection pool of each process. Total connections = processes x (pool + overflow), which
    # must stay below the database's max_connections (see the deployment notes).
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    # true when a transaction-mode PgBouncer sits between the app and the database
    db_pgbouncer: bool = False
    log_level: str = "INFO"
    # JSON list in the environment, e.g. CORS_ORIGINS='["https://example.com"]'
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
