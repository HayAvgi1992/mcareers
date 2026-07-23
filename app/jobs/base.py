"""Job handler protocol and shared errors."""

from __future__ import annotations

from typing import Any, Protocol

from app.db.models import Job


class JobHandler(Protocol):
    async def run(self, job: Job) -> dict[str, Any]:
        """Execute the job and return a JSON-serializable result."""


class HandlerError(Exception):
    """Raised when a handler fails in a controlled way (e.g. webhook miss)."""


class UnknownJobTypeError(Exception):
    """Raised when no handler is registered for a job type."""
