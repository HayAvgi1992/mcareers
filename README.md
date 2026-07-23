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

## How to submit a test job (example request)

## Brief architecture overview
