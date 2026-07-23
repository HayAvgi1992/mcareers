"""Map job_type → handler."""

from __future__ import annotations

from app.db.models import JobType
from app.jobs import batch, email, report, webhook
from app.jobs.base import JobHandler, UnknownJobTypeError

_HANDLERS: dict[JobType, JobHandler] = {
    JobType.email: email,
    JobType.webhook: webhook,
    JobType.report: report,
    JobType.batch: batch,
}


def get_handler(job_type: JobType | str) -> JobHandler:
    """Return the handler module for a job type, or raise UnknownJobTypeError."""
    if isinstance(job_type, str):
        try:
            job_type = JobType(job_type)
        except ValueError as exc:
            raise UnknownJobTypeError(f"unknown job_type: {job_type!r}") from exc

    handler = _HANDLERS.get(job_type)
    if handler is None:
        raise UnknownJobTypeError(f"unknown job_type: {job_type!r}")
    return handler
