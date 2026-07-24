-- PostgreSQL schema — source of truth for job state.
-- Redis (jobs:pending ZSET) is the dispatch layer; Postgres wins on conflict.

CREATE TYPE job_status AS ENUM (
    'scheduled',
    'pending',
    'processing',
    'completed',
    'failed',
    'cancelled'
);

CREATE TYPE job_type AS ENUM (
    'email',
    'webhook',
    'report',
    'batch'
);

CREATE TYPE log_level AS ENUM (
    'info',
    'warning',
    'error'
);

CREATE TABLE jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type        job_type NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}',

    status          job_status NOT NULL DEFAULT 'pending',
    priority        INTEGER NOT NULL DEFAULT 0,

    attempt_count   INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,

    error_message   TEXT,
    error_details   JSONB,

    progress_pct    INTEGER NOT NULL DEFAULT 0
                    CHECK (progress_pct >= 0 AND progress_pct <= 100),

    scheduled_at    TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,

    idempotency_key VARCHAR(255),

    worker_id       VARCHAR(255),
    leased_until    TIMESTAMPTZ,

    result          JSONB,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,

    CONSTRAINT chk_attempt_count_non_negative CHECK (attempt_count >= 0),
    CONSTRAINT chk_max_attempts_positive CHECK (max_attempts > 0)
);

-- One active idempotency key at a time; cleanup nulls keys older than 24h to allow reuse.
CREATE UNIQUE INDEX uq_jobs_idempotency_key
    ON jobs (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- Worker feeder: pending jobs ordered by priority (next_run_at filtered at query time).
CREATE INDEX idx_jobs_pending_ready
    ON jobs (priority DESC, created_at ASC)
    WHERE status = 'pending';

-- Scheduler: due scheduled jobs.
CREATE INDEX idx_jobs_scheduled_at
    ON jobs (scheduled_at)
    WHERE status = 'scheduled';

-- API list/filter endpoints.
CREATE INDEX idx_jobs_status ON jobs (status);
CREATE INDEX idx_jobs_job_type ON jobs (job_type);
CREATE INDEX idx_jobs_created_at ON jobs (created_at DESC);

-- Reaper (should-have): recover stuck processing jobs.
CREATE INDEX idx_jobs_processing_leased
    ON jobs (leased_until)
    WHERE status = 'processing';

CREATE TABLE job_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      UUID NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
    level       log_level NOT NULL DEFAULT 'info',
    message     TEXT NOT NULL,
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_job_logs_job_id ON job_logs (job_id, created_at);

-- Idempotency key cleanup (run periodically, e.g. every hour):
--   UPDATE jobs
--   SET idempotency_key = NULL
--   WHERE idempotency_key IS NOT NULL
--     AND created_at < now() - interval '24 hours';
