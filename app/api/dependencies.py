"""FastAPI dependency injectors."""

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.queue.client import QueueClient


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


def get_queue(request: Request) -> QueueClient:
    return request.app.state.queue
