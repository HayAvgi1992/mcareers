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

    # Max seconds a handler may run before the attempt is failed (retry/fail via DB).
    # Keep below worker_lease_seconds so the worker can finalize before the reaper.
    job_timeout_seconds: float = 30.0

    # How often the reaper scans for expired leases.
    reaper_poll_interval_seconds: float = 5.0

    # Idle sleep when the Redis pending queue is empty.
    executor_poll_interval_seconds: float = 0.5

    # Worker liveness for GET /health (Redis heartbeat ZSET).
    worker_heartbeat_interval_seconds: float = 5.0
    # Drop from "alive" if no beat within this window (keep > interval).
    worker_heartbeat_ttl_seconds: float = 15.0

    # Scheduler / feeder poll interval.
    scheduler_poll_interval_seconds: float = 1.0

    # How often maintenance nulls out idempotency keys older than 24h.
    idempotency_cleanup_interval_seconds: float = 3600.0

    # Default max attempts for new jobs (matches schema default).
    default_max_attempts: int = 3

    # Retry backoff after attempt N fails (before attempt N+1). Spec defaults.
    retry_backoff_after_attempt_1_seconds: float = 30.0
    retry_backoff_after_attempt_2_seconds: float = 120.0

    # Mock handler latencies (tune for demos / manual Phase 4 testing).
    email_mock_sleep_seconds: float = 0.5
    webhook_mock_sleep_seconds: float = 0.3
    report_mock_sleep_seconds: float = 1.0
    batch_item_sleep_seconds: float = 0.05


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
