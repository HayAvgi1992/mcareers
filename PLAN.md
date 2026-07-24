# Implementation Plan

Phased build plan for the job queue service. Must-haves first, then should-haves, then nice-to-haves.

**Stack:** Python 3.11+ · FastAPI · PostgreSQL · Redis · docker-compose

**Design reference:** [DECISIONS.md](./DECISIONS.md) · [app/db/schema.sql](./app/db/schema.sql)

**Session rules:** [SESSION_RULES.md](./SESSION_RULES.md) — follow for every story/session.

---

## Code Structure

Target layout and responsibility of each module. Create folders/files as you reach each story — don't scaffold everything upfront.

```
mcareers/
├── README.md
├── PLAN.md
├── DECISIONS.md
├── AI_USAGE.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
│
├── app/
│   ├── main.py                  # FastAPI app + startup/shutdown events + uvicorn entrypoint
│   ├── config.py                # Settings from env vars (DB URL, Redis URL, lease TTL, etc.)
│   │
│   ├── api/
│   │   ├── dependencies.py      # Inject DB session, Redis client
│   │   ├── schemas.py           # Pydantic: JobCreate, JobResponse, JobListParams, etc.
│   │   └── routes/
│   │       ├── jobs.py          # Submit, get, list, cancel, retry
│   │       └── health.py        # Health + queue stats (should-have)
│   │
│   ├── db/
│   │   ├── schema.sql           # DDL (source of truth for tables/indexes)
│   │   ├── session.py           # SQLAlchemy async engine + session factory
│   │   └── models.py            # ORM models: Job, JobLog
│   │
│   ├── queue/
│   │   ├── keys.py              # Redis key names + priority score helper
│   │   └── client.py            # Thin Redis wrapper: enqueue, dequeue, remove
│   │
│   ├── services/
│   │   ├── job_service.py       # API business logic (submit, get, list, cancel, retry)
│   │   └── idempotency.py       # Duplicate-key lookup + 24h cleanup helper
│   │
│   ├── worker/
│   │   ├── __main__.py          # Worker process entrypoint (`python -m app.worker`)
│   │   ├── feeder.py            # Poll DB → promote ready pending jobs to Redis
│   │   ├── claim.py             # Atomic DB claim (pending → processing + lease)
│   │   ├── executor.py          # Pop Redis → claim → run handler → finalize
│   │   ├── retry.py             # Backoff calculation + failure state updates
│   │   └── reaper.py            # Recover expired leases (should-have)
│   │
│   └── jobs/
│       ├── base.py              # JobHandler protocol / base class
│       ├── registry.py          # job_type → handler mapping
│       ├── email.py
│       ├── webhook.py
│       ├── report.py
│       └── batch.py
│
└── tests/
    ├── conftest.py              # Test DB, Redis, httpx client, worker helpers
    ├── test_submission.py
    ├── test_completion.py
    ├── test_retry.py
    ├── test_cancellation.py
    ├── test_idempotency.py
    └── test_priority.py
```

### Module boundaries

| Module | Owns | Must not |
|--------|------|----------|
| `api/routes` | HTTP validation, status codes, call services | Job execution, queue pop |
| `services/job_service` | Business rules, DB writes, enqueue on submit | Handler logic |
| `queue/client` | Redis ZSET operations | Business rules |
| `worker/feeder` | DB → Redis promotion | Execute jobs |
| `worker/executor` | Pop → claim → dispatch handler → finalize | HTTP |
| `worker/retry` | Backoff timing, attempt limits | Re-enqueue on failure |
| `jobs/*` | Mock job execution only | DB/Redis access |

### Redis keys

| Key | Type | Purpose |
|-----|------|---------|
| `jobs:pending` | ZSET | Ready jobs; score = priority composite |
| `jobs:scheduled` | ZSET | Future jobs (should-have); score = `run_at` epoch |

**Rule:** Postgres wins when Redis and DB disagree.

---

## Phases Overview

| Phase | Focus | Delivers |
|-------|-------|----------|
| **0** | Project skeleton | Runnable docker-compose, empty app boots |
| **1** | Core pipeline | Submit → enqueue → process → complete |
| **2** | Must-have features | Priority, retry, cancel, idempotency, tests |
| **3** | Should-haves | Scheduler, reaper, health, logging, graceful shutdown |
| **4** | Nice-to-haves | Multi-worker, batch progress, timeout, DLQ |
| **5** | Submission polish | README, DECISIONS, AI_USAGE |

---

## Phase 0 — Project Skeleton

### Story 0.1: Dependencies and configuration

**As a** developer  
**I want** pinned dependencies and env-based config  
**So that** API and worker share the same settings

**Tasks**
- [x] Fill `requirements.txt` (fastapi, uvicorn, sqlalchemy, asyncpg, redis, pydantic-settings, pytest, httpx, …)
- [x] Create `app/config.py` with `DATABASE_URL`, `REDIS_URL`, `WORKER_LEASE_SECONDS`, etc.
- [x] Add `.env.example`

**Acceptance criteria**
- [x] `from app.config import settings` loads from environment
- [x] Defaults work for local docker-compose hostnames

---

### Story 0.2: Docker Compose infrastructure

**As a** reviewer  
**I want** `docker-compose up` to start all services  
**So that** I can run the project without manual setup

**Tasks**
- [x] `docker-compose.yml`: postgres, redis, api, worker
- [x] `Dockerfile`: multi-stage or single image for api + worker (different commands)
- [x] Postgres init: run `schema.sql` on first boot
- [x] Healthchecks on postgres + redis

**Acceptance criteria**
- [x] `docker-compose up` starts 4 services
- [x] API responds on documented port
- [x] Tables exist in Postgres after startup

---

### Story 0.3: Database and Redis connectivity

**As a** developer  
**I want** shared DB session and Redis client modules  
**So that** API and worker use the same connection patterns

**Tasks**
- [x] `app/db/session.py` — async SQLAlchemy session
- [x] `app/db/models.py` — `Job`, `JobLog` ORM models matching `schema.sql`
- [x] `app/queue/client.py` — async Redis connection
- [x] `app/queue/keys.py` — key constants + `priority_score(priority, created_at)`

**Acceptance criteria**
- [x] API startup connects to DB and Redis
- [x] Worker startup connects to DB and Redis
- [x] ORM `Job` model matches schema columns

---

## Phase 1 — Core Pipeline (Happy Path)

### Story 1.1: Submit job API

**As a** client  
**I want** to submit a job via HTTP  
**So that** work is queued for async processing

**Tasks**
- [x] `app/api/schemas.py` — `JobCreate`, `JobResponse`
- [x] `app/api/routes/jobs.py` — `POST /jobs`
- [x] `app/services/job_service.py` — persist job (`status=pending`), enqueue to Redis
- [x] `app/main.py` — mount routes, `@app.on_event` startup/shutdown

**Acceptance criteria**
- [x] `POST /jobs` with `job_type` + `payload` returns `201` + job `id`
- [x] Job row exists in Postgres with `status=pending`
- [x] Job ID appears in Redis `jobs:pending` ZSET

---

### Story 1.2: Get job API

**As a** client  
**I want** to query job status and result  
**So that** I can track progress

**Tasks**
- [x] `GET /jobs/{id}` — return status, result, error, timestamps, progress

**Acceptance criteria**
- [x] Returns full job details for existing ID
- [x] Returns `404` for unknown ID

---

### Story 1.3: Job handler registry + mock handlers

**As a** worker  
**I want** to dispatch by `job_type`  
**So that** each job runs the correct logic

**Tasks**
- [x] `app/jobs/base.py` — handler interface (`async def run(job) -> result`)
- [x] `app/jobs/registry.py` — map type → handler
- [x] Implement `email`, `webhook`, `report`, `batch` handlers per spec (sleep, mock results, webhook 80/20)

**Acceptance criteria**
- [x] Each handler returns JSON result matching spec
- [x] Webhook fails ~20% of the time (deterministic seed in tests optional)
- [x] Unknown `job_type` raises clear error

---

### Story 1.4: Worker executor loop

**As a** system  
**I want** a worker that picks up and runs jobs  
**So that** submitted jobs complete

**Tasks**
- [x] `app/worker/claim.py` — `UPDATE … WHERE status=pending` + set lease
- [x] `app/worker/executor.py` — pop Redis → claim DB → run handler → mark completed
- [x] `app/worker/__main__.py` — start executor loop (`python -m app.worker`)

**Acceptance criteria**
- [x] Submitted job transitions: `pending → processing → completed`
- [x] Result stored in DB
- [x] `started_at` / `completed_at` populated

---

### Story 1.5: DB feeder loop

**As a** system  
**I want** a feeder that promotes DB-ready jobs to Redis  
**So that** retries and recovery don't require the executor to re-enqueue

**Tasks**
- [x] `app/worker/feeder.py` — query ready pending jobs, `ZADD jobs:pending`
- [x] Run feeder alongside executor in `worker.py`

**Acceptance criteria**
- [x] New submissions reach Redis even if not enqueued by API (recovery path)
- [x] Jobs with future `next_run_at` are not enqueued
- [x] Feeder respects priority ordering in ZSET score

---

## Phase 2 — Must-Have Features + Tests

### Story 2.1: Priority processing

**As a** client  
**I want** higher-priority jobs processed first  
**So that** urgent work isn't blocked

**Tasks**
- [x] Accept `priority` on submit (default 0)
- [x] Use composite ZSET score in enqueue
- [x] `tests/test_priority.py`

**Acceptance criteria**
- [x] Submit low then high priority; high completes first
- [x] Same priority → FIFO by `created_at`

---

### Story 2.2: Automatic retry with exponential backoff

**As a** system  
**I want** failed jobs retried with backoff  
**So that** transient failures recover without manual intervention

**Tasks**
- [x] `app/worker/retry.py` — backoff: 0s → 30s → 2min; max 3 attempts
- [x] On failure: worker updates DB only (`next_run_at`, `attempt_count`, `status=pending`)
- [x] Feeder picks up when `next_run_at <= now()`
- [x] `tests/test_retry.py`

**Acceptance criteria**
- [x] Webhook job retries on simulated failure
- [x] After 3 failures → permanent `failed`
- [x] Worker does **not** push to Redis on failure

---

### Story 2.3: Manual retry endpoint

**As a** client  
**I want** to retry a permanently failed job  
**So that** I can recover after fixing an upstream issue

**Tasks**
- [x] `POST /jobs/{id}/retry`
- [x] Increment `max_attempts`, set `pending`, `next_run_at=now()`

**Acceptance criteria**
- [x] Failed job can be retried manually
- [x] Non-failed job returns appropriate error
- [x] Feeder enqueues on next cycle

---

### Story 2.4: Job cancellation

**As a** client  
**I want** to cancel a pending job  
**So that** unnecessary work isn't processed

**Tasks**
- [x] `POST /jobs/{id}/cancel` (or `DELETE`)
- [x] DB: `pending → cancelled`; Redis: `ZREM`
- [x] `tests/test_cancellation.py`

**Acceptance criteria**
- [x] Pending job cancelled; worker claim fails if already popped
- [x] Processing/completed jobs cannot be cancelled
- [x] Cancelled job not executed

---

### Story 2.5: Idempotency

**As a** client  
**I want** duplicate submissions with the same key to return the existing job  
**So that** retries are safe

**Tasks**
- [ ] `app/services/idempotency.py`
- [ ] Accept optional `Idempotency-Key` header or body field
- [ ] `201` new · `200` duplicate → `{ id, status }` only
- [ ] No re-enqueue on duplicate
- [ ] `tests/test_idempotency.py`

**Acceptance criteria**
- [ ] Same key within 24h returns same job
- [ ] Duplicate does not create row or Redis entry
- [ ] Cleanup helper nulls keys older than 24h

---

### Story 2.6: List jobs with filters

**As a** client  
**I want** to list jobs filtered by status and type  
**So that** I can inspect the queue

**Tasks**
- [ ] `GET /jobs?status=&job_type=&limit=&offset=`

**Acceptance criteria**
- [ ] Filters work independently and combined
- [ ] Paginated response with total count

---

### Story 2.7: Core test suite

**As a** reviewer  
**I want** meaningful tests for required scenarios  
**So that** correctness is verifiable

**Tasks**
- [ ] `tests/conftest.py` — test DB, Redis, API client, optional worker fixture
- [ ] Complete `test_submission.py`, `test_completion.py`
- [ ] All 6 required test files pass in CI/local

**Acceptance criteria**
- [ ] ≥ 6 meaningful tests covering spec scenarios
- [ ] Worker logic tested independently of API (direct service/worker calls)
- [ ] Tests don't depend on external services outside test containers

---

## Phase 3 — Should-Haves

### Story 3.1: Scheduled jobs

**As a** client  
**I want** to schedule a job for future execution  
**So that** work runs at a specific time

**Tasks**
- [ ] Submit with `scheduled_at` → `status=scheduled`, `ZADD jobs:scheduled`
- [ ] Scheduler loop in worker (adaptive sleep, batch promote)
- [ ] Cancel scheduled jobs

**Acceptance criteria**
- [ ] Job not processed before `scheduled_at`
- [ ] Promoted to pending and enqueued when due
- [ ] Sub-second to ~1s scheduling latency

---

### Story 3.2: Worker crash recovery (reaper)

**As an** operator  
**I want** stuck processing jobs recovered  
**So that** worker crashes don't lose work

**Tasks**
- [ ] `app/worker/reaper.py` — reset expired leases → pending
- [ ] Feeder re-enqueues recovered jobs
- [ ] Fill in DECISIONS.md §2

**Acceptance criteria**
- [ ] Job with expired `leased_until` returns to pending
- [ ] Job eventually completes after recovery

---

### Story 3.3: Health endpoint + queue stats

**As an** operator  
**I want** a health endpoint with queue statistics  
**So that** I can monitor the system

**Tasks**
- [ ] `GET /health` — DB + Redis connectivity
- [ ] Queue depth, counts by status

**Acceptance criteria**
- [ ] Returns `200` when healthy, `503` when dependency down
- [ ] Includes pending/processing/failed counts

---

### Story 3.4: Structured JSON logging

**As an** operator  
**I want** logs with job context on state transitions  
**So that** I can trace job lifecycle

**Tasks**
- [ ] structlog setup with `job_id`, `job_type`, `status` on every transition

**Acceptance criteria**
- [ ] Submit, claim, complete, fail, retry, cancel all emit structured logs

---

### Story 3.5: Graceful shutdown

**As a** deployer  
**I want** workers to finish the current job before exit  
**So that** jobs aren't left mid-processing

**Tasks**
- [ ] SIGTERM handler; stop feeder/scheduler; drain executor

**Acceptance criteria**
- [ ] In-flight job completes before process exits
- [ ] No new jobs picked up after shutdown signal

---

## Phase 4 — Nice-to-Haves

### Story 4.1: Multiple concurrent workers

Run 2+ worker containers; verify no duplicate execution.

### Story 4.2: Batch job progress tracking

Update `progress_pct` during batch processing; expose via GET.

### Story 4.3: Job timeout enforcement

Mark job failed if processing exceeds configured timeout.

### Story 4.4: Dead letter queue

Move permanently failed jobs to a separate Redis list / DB flag for inspection.

---

## Phase 5 — Submission Polish

### Story 5.1: README

- [ ] How to run (`docker-compose up`)
- [ ] How to run tests
- [ ] Example curl for job submission
- [ ] Brief architecture overview

### Story 5.2: DECISIONS.md

- [ ] Complete all sections including §5 honest trade-off

### Story 5.3: AI_USAGE.md

- [ ] Tools used, what helped, what AI got wrong

---

## Recommended Build Order

```
0.1 → 0.2 → 0.3 → 1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 2.6 → 2.7
                                                                              ↓
                                        3.x (should-haves, any order) → 5.x (docs)
```

**First milestone (demo-able):** end of Phase 1 — submit a job, worker completes it, GET returns result.

**Must-have complete:** end of Phase 2 — all 6 tests green.

---

## API Contract (Reference)

| Method | Path | Phase | Notes |
|--------|------|-------|-------|
| `POST` | `/jobs` | 1.1 | 201 create · 200 idempotent duplicate |
| `GET` | `/jobs/{id}` | 1.2 | Status, result, error, progress |
| `GET` | `/jobs` | 2.6 | Filter by status, type |
| `POST` | `/jobs/{id}/cancel` | 2.4 | Pending only (scheduled in 3.1) |
| `POST` | `/jobs/{id}/retry` | 2.3 | Failed only; increments max_attempts |
| `GET` | `/health` | 3.3 | Should-have |

---

## Definition of Done (Must-Have)

- [ ] All Phase 0–2 stories complete
- [ ] `docker-compose up` runs API + worker + postgres + redis
- [ ] 6 test files pass
- [ ] DECISIONS.md §1, §3, §4 filled
- [ ] README sections drafted (can finalize in Phase 5)
