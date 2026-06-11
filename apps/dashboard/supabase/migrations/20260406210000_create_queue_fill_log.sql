-- Phase 4: Queue fill explain mode
-- When a fill produces 0 posts, this table records exactly why.

CREATE TABLE queue_fill_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL,
  group_id TEXT,

  started_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  -- Counts
  posts_inserted INT NOT NULL DEFAULT 0,
  posts_generated INT NOT NULL DEFAULT 0,
  posts_rejected INT NOT NULL DEFAULT 0,

  -- Rejection breakdown: {"duplicate": 3, "content_filter": 2, "embedding_dedup": 1}
  rejection_summary JSONB DEFAULT '{}',

  -- Account breakdown: {"eligible": 5, "skipped": {"suppressed": 2, "view_cooldown": 1}}
  account_summary JSONB DEFAULT '{}',

  -- Per-account skip details: [{"account_id": "...", "username": "@foo", "reason": "view_cooldown"}]
  skip_details JSONB DEFAULT '[]',

  -- Pipeline timing
  duration_ms INT,

  -- Early exit reason (if fill didn't reach generation): "ai_queue_fill_disabled", "daily_limit_reached", etc.
  early_exit_reason TEXT
);

-- Index for querying recent fills per group
CREATE INDEX idx_qfl_workspace_group ON queue_fill_log(workspace_id, group_id, completed_at DESC);

-- RLS: service_role only
ALTER TABLE queue_fill_log ENABLE ROW LEVEL SECURITY;

-- Auto-cleanup: keep 7 days of fill logs (cron can purge older)
COMMENT ON TABLE queue_fill_log IS 'Auto-poster queue fill explain log. Retain 7 days.';
