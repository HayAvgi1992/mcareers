# Design Decisions

## 1. Job Pickup Strategy

**Decision:** Redis dispatch + PostgreSQL atomic claim.

Workers dequeue a job ID from Redis and then atomically claim ownership in PostgreSQL (`UPDATE ... WHERE status='pending'`).

**Why**

- Redis provides fast priority dispatch.
- PostgreSQL remains the source of truth.
- Atomic DB claim guarantees only one worker owns a job.

**Tradeoff**

Pickup requires both Redis and PostgreSQL, adding one extra database operation, but guarantees correctness even if Redis becomes stale.

---

## 2. Worker Crash Recovery

**Decision:** Lease + heartbeat + reaper.

Workers periodically renew a lease while processing a job. If a worker crashes, lease renewal stops. After the lease expires, the reaper moves the job back to `pending`, and the feeder re-enqueues it.

**Why**

- Detect crashed workers automatically.
- Recover unfinished jobs without manual intervention.
- Keep ownership in PostgreSQL rather than Redis.

**Tradeoff**

Recovery is eventual (up to one lease interval), not instantaneous.

---

## 3. Priority Queue

**Decision:** Redis Sorted Set.

Priority score:

```
(-priority × 10¹²) + created_at_epoch_ms
```

This guarantees:

- Higher priority jobs first.
- FIFO ordering within the same priority.

**Why**

Redis provides efficient O(log N) priority operations without polling PostgreSQL.

---

## 4. Retry Strategy

**Decision:** PostgreSQL-driven retries.

Workers never re-enqueue failed jobs directly.

On failure:

- Update `attempt_count`
- Set `next_run_at`
- Keep status `pending`

The feeder promotes ready jobs back into Redis.

**Why**

This centralizes retry scheduling in PostgreSQL and keeps Redis as a stateless dispatch layer.

---

## 5. Maintenance Separation

**Decision:** Separate executors from maintenance processes.

Workers execute jobs only.

A single maintenance process owns:

- Scheduler
- Feeder
- Reaper
- Idempotency cleanup

**Why**

Scaling workers should increase execution capacity only. Background maintenance should have a single owner to avoid duplicate housekeeping work.

---

## 6. Dead Letter Queue

**Decision:** Failed jobs remain in PostgreSQL and are also recorded in a Redis Dead Letter List.

**Why**

- PostgreSQL stores the complete failure state.
- Redis provides quick operational visibility of recent failures.

The Dead Letter Queue is for inspection only and never dispatches jobs.

---

## 7. Execution Semantics

The system provides **at-least-once** execution.

Duplicate execution is prevented during normal operation by the atomic PostgreSQL claim.

If a worker crashes after performing a side effect but before completing the transaction, the job may execute again after recovery. Handlers interacting with external systems should therefore be idempotent whenever possible.