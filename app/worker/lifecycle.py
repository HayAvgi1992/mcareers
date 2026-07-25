"""Shared graceful-shutdown helpers for worker loops."""

from __future__ import annotations

import asyncio


async def wait_or_stop(stop: asyncio.Event, timeout: float) -> bool:
    """
    Wait up to ``timeout`` seconds, or until ``stop`` is set.
    Returns True if shutdown was requested.
    """
    if stop.is_set():
        return True
    if timeout <= 0:
        return stop.is_set() # return True if stop is set and False if not
    try:
        await asyncio.wait_for(stop.wait(), timeout=timeout) # return timeout error if timeout or True when stop is set
        return True
    except asyncio.TimeoutError:
        return stop.is_set()
