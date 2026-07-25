# mcareers

Distributed background job processing system (Python / FastAPI / PostgreSQL / Redis).

Postgres is the **source of truth** for job state. Redis is a **dispatch** layer (`jobs:pending` / `jobs:scheduled` ZSETs). Workers pop from Redis, then atomically claim in Postgres so only one executor runs each job.

## Prerequisites

- Docker + Docker Compose
- (Optional, for host tests) Python 3.11+, local Postgres + Redis on `localhost`

## How to run

```bash
cp .env.example .env
docker compose up --build
```

| Service       | Port | Role |
|---------------|------|------|
| `api`         | 8000 | FastAPI HTTP API |
| `worker`      | —    | Job executor only (safe to scale) |
| `maintenance` | —    | Feeder + scheduler + reaper + idempotency cleanup (keep **one** replica) |
| `postgres`    | 5432 | Job state / results |
| `redis`       | 6379 | Priority dispatch queues |

`api`, `worker`, and `maintenance` load env from `.env` (docker-compose hostnames).

**Phase 4 demo timings:** the checked-in `.env` uses short backoffs / mock sleeps so you can exercise timeout, progress, and DLQ quickly (`report` sleeps 8s with a 5s timeout; batch items sleep 0.4s). Spec defaults are in `.env.example`. After changing `.env`, recreate: `docker compose up -d --scale worker=2 --force-recreate`.

Scale executors (do **not** scale `maintenance`):

```bash
docker compose up --build --scale worker=2
```

Stop:

```bash
docker compose down
```

## How to run tests

With the stack running (uses compose service hostnames inside the container):

```bash
docker compose exec api python -m pytest -q
```

On the host (Postgres + Redis on `127.0.0.1`; tests use Redis DB **15** so they do not collide with a live worker on DB 0):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/mcareers
pytest -q
```

## Example: submit a job

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_type":"email","payload":{"to":"user@example.com"},"priority":1}' | jq
```

Poll status / result:

```bash
curl -s http://localhost:8000/jobs/<JOB_ID> | jq '.status, .result, .progress_pct'
```

Idempotent submit (duplicate key → `200` with `{id, status}` only):

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-client-key-1' \
  -d '{"job_type":"email","payload":{"to":"user@example.com"}}' | jq
```

Other useful endpoints:

```bash
# List
curl -s 'http://localhost:8000/jobs?status=pending&limit=20' | jq

# Cancel (pending or scheduled)
curl -s -X POST http://localhost:8000/jobs/<JOB_ID>/cancel | jq

# Manual retry (failed only)
curl -s -X POST http://localhost:8000/jobs/<JOB_ID>/retry | jq

# Health + queue stats
curl -s http://localhost:8000/health | jq

# Schedule for later
curl -s -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d "{\"job_type\":\"email\",\"payload\":{\"to\":\"later@example.com\"},\"scheduled_at\":\"$(date -u -d '+2 minutes' +%Y-%m-%dT%H:%M:%SZ)\"}" | jq
```

Expect `status: "scheduled"`. The worker scheduler promotes it to `pending` when due (~1s latency).

Job types: `email`, `webhook`, `report`, `batch`.

Batch jobs update `progress_pct` while processing items; poll with `GET /jobs/<id>`.

### Health check

```bash
curl -s http://localhost:8000/health | jq
```

### Check Redis queue (optional)

```bash
docker compose exec redis redis-cli ZRANGE jobs:pending 0 -1 WITHSCORES
```

Your job UUID should appear in `jobs:pending`.

### Multiple workers (no duplicate execution)

Scale **workers** only; leave **maintenance** at one replica (it owns feeder/scheduler/reaper/cleanup):

```bash
docker compose up --build --scale worker=2
```

Submit a burst of jobs:

```bash
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:8000/jobs \
    -H 'Content-Type: application/json' \
    -d "{\"job_type\":\"email\",\"payload\":{\"to\":\"u$i@example.com\"}}" >/dev/null
done
```

Check that distinct `worker_id`s appear and each job is claimed once:

```bash
docker compose logs worker | grep job_claimed
```

```bash
docker compose exec postgres \
  psql -U postgres -d mcareers \
  -c "SELECT id, status, attempt_count, worker_id
      FROM jobs
      WHERE created_at > now() - interval '5 minutes'
      ORDER BY created_at DESC;"
```

Expect each job `completed` with `attempt_count = 1` (successful path).

## Brief architecture overview

```
Client → API (FastAPI)
           │
           ├─ write job row (Postgres)
           └─ ZADD jobs:pending or jobs:scheduled (Redis)

maintenance
  ├─ scheduler: due scheduled → pending + enqueue
  ├─ feeder:    ready pending rows → Redis (NX)
  ├─ reaper:    expired processing leases → pending
  └─ cleanup:   null idempotency keys older than 24h

worker (N replicas)
  └─ ZPOPMIN → DB claim (pending→processing) → handler (≤ JOB_TIMEOUT_SECONDS) → complete/fail
```

**Invariants**

- Postgres wins if Redis and DB disagree (stale Redis entries are dropped on failed claim).
- Workers do **not** re-enqueue on failure; they set `next_run_at` and the feeder promotes later.
- Priority score in Redis: `(-priority * 10^12) + created_at_epoch_ms` (higher priority first; FIFO within the same priority).
- Retry backoff: attempt 1 immediate · 2 → 30s · 3 → 2min · then permanent `failed`.
- Handler timeout (`JOB_TIMEOUT_SECONDS`, default 30) fails the attempt via the same retry path; keep it below `WORKER_LEASE_SECONDS`.
- Permanent failures: Postgres `status=failed` + Redis LIST `jobs:dead_letter` (inspection only; not dispatched). List failed jobs with `GET /jobs?status=failed`.

More detail: [DECISIONS.md](./DECISIONS.md). Session conventions: [SESSION_RULES.md](./SESSION_RULES.md).

## Project docs

| File | Purpose |
|------|---------|
| [PLAN.md](./PLAN.md) | Build stories / checklist |
| [DECISIONS.md](./DECISIONS.md) | Architecture trade-offs |
| [AI_USAGE.md](./AI_USAGE.md) | AI tooling notes |
| [app/db/schema.sql](./app/db/schema.sql) | Postgres schema |
