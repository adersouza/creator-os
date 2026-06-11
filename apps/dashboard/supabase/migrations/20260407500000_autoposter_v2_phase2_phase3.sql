-- Autoposter v2: Phase 2 (Content Pool) + Phase 3 (Flat Config)
-- Phase 2: pool_status column on auto_post_queue
-- Phase 3: account_schedule table + scheduler_decisions table

-- ============================================================================
-- Phase 2: Content Pool
-- ============================================================================

-- pool_status tracks the lifecycle of queue items in the content pool:
--   NULL    = legacy item (pre-v3, has account_id pre-assigned)
--   'available' = ready for the scheduler to claim
--   'claimed'   = assigned to an account by the scheduler
ALTER TABLE auto_post_queue
  ADD COLUMN IF NOT EXISTS pool_status TEXT DEFAULT NULL;

-- Index for the scheduler's hot query: find available items per group
CREATE INDEX IF NOT EXISTS idx_apq_pool_available
  ON auto_post_queue(group_id, pool_status)
  WHERE pool_status = 'available';

-- ============================================================================
-- Phase 3: Flat Account Config (account_schedule)
-- ============================================================================

-- One row per account+group with all scheduling config flattened.
-- Replaces the 5-level merge: workspace config > group config > account overrides > voice > ai config.
CREATE TABLE IF NOT EXISTS account_schedule (
  account_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  posts_per_day INT NOT NULL DEFAULT 1,
  min_interval_minutes INT NOT NULL DEFAULT 60,
  active_hours_start INT NOT NULL DEFAULT 8,
  active_hours_end INT NOT NULL DEFAULT 22,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  post_on_weekends BOOLEAN NOT NULL DEFAULT true,
  status TEXT NOT NULL DEFAULT 'active',
  status_reason TEXT,
  blocked_until TIMESTAMPTZ,
  paused BOOLEAN NOT NULL DEFAULT false,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (account_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_as_workspace
  ON account_schedule(workspace_id);

CREATE INDEX IF NOT EXISTS idx_as_group
  ON account_schedule(group_id);

-- ============================================================================
-- Phase 1 cleanup: scheduler_decisions table (if not yet created)
-- ============================================================================

CREATE TABLE IF NOT EXISTS scheduler_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT,
  group_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  reason TEXT NOT NULL,
  queue_item_id TEXT,
  account_status TEXT,
  local_hour INT,
  posts_today INT,
  minutes_since_last_post INT,
  queue_depth INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sd_group_created
  ON scheduler_decisions(group_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sd_account_created
  ON scheduler_decisions(account_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sd_run
  ON scheduler_decisions(run_id);

-- Partitioned cleanup: auto-delete decisions older than 7 days (cron handles this)
-- For now, a simple index on created_at enables efficient cleanup queries
CREATE INDEX IF NOT EXISTS idx_sd_created
  ON scheduler_decisions(created_at);

-- ============================================================================
-- Phase 3: Populate account_schedule from existing config hierarchy
-- Resolves: group_config -> account_overrides -> flat row
-- ============================================================================

INSERT INTO account_schedule (account_id, group_id, workspace_id, posts_per_day, min_interval_minutes, active_hours_start, active_hours_end, timezone, post_on_weekends, paused, status, updated_at)
SELECT
  a_id AS account_id,
  ag.id AS group_id,
  gc.workspace_id,
  COALESCE((ov.overrides->>'max_posts_per_day')::INT, gc.posts_per_account_per_day, 1) AS posts_per_day,
  COALESCE((ov.overrides->>'min_interval_minutes')::INT, gc.min_interval_minutes, 60) AS min_interval_minutes,
  COALESCE(gc.active_hours_start, 8) AS active_hours_start,
  COALESCE(gc.active_hours_end, 22) AS active_hours_end,
  COALESCE(gc.timezone, 'UTC') AS timezone,
  COALESCE(gc.post_on_weekends, true) AS post_on_weekends,
  COALESCE((ov.overrides->>'paused')::BOOLEAN, false) AS paused,
  COALESCE(st.status, 'active') AS status,
  NOW()
FROM account_groups ag
CROSS JOIN LATERAL unnest(ag.account_ids) AS a_id
JOIN auto_post_group_config gc ON gc.group_id = ag.id
LEFT JOIN auto_post_account_overrides ov ON ov.group_id = ag.id AND ov.account_id = a_id
LEFT JOIN account_autoposter_state st ON st.group_id = ag.id AND st.account_id = a_id
WHERE gc.enabled = true
ON CONFLICT (account_id, group_id) DO NOTHING;
