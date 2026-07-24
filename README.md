# mcareers

Distributed background job processing system.

## How to run the project

```bash
cp .env.example .env
docker compose up --build
```

Services:

| Service  | Port | Notes                                      |
|----------|------|--------------------------------------------|
| api      | 8000 | FastAPI (`GET /` → `{"status":"ok"}`)      |
| worker   | —    | Background worker process                  |
| postgres | 5432 | DB `mcareers`; schema applied on first boot |
| redis    | 6379 | Dispatch queue                             |

`api` and `worker` load env from `.env` (docker-compose hostnames). For host-local processes, point `DATABASE_URL` / `REDIS_URL` at `localhost` instead.

## How to run tests

```bash
# Inside the running stack (uses compose service hostnames):
docker compose exec api python -m pytest -q

# Or on the host (Postgres + Redis on localhost):
pytest -q
```

## Manual smoke test (submit → DB → API)

With the stack running (`docker compose up --build`):

### 1. Submit a job

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"job_type":"email","payload":{"to":"user@example.com"},"priority":1}' | jq
```

Copy the `id` from the response.

### 2. Read it via API

```bash
curl -s http://localhost:8000/jobs/<JOB_ID> | jq
```

Expect `status: "completed"` within ~1s for `email` jobs (worker executor is running). Poll with:

```bash
curl -s http://localhost:8000/jobs/<JOB_ID> | jq '.status, .result'
```

### List jobs (filters + pagination)

```bash
curl -s 'http://localhost:8000/jobs?status=pending&job_type=email&limit=20&offset=0' | jq
```

### Schedule a job for later

```bash
curl -s -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d "{\"job_type\":\"email\",\"payload\":{\"to\":\"later@example.com\"},\"scheduled_at\":\"$(date -u -d '+2 minutes' +%Y-%m-%dT%H:%M:%SZ)\"}" | jq
```

Expect `status: "scheduled"`. The worker scheduler promotes it to `pending` when due (~1s latency).

### 3. Check Postgres

```bash
docker compose exec postgres \
  psql -U postgres -d mcareers \
  -c "SELECT id, job_type, status, priority, payload, created_at FROM jobs ORDER BY created_at DESC LIMIT 5;"
```

### 4. Check Redis queue (optional)

```bash
docker compose exec redis redis-cli ZRANGE jobs:pending 0 -1 WITHSCORES
```

Your job UUID should appear in `jobs:pending`.

## Brief architecture overview
