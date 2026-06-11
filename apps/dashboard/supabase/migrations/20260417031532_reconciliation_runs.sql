-- W2 daily reconciliation observability.
-- Tracks each run of /api/cron/reconcile-daily so we can see: how often
-- did we find orphan posts (webhook-loss evidence), how long did runs take,
-- which accounts errored. Service-role only — no user surface.

CREATE TABLE IF NOT EXISTS public.reconciliation_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  duration_ms INTEGER,
  platform TEXT NOT NULL CHECK (platform IN ('threads', 'instagram', 'all')),
  accounts_checked INTEGER NOT NULL DEFAULT 0,
  accounts_errored INTEGER NOT NULL DEFAULT 0,
  orphans_inserted INTEGER NOT NULL DEFAULT 0,
  posts_checked INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'completed', 'failed')),
  error_summary TEXT,
  details JSONB
);

CREATE INDEX IF NOT EXISTS reconciliation_runs_started_at_idx
  ON public.reconciliation_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS reconciliation_runs_status_idx
  ON public.reconciliation_runs (status)
  WHERE status <> 'completed';

ALTER TABLE public.reconciliation_runs ENABLE ROW LEVEL SECURITY;
-- No policies: service_role bypasses RLS (used by cron + admin routes).
-- Authenticated users see zero rows, which is correct for this internal table.
