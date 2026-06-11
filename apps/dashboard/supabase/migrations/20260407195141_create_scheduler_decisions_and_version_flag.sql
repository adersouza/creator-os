-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260407195141
-- applied-by: create_scheduler_decisions_and_version_flag migration row


-- Phase 1: Scheduler v2 infrastructure

-- 1. Decision log table
CREATE TABLE IF NOT EXISTS scheduler_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  run_id UUID NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  account_status TEXT,
  window_hour INT,
  cap_used INT,
  cap_limit INT,
  minutes_since_last_post INT,
  queue_depth INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sd_workspace_created ON scheduler_decisions(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sd_account ON scheduler_decisions(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sd_run ON scheduler_decisions(run_id);

-- 2. Feature flag column on auto_post_config
ALTER TABLE auto_post_config ADD COLUMN IF NOT EXISTS scheduler_version INT NOT NULL DEFAULT 1;

COMMENT ON TABLE scheduler_decisions IS 'Scheduler v2 decision log. Retain 3 days via data-retention cron.';
COMMENT ON COLUMN auto_post_config.scheduler_version IS '1=legacy (4 crons), 2=unified scheduler';
