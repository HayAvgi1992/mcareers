"""Shared pytest fixtures. Env must be set before app imports."""

from __future__ import annotations

import os

# Prefer env already injected by compose. For host runs, default to localhost
# so we don't pick up docker service hostnames from .env.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/mcareers",
)
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.main import app, shutdown, startup
from app.queue.keys import JOBS_PENDING


@pytest.fixture(autouse=True)
async def _dispose_engine_between_loops() -> None:
    """Avoid asyncpg 'Future attached to a different loop' across tests."""
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncClient:
    await startup()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await shutdown()


@pytest.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def redis_client() -> Redis:
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def clean_jobs(redis_client: Redis) -> None:
    """Clear jobs table and pending ZSET around a test."""
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE job_logs, jobs CASCADE"))
    await redis_client.delete(JOBS_PENDING)
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE job_logs, jobs CASCADE"))
    await redis_client.delete(JOBS_PENDING)
