# AI Tool Usage

## Tools I Used

- Cursor (Grok) as the primary AI pair-programming assistant throughout the project.
- AI was used to generate initial implementations, boilerplate, test scaffolding, Docker configuration, documentation drafts, and alternative implementation ideas.
- Final architecture, distributed-system design, debugging, and code reviews remained manual.

---

## What Helped Most

AI provided the most value in repetitive engineering tasks:

- FastAPI endpoint scaffolding.
- SQLAlchemy model generation.
- Docker / Docker Compose setup.
- Redis and PostgreSQL client wrappers.
- Test scaffolding.
- Documentation drafting.
- Refactoring repetitive code.

These significantly accelerated implementation while still requiring manual review.

---

## What I Had to Fix

The majority of corrections were related to distributed-system design rather than syntax or implementation.

### PostgreSQL as the Source of Truth

AI occasionally treated Redis as part of the system state.

I intentionally kept PostgreSQL as the only source of truth, allowing Redis to be fully rebuilt by the feeder after failures.

---

### Preventing Duplicate Execution

I verified that Redis dequeue alone cannot prevent duplicate execution.

The final design became:

Redis dequeue

↓

Atomic PostgreSQL claim

↓

Execute only if claim succeeds

This guarantees that only one worker owns a job.

---

### Retry Scheduling

AI suggested workers could directly re-enqueue failed jobs.

I rejected this approach.

Workers only update PostgreSQL (`attempt_count`, `next_run_at`, `status`).

The feeder later promotes eligible jobs back into Redis.

---

### Worker Crash Recovery

The crash recovery flow required several design iterations.

The final solution became:

Lease

↓

Heartbeat

↓

Reaper

↓

Feeder

This allows crashed jobs to be safely recovered without relying on Redis state.

---

### Maintenance Separation

Initially executor and maintenance responsibilities lived in the same process.

While reasoning about horizontal scaling I separated them into:

- Worker (execution)
- Maintenance (Scheduler, Feeder, Reaper, Cleanup)

This prevents duplicated housekeeping when scaling workers.

---

### Simplicity over Abstraction

Several AI suggestions introduced unnecessary abstractions.

Examples included:

- Complex progress reporting interfaces.
- Generic handler wrappers.
- Over-engineered shutdown plumbing.

These were simplified to match the actual requirements.

---

## What AI Struggled With

AI consistently performed well on implementation but was much weaker in architectural reasoning.

Areas requiring manual engineering judgment included:

- Distributed-system tradeoffs.
- Concurrency correctness.
- Process ownership.
- Failure recovery.
- Long-term architectural consistency.
- Race condition analysis.
- Choosing simpler solutions over generic abstractions.

The final architecture was validated manually before implementation.