# Design Decisions

## 1. Job Pickup Strategy

**Approach chosen:** Redis priority pop + PostgreSQL conditional claim.

Workers pop the highest-priority job ID from the Redis `jobs:pending` ZSET, then atomically claim it in Postgres (`UPDATE ... WHERE id = ? AND status = 'pending'`). Only the worker that wins the DB claim executes the job. If the claim fails (cancelled, already taken, or not yet due), the worker discards the stale Redis entry and loops.

**Why:** Redis gives fast O(log N) priority dequeue; Postgres remains the source of truth for state, cancellation, and idempotency. The two-step pattern prevents duplicate execution under concurrent workers without relying on Redis alone.

**Trade-offs:** Two-step pickup adds a small latency vs Redis-only. We accept this in exchange for correctness when Redis and DB diverge. Postgres wins on any conflict.

---

## 2. Worker Crash Recovery

**Approach chosen:** Lease + reaper loop. On claim, the worker sets `leased_until = now + worker_lease_seconds`. A reaper periodically finds `status = processing AND leased_until < now()`, resets those rows to `pending` (clears `worker_id` / `leased_until`, sets `next_run_at = NULL`), and leaves Redis alone. The existing DB feeder then re-enqueues recovered jobs into `jobs:pending`.

**Why:** Postgres remains source of truth. If a worker dies mid-handler, the lease expires and another worker can claim the job without requiring Redis heartbeats or distributed locks. Keeping enqueue in the feeder avoids duplicate Redis push logic on the recovery path.

**What happens if worker crashes mid-job:** After `leased_until` passes, the reaper returns the job to `pending`. The feeder promotes it to Redis; a live worker claims and runs it again. `attempt_count` is not decremented (the crashed attempt already counted toward `max_attempts`).

---

## 3. Priority Queue Implementation

**Approach chosen:** Redis sorted set (`jobs:pending`) with composite score.

Score formula: `(-priority * 10^12) + created_at_epoch_ms` — higher priority first; FIFO within the same priority level.

**Why:** Native Redis ZSET ordering avoids a DB hot loop on dequeue. Priority is applied at dispatch time; the feeder preserves the same ordering when promoting jobs from Postgres to Redis.

---

## 4. Retry Backoff Strategy

**Approach chosen:** DB-driven retry scheduling (Option B). The worker does not re-enqueue to Redis on failure.

On failure the worker only updates Postgres: increment `attempt_count`, set `next_run_at` to the backoff delay, keep `status = 'pending'`. A feeder loop in the main worker process polls Postgres for ready jobs (`status = 'pending' AND (next_run_at IS NULL OR next_run_at <= now())`) and enqueues them to Redis. This keeps failure handling out of the execution path and centralizes queue promotion in one place.

Manual retry (`POST /jobs/{id}/retry`): increment `max_attempts`, set `status = 'pending'`, `next_run_at = now()`. The feeder picks it up on the next cycle.

**Timing:**
- Attempt 1: immediate (`next_run_at = NULL`)
- Attempt 2: 30 seconds after failure
- Attempt 3: 2 minutes after failure
- After `attempt_count >= max_attempts`: `status = 'failed'` permanently

---

## 5. One Thing I Would Do Differently With More Time

[Be honest — what did you skip or simplify?]
