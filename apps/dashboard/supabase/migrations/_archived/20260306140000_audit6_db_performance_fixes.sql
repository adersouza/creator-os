-- Audit #6: DB Performance Hotspots — Fix redundant indexes + autovacuum thresholds
-- See DEEP_AUDIT_TRACKER.md for full analysis

-- ============================================================================
-- Finding 1: Drop redundant/unused posts indexes (25 → 22)
-- ============================================================================

-- Never used (0 scans since DB creation)
DROP INDEX IF EXISTS idx_posts_draft_folder_id;
DROP INDEX IF EXISTS idx_posts_rejected_by;

-- Redundant: idx_posts_account_status (account_id, status) is a prefix of
-- idx_posts_account_status_published (account_id, status, published_at DESC)
-- which has 30,888 scans vs 1,189 — the wider index serves both query patterns.
DROP INDEX IF EXISTS idx_posts_account_status;

-- ============================================================================
-- Finding 5: Lower autovacuum thresholds for small high-churn tables
-- Default is threshold=50 + scale_factor=0.2, which means tables with <50
-- dead tuples never trigger autovacuum regardless of dead-to-live ratio.
-- ============================================================================

ALTER TABLE user_settings SET (
  autovacuum_vacuum_threshold = 5,
  autovacuum_vacuum_scale_factor = 0.1,
  autovacuum_analyze_threshold = 5,
  autovacuum_analyze_scale_factor = 0.1
);

ALTER TABLE notifications SET (
  autovacuum_vacuum_threshold = 5,
  autovacuum_vacuum_scale_factor = 0.1,
  autovacuum_analyze_threshold = 5,
  autovacuum_analyze_scale_factor = 0.1
);

ALTER TABLE competitors SET (
  autovacuum_vacuum_threshold = 5,
  autovacuum_vacuum_scale_factor = 0.1,
  autovacuum_analyze_threshold = 5,
  autovacuum_analyze_scale_factor = 0.1
);

ALTER TABLE workspaces SET (
  autovacuum_vacuum_threshold = 5,
  autovacuum_vacuum_scale_factor = 0.1,
  autovacuum_analyze_threshold = 5,
  autovacuum_analyze_scale_factor = 0.1
);

ALTER TABLE workspace_members SET (
  autovacuum_vacuum_threshold = 5,
  autovacuum_vacuum_scale_factor = 0.1,
  autovacuum_analyze_threshold = 5,
  autovacuum_analyze_scale_factor = 0.1
);

ALTER TABLE inspiration_config SET (
  autovacuum_vacuum_threshold = 5,
  autovacuum_vacuum_scale_factor = 0.1,
  autovacuum_analyze_threshold = 5,
  autovacuum_analyze_scale_factor = 0.1
);

ALTER TABLE account_groups SET (
  autovacuum_vacuum_threshold = 5,
  autovacuum_vacuum_scale_factor = 0.1,
  autovacuum_analyze_threshold = 5,
  autovacuum_analyze_scale_factor = 0.1
);

ALTER TABLE sent_replies SET (
  autovacuum_vacuum_threshold = 5,
  autovacuum_vacuum_scale_factor = 0.1,
  autovacuum_analyze_threshold = 5,
  autovacuum_analyze_scale_factor = 0.1
);

-- ============================================================================
-- Finding 4: Run ANALYZE on tables that have never been analyzed
-- ============================================================================

ANALYZE creator_events;
ANALYZE trend_forecasts;
ANALYZE feature_usage;
ANALYZE audit_logs;
ANALYZE user_settings;
ANALYZE post_metric_history;
ANALYZE api_usage;
ANALYZE competitors;
ANALYZE sent_replies;
ANALYZE notifications;
ANALYZE workspaces;
ANALYZE workspace_members;
ANALYZE account_groups;
ANALYZE inspiration_config;

-- ============================================================================
-- RPC function for daily-maintenance Phase 7: ANALYZE small tables
-- Called by daily-maintenance.ts to keep planner statistics fresh.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.analyze_small_tables()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  ANALYZE user_settings;
  ANALYZE notifications;
  ANALYZE competitors;
  ANALYZE workspaces;
  ANALYZE workspace_members;
  ANALYZE inspiration_config;
  ANALYZE account_groups;
  ANALYZE sent_replies;
  ANALYZE post_metric_history;
  ANALYZE api_usage;
  ANALYZE feature_usage;
  ANALYZE audit_logs;
  ANALYZE creator_events;
  ANALYZE trend_forecasts;
END;
$$;
