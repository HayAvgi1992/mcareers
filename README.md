# mcareers

A distributed background job processing system for executing asynchronous tasks such as emails, webhooks, reports, and batch jobs.

The system supports:

- Priority scheduling
- Delayed (scheduled) execution
- Automatic retries with backoff
- Job cancellation
- Progress reporting
- Idempotent submissions
- Crash recovery
- Horizontal worker scaling

The architecture intentionally separates **durability** from **dispatch**:

- **PostgreSQL** is the **source of truth** and stores the complete job lifecycle.
- **Redis** is used only as a high-performance dispatch layer.
- Workers fetch job IDs from Redis, then atomically claim ownership in PostgreSQL to guarantee that only one worker executes a job at a time.

---

# Design Goals

The project was designed around the following goals:

- Keep PostgreSQL as the single source of truth.
- Allow horizontal scaling of workers.
- Recover automatically from crashes without losing jobs.
- Support priority-based scheduling.
- Support delayed execution.
- Prevent duplicate job submission through idempotency.
- Keep the operational model simple and deterministic.

---

# High-Level Architecture

```
                    +----------------+
                    |     Client     |
                    +----------------+
                             |
                             v
                     +----------------+
                     | FastAPI (API)  |
                     +----------------+
                       |            |
             write job |            | enqueue
                       |            |
                       v            v
              +----------------+   +----------------------+
              |   PostgreSQL   |   |        Redis         |
              | Source of Truth|   | Dispatch Queues      |
              +----------------+   +----------------------+
                       ^                    |
                       |                    |
             atomic claim                   |
                       |                    |
                 +-------------------------------+
                 |         Workers (N)           |
                 | Redis Pop -> DB Claim -> Run  |
                 +-------------------------------+

                +------------------------------+
                |        Maintenance           |
                |------------------------------|
                | Scheduler                    |
                | Feeder                       |
                | Reaper                       |
                | Idempotency Cleanup          |
                +------------------------------+
```

---

# Reliability Model

The system favors **correctness** and **recoverability** over maximum throughput.

Core guarantees:

- PostgreSQL is always the source of truth.
- Redis can be rebuilt from PostgreSQL.
- Workers never execute a job without first claiming it in PostgreSQL.
- Atomic DB claim prevents concurrent execution.
- Lease + heartbeat detect crashed workers.
- Feeder restores Redis if dispatch data is lost.
- Scheduled jobs are promoted only when due.
- Failed jobs retry using exponential backoff.
- Permanent failures are moved to a Dead Letter Queue.

The system provides **at-least-once execution semantics**.

Because a worker may crash after performing a side effect but before marking the job as completed, handlers interacting with external systems should be implemented in an idempotent manner whenever possible.

---

# Architecture Overview

```
Client
    |
    v
FastAPI API
    |
    +----------------------+
    |                      |
    v                      v
PostgreSQL            Redis Dispatch
(Source of Truth)     (Priority Queues)

           Maintenance
        -----------------
        Scheduler
        Feeder
        Reaper
        Cleanup

               |
               v

Workers (N replicas)

Redis POP
      ↓
Atomic DB Claim
      ↓
Handler
      ↓
Complete / Retry / Failed
```

---

# Core Design Decisions

- PostgreSQL owns the complete job lifecycle.
- Redis is treated as a recoverable dispatch layer.
- Workers never modify scheduling state directly.
- Maintenance responsibilities are isolated from workers.
- Job ownership is controlled exclusively through PostgreSQL.
- Failed workers are detected using leases and heartbeats.
- Retry scheduling happens only in PostgreSQL.
- Redis queues can always be reconstructed from database state.

---

# Prerequisites

- Docker + Docker Compose
- (Optional) Python 3.11+, local PostgreSQL and Redis

---

# How to Run

```bash
cp .env.example .env
docker compose up --build
```

| Service | Port | Purpose |
|---------|------|---------|
| api | 8000 | FastAPI HTTP API |
| worker | — | Executes jobs (safe to scale horizontally) |
| maintenance | — | Scheduler, feeder, reaper, cleanup (run one replica) |
| postgres | 5432 | Source of truth |
| redis | 6379 | Dispatch queues |

Scale workers:

```bash
docker compose up --build --scale worker=2
```

Stop:

```bash
docker compose down
```

---

# Running Tests

Inside Docker:

```bash
docker compose exec api python -m pytest -q
```

Host:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/mcareers

pytest -q
```

---

# Example Requests

Job types: `email`, `webhook`, `report`, `batch`. Batch jobs update `progress_pct` while processing; poll with `GET /jobs/<id>`.

### Submit a job

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_type":"email","payload":{"to":"user@example.com"},"priority":1}' | jq
```

### Poll status / result

```bash
curl -s http://localhost:8000/jobs/<JOB_ID> | jq '.status, .result, .progress_pct'
```

### Idempotent submit

Duplicate key → `200` with `{id, status}` only:

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: my-client-key-1' \
  -d '{"job_type":"email","payload":{"to":"user@example.com"}}' | jq
```

### List jobs

```bash
curl -s 'http://localhost:8000/jobs?status=pending&limit=20' | jq
```

### Cancel (pending or scheduled)

```bash
curl -s -X POST http://localhost:8000/jobs/<JOB_ID>/cancel | jq
```

### Manual retry (failed only)

```bash
curl -s -X POST http://localhost:8000/jobs/<JOB_ID>/retry | jq
```

### Schedule for later

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d "{\"job_type\":\"email\",\"payload\":{\"to\":\"later@example.com\"},\"scheduled_at\":\"$(date -u -d '+2 minutes' +%Y-%m-%dT%H:%M:%SZ)\"}" | jq
```

Expect `status: "scheduled"`. Maintenance promotes it to `pending` when due (~1s latency).

### Health (queue stats + live workers)

```bash
curl -s http://localhost:8000/health | jq
```

### Check Redis queue (optional)

```bash
docker compose exec redis redis-cli ZRANGE jobs:pending 0 -1 WITHSCORES
```

Your job UUID should appear in `jobs:pending`.

### Multiple workers (no duplicate execution)

Scale **workers** only; leave **maintenance** at one replica:

```bash
docker compose up --build --scale worker=2
```

Submit a burst:

```bash
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:8000/jobs \
    -H 'Content-Type: application/json' \
    -d "{\"job_type\":\"email\",\"payload\":{\"to\":\"u$i@example.com\"}}" >/dev/null
done
```

Check distinct `worker_id`s and single claims:

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

Expect each job `completed` with `attempt_count = 1` on the successful path.

---

# Current Limitations

This project intentionally keeps several production concerns out of scope:

- At-least-once execution (not exactly-once)
- Single maintenance instance (no leader election)
- Mock job handlers
- Local Docker deployment
- No authentication or authorization
- No metrics or distributed tracing

---

# Possible Future Improvements

- Kubernetes deployment
- Leader election for maintenance
- Prometheus metrics
- OpenTelemetry tracing
- S3 report storage
- Authentication
- Web dashboard
- Multi-tenant support

---

# Project Documentation

| File | Purpose |
|------|---------|
| PLAN.md | Build roadmap |
| DECISIONS.md | Architecture decisions and trade-offs |
| SESSION_RULES.md | Project conventions and development rules |
| AI_USAGE.md | AI usage and development process |
| app/db/schema.sql | Database schema |