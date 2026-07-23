# AI Tool Usage

## Tools I Used

- Cursor (Grok) for Story 0.1 scaffolding (requirements, config, `.env.example`)
- Cursor (Grok) for Story 0.2 docker-compose / Dockerfile / boot stubs
- Cursor (Grok) for Story 0.3 DB session/models + Redis queue client
- Cursor (Grok) for Story 1.1 submit job API (schemas, service, route, tests)
- Cursor (Grok) for Story 1.2 get job API

## What Helped Most

- Quickly drafting a pydantic-settings `Settings` class with docker-compose hostname defaults.
- Compose healthcheck + `depends_on` wiring so api/worker wait for postgres/redis.
- Mapping `schema.sql` enums/columns into SQLAlchemy 2.0 `Mapped` models.
- Wiring submit as DB-commit-then-Redis-enqueue so Postgres stays source of truth.

## What I Had to Fix

[Describe 1-2 cases where AI gave incorrect advice — especially around concurrency]

## What AI Struggled With

[Any parts where AI wasn't helpful]
