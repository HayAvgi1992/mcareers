"""Job handler protocol and shared errors."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from app.db.models import Job

# Mid-run progress callback used by batch (and any future progress-aware handler).
ProgressReporter = Callable[[int], Awaitable[None]]


class JobHandler(Protocol):
    async def run(self, job: Job) -> dict[str, Any]:
        """Execute the job and return a JSON-serializable result."""


class HandlerError(Exception):
    """Raised when a handler fails in a controlled way (e.g. webhook miss)."""


class UnknownJobTypeError(Exception):
    """Raised when no handler is registered for a job type."""
