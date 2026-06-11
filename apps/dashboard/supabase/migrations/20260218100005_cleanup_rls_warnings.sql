-- ============================================================================
-- Cleanup: Remove redundant policies, fix initplan warnings, drop duplicate indexes
-- Date: 2026-02-18
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. Drop "Service role full access" policies — service_role bypasses RLS
--    These are unnecessary and cause auth_rls_initplan warnings
-- ============================================================================

DROP POLICY IF EXISTS "Service role full access" ON ig_pending_containers;
DROP POLICY IF EXISTS "Service role full access" ON threads_webhook_events;
DROP POLICY IF EXISTS "Service role full access" ON cron_locks;
DROP POLICY IF EXISTS "Service role full access" ON cron_runs;

-- group_analytics: drop service role + duplicate user policies
DROP POLICY IF EXISTS "Service role manages group_analytics" ON group_analytics;
DROP POLICY IF EXISTS "Users can read own group analytics" ON group_analytics;
-- Keep only "Users read own group analytics" (the newer, properly scoped one)
-- Recreate it with (SELECT auth.uid()) for initplan optimization
DROP POLICY IF EXISTS "Users read own group analytics" ON group_analytics;
CREATE POLICY "Users read own group analytics"
  ON group_analytics FOR SELECT
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 2. Fix duplicate policies on notifications
--    Drop the older one, keep "Users read own notifications"
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.notifications') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Users can view own notifications" ON public.notifications;
  END IF;
END $$;

-- ============================================================================
-- 3. Fix duplicate policies on post_replies
--    Drop the old per-action policies, keep "Users access own post replies" (FOR ALL)
-- ============================================================================

DROP POLICY IF EXISTS "Authenticated users can insert replies" ON post_replies;
DROP POLICY IF EXISTS "Authenticated users can update replies" ON post_replies;
DROP POLICY IF EXISTS "Authenticated users can delete replies" ON post_replies;

-- ============================================================================
-- 4. Drop duplicate indexes
-- ============================================================================

-- account_analytics: keep idx_account_analytics_account_date, drop the other
DROP INDEX IF EXISTS idx_account_analytics_account_id_date;

-- competitor_posts: keep idx_competitor_posts_competitor_created, drop the other
DROP INDEX IF EXISTS idx_competitor_posts_competitor_date;

-- cron_runs: keep idx_cron_runs_job_recent, drop the other
DROP INDEX IF EXISTS idx_cron_runs_job_started;

COMMIT;
