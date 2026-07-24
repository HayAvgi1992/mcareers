# Session Rules

Guidelines for every implementation session. Start a **new session per story** from [PLAN.md](./PLAN.md). Paste or `@`-reference this file at the beginning of each session so context stays consistent.

---

## 1. Before You Write Code

1. **Pick one story** from `PLAN.md` (e.g. Story 1.4: Worker executor loop).
2. **State scope explicitly** — what is in and out for this session.
3. **Read first:**
   - [DECISIONS.md](./DECISIONS.md) — locked architecture
   - [app/db/schema.sql](./app/db/schema.sql) — data model
   - Relevant module boundaries in `PLAN.md` → Code Structure
4. **Do not** implement other stories, refactor unrelated code, or expand into should-haves unless the current story requires it.

---

## 2. Architecture Invariants (Never Break These)

These are locked. If a session needs to change one, stop and update `DECISIONS.md` first.

| Rule | Detail |
|------|--------|
| **Postgres is source of truth** | All job state, results, errors, idempotency live in DB. Redis is dispatch only. |
| **Postgres wins on conflict** | If Redis and DB disagree, trust DB. Drop stale Redis entries; feeder recovers from DB. |
| **Two-step job pickup** | Worker pops from Redis `jobs:pending`, then atomically claims in DB (`pending → processing`). Only the claim winner executes. |
| **Worker does not re-enqueue on failure** | On failure/retry: update DB only (`next_run_at`, `attempt_count`, `status=pending`). Feeder promotes back to Redis. |
| **Separate processes** | API never executes jobs. Worker never serves HTTP. |
| **Priority score** | `(-priority * 10^12) + created_at_epoch_ms` in Redis ZSET. |
| **Retry backoff** | Attempt 1: immediate · Attempt 2: 30s · Attempt 3: 2min · then permanent `failed`. |
| **Idempotency** | Duplicate key → `200` + `{ id, status }` only. No new row. No re-enqueue. New key → `201`. |
| **Manual retry** | Increment `max_attempts`, set `pending`, `next_run_at=now()`. Feeder enqueues. |
| **Module boundaries** | Routes → services → DB/queue. Handlers never touch DB/Redis. See `PLAN.md`. |

---

## 3. Logging (Required on Every State Transition)

Use **structured JSON logging** (structlog) once logging is set up (Story 3.4). Until then, use a consistent structured pattern that can be swapped to structlog later.

### Every log must include job context when a job is involved

```python
logger.info("job_claimed", job_id=str(job.id), job_type=job.job_type, status=job.status)
```

### Required log events

| Event | Level | When |
|-------|-------|------|
| `job_submitted` | info | API creates or returns existing job |
| `job_enqueued` | info | Job ID added to Redis pending |
| `job_claimed` | info | Worker wins DB claim |
| `job_started` | info | Handler execution begins |
| `job_completed` | info | Success; result stored |
| `job_failed` | warning/error | Handler error or permanent failure |
| `job_retry_scheduled` | info | Failure with retries remaining; log `next_run_at`, `attempt_count` |
| `job_cancelled` | info | Cancelled via API |
| `job_manual_retry` | info | Manual retry triggered |
| `job_claim_skipped` | debug | Redis pop but DB claim failed (stale/cancelled) |
| `job_feeder_promoted` | debug | Feeder enqueued job(s) from DB to Redis |
| `job_reaped` | info | Expired processing lease reset to pending |
| `job_schedule_promoted` | info | Scheduled job promoted to pending |

### Logging rules

- Log **state transitions**, not every loop iteration (avoid hot-loop noise).
- Include `job_id` on every job-related log line.
- Include `error` / `error_message` on failures.
- Never log full payloads or secrets — log `job_type` and payload size if needed.
- API errors: log `request_id` or path + status code.

---

## 4. Security Requirements

Apply on every session that touches input, handlers, or queue data.

- **Validate all input** with Pydantic schemas — job type, payload shape, priority bounds, timestamps.
- **Reject unknown `job_type`** at API and worker (defense in depth).
- **Never eval or exec** payload data. Handlers receive typed/parsed data only.
- **Sanitize error messages** stored on jobs — no stack traces with internal paths in API responses (logs are fine).
- **Guard against queue poisoning** — malformed payloads must fail the job gracefully, not crash the worker process. Wrap handler execution in try/except; uncaught exceptions → `failed` + log.
- **Idempotency keys** — validate length/format; reject empty strings.

---

## 5. Code Standards

- **Python 3.11+**, type hints on public functions.
- **Async** for FastAPI, SQLAlchemy async, redis.asyncio.
- **Minimal scope** — only files needed for the current story.
- **Match existing patterns** — read neighboring modules before adding code.
- **No over-abstraction** — no helpers for one-liners; no premature generic frameworks.
- **Comments** only for non-obvious distributed-systems logic (claim races, ordering guarantees).
- **Create files** per `PLAN.md` structure as needed — don't scaffold the whole tree upfront.

---

## 6. Testing Requirements (Per Session)

Every feature story must include or extend tests.

| Story type | Test expectation |
|------------|------------------|
| API endpoint | httpx test against FastAPI app |
| Worker logic | Test claim/feeder/retry **directly**, not only via HTTP |
| Job handler | Unit test handler in isolation with mock job object |
| Bug fix | Regression test |

### Test quality rules

- Assert **behavior**, not implementation details.
- Tests must be **isolated** — use test DB/Redis (conftest fixtures), no external services.
- Cover **happy path + one failure path** minimum per story.
- Required scenarios (by Phase 2 end): submission, completion, retry, cancellation, idempotency, priority — each in its own file under `tests/`.
- Tests must pass before the session ends: `pytest`

---

## 7. API Contract Reference

Follow these status codes and behaviors consistently.

| Endpoint | Success | Notes |
|----------|---------|-------|
| `POST /jobs` | `201` created · `200` duplicate | Duplicate returns `{ id, status }` only |
| `GET /jobs/{id}` | `200` · `404` | Include status, result, error, progress, timestamps |
| `GET /jobs` | `200` | Filter by `status`, `job_type`; paginate |
| `POST /jobs/{id}/cancel` | `200` · `404` · `409` | Pending (and scheduled later) only |
| `POST /jobs/{id}/retry` | `200` · `404` · `409` | Failed jobs only; increments `max_attempts` |
| `GET /health` | `200` · `503` | Should-have — DB + Redis + queue stats |

---

## 8. Documentation Updates (End of Session)

Before closing a session, update what changed:

| File | When to update |
|------|----------------|
| **PLAN.md** | Check off completed tasks / story acceptance criteria |
| **DECISIONS.md** | Any new architectural choice or change to locked decisions |
| **README.md** | New run instructions, env vars, example curl commands |
| **AI_USAGE.md** | Note what AI helped with and what you corrected (especially concurrency) |
| **app/db/schema.sql** | Any schema change + note migration approach |

Do **not** create new markdown files unless explicitly requested.

---

## 9. Session Exit Checklist

Before ending the session, confirm:

- [ ] Story scope completed — acceptance criteria from `PLAN.md` met
- [ ] Architecture invariants preserved (§2)
- [ ] State-transition logs added for new paths (§3)
- [ ] Input validation and handler error wrapping in place (§4)
- [ ] Tests written/updated and passing (§6)
- [ ] `PLAN.md` checkboxes updated (§8)
- [ ] `DECISIONS.md` / `README.md` / `AI_USAGE.md` updated if applicable (§8)
- [ ] No unrelated refactors or scope creep
- [ ] No secrets committed (`.env` stays gitignored)

---

## 10. What NOT To Do

- Don't commit unless explicitly asked.
- Don't push to remote unless explicitly asked.
- Don't implement should-haves during must-have stories.
- Don't have the worker push to Redis on failure (feeder only).
- Don't use Kafka or DB-only dequeue — stack is Postgres + Redis per `DECISIONS.md`.
- Don't process jobs inside API request handlers.
- Don't skip tests for "simple" features.
- Don't trust AI advice on concurrency without verifying against `DECISIONS.md`.

---

## 11. Suggested Session Prompt Template

Copy into each new session:

```
Implement PLAN.md Story X.X: [title]

Follow SESSION_RULES.md and DECISIONS.md.

In scope: [list]
Out of scope: [list]

When done: tests passing, PLAN.md updated, logs on state transitions.
```

---

## 12. Evaluation Dimensions (Keep in Mind)

Reviewers assess across these areas — each session should move at least one forward:

1. **Spec-driven development** — traceable to PLAN story; honest AI_USAGE
2. **Architecture** — clean separation, correct boundaries
3. **Security** — validation, safe payloads, no worker crashes on bad jobs
4. **Performance** — no DB hot loops on dequeue; efficient Redis ops
5. **Observability** — structured logs, diagnosable state transitions
6. **Tests** — meaningful, isolated, worker tested independently
