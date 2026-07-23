"""Shared settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Defaults match docker-compose service hostnames (Story 0.2).
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@postgres:5432/mcareers"
    )
    redis_url: str = "redis://redis:6379/0"

    # How long a worker holds a processing lease before a reaper may reclaim it.
    worker_lease_seconds: int = 60

    # Idle sleep when the Redis pending queue is empty.
    executor_poll_interval_seconds: float = 0.5

    # Scheduler poll interval when promoting ready pending jobs to Redis.
    scheduler_poll_interval_seconds: float = 1.0

    # Default max attempts for new jobs (matches schema default).
    default_max_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
