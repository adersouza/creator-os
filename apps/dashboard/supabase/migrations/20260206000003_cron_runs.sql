-- Migration: Cron Runs — Health monitoring for cron executions
-- Date: 2026-02-06
-- Purpose: Track cron job execution history for monitoring and debugging

CREATE TABLE IF NOT EXISTS cron_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_name TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running',  -- 'running' | 'success' | 'partial' | 'failed'
  items_processed INT DEFAULT 0,
  error TEXT,
  metadata JSONB DEFAULT '{}'
);

-- Index for querying recent runs by job
CREATE INDEX IF NOT EXISTS idx_cron_runs_job_started ON cron_runs(job_name, started_at DESC);

-- Index for finding non-successful runs
CREATE INDEX IF NOT EXISTS idx_cron_runs_status ON cron_runs(status) WHERE status != 'success';

-- ============================================================================
-- Permissions
-- ============================================================================

GRANT ALL ON cron_runs TO service_role;
