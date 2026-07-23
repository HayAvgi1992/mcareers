"""Redis key names and priority score helper."""

from __future__ import annotations

from datetime import datetime

# Dispatch ZSET: ready jobs. Score = priority_score(...).
JOBS_PENDING = "jobs:pending"

# Future jobs (should-have Story 3.1). Score = run_at epoch.
JOBS_SCHEDULED = "jobs:scheduled"

# Higher priority first; FIFO within same priority (DECISIONS.md §3).
_PRIORITY_SCALE = 10**12 # high number to ensure the priority is respected


def priority_score(priority: int, created_at: datetime) -> float:
    """Composite ZSET score: (-priority * 10^12) + created_at_epoch_ms."""
    created_at_epoch_ms = int(created_at.timestamp() * 1000)
    # negative priority to ensure the priority is respected - redis sorts by score in ascending order
    return (-priority * _PRIORITY_SCALE) + created_at_epoch_ms
