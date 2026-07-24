# AI Tool Usage

## Tools I Used

- Cursor (Grok) for Story 0.1 scaffolding (requirements, config, `.env.example`)
- Cursor (Grok) for Story 0.2 docker-compose / Dockerfile / boot stubs
- Cursor (Grok) for Story 0.3 DB session/models + Redis queue client
- Cursor (Grok) for Story 1.1 submit job API (schemas, service, route, tests)
- Cursor (Grok) for Story 1.2 get job API
- Cursor (Grok) for Story 1.3 mock handlers + registry
- Cursor (Grok) for Story 1.4 worker claim + executor loop
- Cursor (Grok) for Story 1.5 DB feeder loop
- Cursor (Grok) for Story 2.1 priority processing tests
- Cursor (Grok) for Story 2.2 retry backoff
- Cursor (Grok) for Story 2.3 manual retry endpoint
- Cursor (Grok) for Story 2.4 job cancellation
- Cursor (Grok) for Story 2.5 idempotency
- Cursor (Grok) for Story 2.6 list jobs with filters

## What Helped Most

- Quickly drafting a pydantic-settings `Settings` class with docker-compose hostname defaults.
- Compose healthcheck + `depends_on` wiring so api/worker wait for postgres/redis.
- Mapping `schema.sql` enums/columns into SQLAlchemy 2.0 `Mapped` models.
- Wiring submit as DB-commit-then-Redis-enqueue so Postgres stays source of truth.

## What I Had to Fix

- Story 1.4: `app/worker.py` and `app/worker/` cannot coexist — moved the entrypoint to `app/worker/__main__.py` so `python -m app.worker` still works.

## What AI Struggled With

[Any parts where AI wasn't helpful]
