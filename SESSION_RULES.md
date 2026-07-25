# SESSION_RULES.md

# Session Rules

This document defines the rules that must be followed during every implementation session.

Each session should focus on **one story only** from `PLAN.md`.

---

# 1. Before Writing Code

Before implementing anything:

1. Choose a single story from `PLAN.md`.
2. Clearly state:
   - **In scope**
   - **Out of scope**
3. Read:
   - `PLAN.md`
   - `DECISIONS.md`
   - `app/db/schema.sql` (if DB related)
4. Do not implement future stories or unrelated refactors.

---

# 2. Architecture Invariants

These rules are locked.

If one of them must change, update `DECISIONS.md` first.

| Rule | Description |
|------|-------------|
| PostgreSQL is the Source of Truth | All job state lives in PostgreSQL. |
| Redis is dispatch only | Redis can always be rebuilt from PostgreSQL. |
| PostgreSQL wins on conflicts | Ignore stale Redis state. |
| Two-step job pickup | Redis dequeue → PostgreSQL atomic claim. |
| Atomic claim controls ownership | Only the worker that successfully claims executes the job. |
| Retries are DB-driven | Workers never re-enqueue failed jobs directly. |
| Separate responsibilities | API accepts requests. Workers execute jobs. Maintenance owns Scheduler, Feeder, Reaper and Cleanup. |
| Handlers are isolated | Handlers never access PostgreSQL or Redis directly. |
| Keep layers clean | Routes → Services → DB / Queue. |

---

# 3. General Development Principles

- Implement the smallest solution that satisfies the current story.
- Do not introduce abstractions for future features.
- Match the existing project style.
- Keep functions focused.
- Prefer readability over clever code.
- Add comments only when explaining distributed-system behavior or concurrency.

---

# 4. Security Rules

Always:

- Validate input using Pydantic.
- Reject unknown job types.
- Never execute payload data.
- Store sanitized error messages.
- Wrap handler execution so bad jobs never crash the worker.
- Validate idempotency keys.

---

# 5. Code Standards

- Python 3.11+
- Full type hints on public functions.
- Async FastAPI.
- Async SQLAlchemy.
- Async Redis.
- No unnecessary abstractions.
- No unrelated refactors.

---

# 6. Testing Rules

Every completed story must include tests.

Guidelines:

- Test behavior, not implementation.
- Keep tests isolated.
- Cover at least:
  - Happy path
  - One failure path
- Run all tests before closing the session.

---

# 7. Documentation Updates

When a story changes project behavior, update the relevant documentation.

| File | Update When |
|------|-------------|
| PLAN.md | Story completed |
| README.md | Usage or behavior changes |
| DECISIONS.md | Architectural decision changes |
| AI_USAGE.md | AI contributed to implementation |
| schema.sql | Database schema changes |

---

# 8. Session Exit Checklist

Before ending the session:

- [ ] Story completed
- [ ] Acceptance criteria satisfied
- [ ] Tests passing
- [ ] Architecture invariants preserved
- [ ] Documentation updated
- [ ] No unrelated refactors
- [ ] No secrets committed

---

# 9. Things Never To Do

- Don't commit unless explicitly asked.
- Don't push unless explicitly asked.
- Don't implement future stories.
- Don't let workers modify scheduling directly.
- Don't let workers re-enqueue failed jobs.
- Don't process jobs inside the API.
- Don't bypass PostgreSQL ownership.
- Don't trust AI concurrency suggestions without checking `DECISIONS.md`.

---

# 10. Philosophy

The project intentionally favors:

- Correctness over raw throughput.
- Recoverability over complexity.
- Simple operational behavior.
- Clear ownership boundaries.
- Predictable distributed-system behavior.

When in doubt, choose the simplest design that preserves these principles.