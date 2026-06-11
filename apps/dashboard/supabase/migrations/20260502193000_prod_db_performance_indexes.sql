-- Production DB performance review follow-up.
--
-- Observed 2026-05-02 via pg_stat_user_tables on the linked Supabase project:
-- - post_metric_history: ~518k live rows, 26M cumulative seq tuples read.
-- - cron_runs: ~50k live rows, status/time health checks are frequent.
--
-- These indexes target existing hot paths:
-- - post_metric_history retention deletes by snapshot_at.
-- - first-24h velocity windows by post_id + hours_since_publish.
-- - cron health checks by status + started_at and retention by started_at.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA extensions;

CREATE INDEX IF NOT EXISTS idx_pmh_snapshot_at
  ON public.post_metric_history (snapshot_at);

CREATE INDEX IF NOT EXISTS idx_pmh_post_hours
  ON public.post_metric_history (post_id, hours_since_publish)
  INCLUDE (views_count, snapshot_at)
  WHERE hours_since_publish IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cron_runs_status_started_at
  ON public.cron_runs (status, started_at DESC)
  WHERE status <> 'success';

CREATE INDEX IF NOT EXISTS idx_cron_runs_started_at
  ON public.cron_runs (started_at DESC);

CREATE OR REPLACE FUNCTION public.analyze_small_tables()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  ANALYZE public.accounts;
  ANALYZE public.instagram_accounts;
  ANALYZE public.account_groups;
  ANALYZE public.workspaces;
  ANALYZE public.workspace_members;
  ANALYZE public.user_settings;
  ANALYZE public.notifications;
  ANALYZE public.competitors;
  ANALYZE public.sent_replies;
  ANALYZE public.inspiration_config;
  ANALYZE public.api_usage;
  ANALYZE public.feature_usage;
  ANALYZE public.audit_logs;
  ANALYZE public.creator_events;
  ANALYZE public.trend_forecasts;
  ANALYZE public.cron_runs;
  ANALYZE public.sync_jobs;
  ANALYZE public.rate_limit_tracking;
  ANALYZE public.account_health_snapshots;
  ANALYZE public.account_autoposter_state;
  ANALYZE public.competitor_top_posts;
  ANALYZE public.post_metric_history;
END;
$$;

GRANT EXECUTE ON FUNCTION public.analyze_small_tables() TO service_role;
