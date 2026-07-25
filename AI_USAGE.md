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
- Cursor (Grok) for Story 2.7 core test suite
- Cursor (Grok) for Story 3.1 scheduled jobs
- Cursor (Grok) for Story 3.2 worker crash recovery (reaper)
- Cursor (Grok) for Story 3.3 health endpoint + queue stats
- Cursor (Grok) for Story 3.4 structured JSON logging
- Cursor (Grok) for Story 3.5 graceful shutdown
- Cursor (Grok) for Story 4.1 multiple concurrent workers
- Cursor (Grok) for splitting maintenance (feeder/scheduler/reaper) from worker
- Cursor (Grok) for Story 4.2 batch progress (implemented, then deferred/removed)
- Cursor (Grok) for Story 4.3 job timeout enforcement
- Cursor (Grok) for Story 5.1 README polish
- Cursor (Grok) for Story 5.2 DECISIONS.md §5 + stale-section fixes
- Cursor (Grok) for Story 5.3 AI_USAGE.md polish

## What Helped Most

- Quickly drafting a pydantic-settings `Settings` class with docker-compose hostname defaults.
- Compose healthcheck + `depends_on` wiring so api/worker wait for postgres/redis.
- Mapping `schema.sql` enums/columns into SQLAlchemy 2.0 `Mapped` models.
- Wiring submit as DB-commit-then-Redis-enqueue so Postgres stays source of truth.
- Scaffolding the two-step claim loop and feeder/reaper SQL from the locked decisions in `DECISIONS.md` / `SESSION_RULES.md`.
- Generating focused pytest scenarios (priority, retry, cancel, idempotency) once fixtures/`conftest` were solid.
- Rewriting README architecture text from the actual process layout (worker vs maintenance).

## What I Had to Fix

- Story 1.4: `app/worker.py` and `app/worker/` cannot coexist — moved the entrypoint to `app/worker/__main__.py` so `python -m app.worker` still works.
- Story 3.1: scheduler promote path once lost enqueue/logging after a refactor; restored single-session promote + Redis push.
- Story 3.5: AI added a `stop=` kwarg through `process_one`; we removed it — shutdown is loop-level (`while not stop.is_set()`), finish the in-flight job, then exit.
- Story 4.1: scaling `worker` also scaled feeder/scheduler/reaper until we split a dedicated `maintenance` process.
- Story 4.2: progress reporting grew into `HandlerSpec` / bind helpers; we deleted it and marked the story deferred.
- Story 2.7: first test pass was oversized (~60+); trimmed to a lean suite of the required scenarios (+ feeder tests kept on request).
- Tests: Redis DB **15** isolation so host pytest does not fight a live worker on DB 0.

## What AI Struggled With

- **Over-engineering when the prompt was vague.** Batch progress and graceful-shutdown wiring tended toward extra abstractions (registry wrappers, stop flags deep in the executor) that we later cut.
- **Keeping process boundaries straight.** Early drafts assumed feeder/reaper lived with the executor; scaling exposed that. AI followed the existing layout instead of questioning it until we noticed duplicate housekeeping.
- **Stale docs.** Partial edits left `AI_USAGE.md` / `DECISIONS.md` §4 describing the old “feeder in main worker” layout; needed an explicit pass to align docs with the maintenance split.
- **Regression risk on small refactors.** Scheduler and logging kwargs sometimes dropped a line (enqueue, structured fields) when AI “cleaned up” a loop — needed a careful re-read against acceptance criteria.
