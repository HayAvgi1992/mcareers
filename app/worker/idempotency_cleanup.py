"""Periodic cleanup of expired idempotency keys (maintenance process)."""

from __future__ import annotations

import asyncio

from app.config import settings
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.services.idempotency import cleanup_expired_idempotency_keys
from app.worker.lifecycle import wait_or_stop

logger = get_logger(__name__)


async def run_cleanup_once() -> int:
    """Open a session and null out keys older than the TTL. Returns rows updated."""
    async with SessionLocal() as session:
        cleared = await cleanup_expired_idempotency_keys(session)
    if cleared:
        logger.info("idempotency_keys_cleared", cleared=cleared)
    return cleared


async def run_idempotency_cleanup_loop(stop: asyncio.Event) -> None:
    """
    Periodically free idempotency keys older than 24h so clients can reuse them.
    Runs in the maintenance process (single replica).
    """
    logger.info("idempotency_cleanup_started")
    while not stop.is_set():
        try:
            await run_cleanup_once()
        except Exception:
            logger.exception("idempotency_cleanup_failed")
        await wait_or_stop(stop, settings.idempotency_cleanup_interval_seconds)
    logger.info("idempotency_cleanup_stopped")
