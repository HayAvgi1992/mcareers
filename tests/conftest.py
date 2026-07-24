"""Shared pytest fixtures. Env must be set before app imports.

Tests talk only to local/compose Postgres + Redis (defaults: 127.0.0.1;
compose injects service hostnames). Redis DB 15 isolates the test queue
from a live worker on DB 0.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

# Prefer env already injected by compose. For host runs, default to localhost
# so we don't pick up docker service hostnames from .env.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/mcareers",
)

# Tests dequeue from DB 15; worker on DB 0 cannot steal test queue entries.
_redis = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
_redis = re.sub(r"/\d+$", "", _redis.rstrip("/"))
os.environ["REDIS_URL"] = f"{_redis}/15"

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal, engine
from app.main import app, shutdown, startup
from app.queue.client import QueueClient
from app.queue.keys import JOBS_PENDING, JOBS_SCHEDULED
from app.worker.executor import process_one


@pytest.fixture(autouse=True)
async def _dispose_engine_between_loops() -> AsyncIterator[None]:
    """Avoid asyncpg 'Future attached to a different loop' across tests."""
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    await startup()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await shutdown()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def queue() -> AsyncIterator[QueueClient]:
    """QueueClient bound to the test Redis DB (for direct worker calls)."""
    q = await QueueClient.connect()
    try:
        yield q
    finally:
        await q.close()


@pytest.fixture
def worker_id() -> str:
    return "test-worker"


@pytest.fixture
def process_next(
    queue: QueueClient, worker_id: str
) -> Callable[[], Coroutine[Any, Any, bool]]:
    """
    Optional worker helper: run one executor tick without HTTP.
    Usage: ``assert await process_next() is True``
    """

    async def _run() -> bool:
        return await process_one(queue, worker_id=worker_id)

    return _run


@pytest.fixture
async def clean_jobs(redis_client: Redis) -> AsyncIterator[None]:
    """Clear jobs table and Redis dispatch ZSETs around a test."""
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE job_logs, jobs CASCADE"))
    await redis_client.delete(JOBS_PENDING, JOBS_SCHEDULED)
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE job_logs, jobs CASCADE"))
    await redis_client.delete(JOBS_PENDING, JOBS_SCHEDULED)
