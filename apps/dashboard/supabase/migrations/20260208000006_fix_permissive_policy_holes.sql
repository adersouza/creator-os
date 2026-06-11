-- ============================================================================
-- Fix permissive policy security holes and redundancies
--
-- Problems found:
--   1. 3 policies check JWT for service_role but are granted to {public} —
--      redundant because service_role bypasses RLS entirely.
--   2. 6 policies use USING(true) granted to {public} on backend-only tables —
--      this gives ANY user (including anon) full read/write access.
--   3. notifications INSERT policy uses WITH CHECK(true) on {public} —
--      allows anonymous notification injection.
--   4. post_replies has two overlapping SELECT policies for {public}.
--
-- service_role bypasses RLS automatically, so no replacement policy is needed
-- for any backend-only table.
-- ============================================================================

BEGIN;

-- ============================================================================
-- Fix 1: Drop redundant JWT/role-checking policies
-- service_role bypasses RLS — these policies do nothing useful and cause
-- "Multiple Permissive Policies" lint warnings
-- ============================================================================

-- ============================================================================
-- Fix 2: Drop USING(true) policies granted to {public}
-- These are security holes — any authenticated or anon user gets full access.
-- Backend tables only need service_role, which bypasses RLS automatically.
-- ============================================================================

-- ============================================================================
-- Fix 3: Fix notifications INSERT policy
-- "Service role can insert notifications" is granted to {public} with
-- WITH CHECK(true) — allows ANY user (even anon) to insert notifications.
-- service_role bypasses RLS, so just drop it.
-- ============================================================================

-- ============================================================================
-- Fix 4: Drop redundant post_replies SELECT policy
-- "Users can read post_replies for their posts" (FK subquery) is fully
-- subsumed by "Authenticated users can view replies" (auth.uid() IS NOT NULL)
-- which already allows any authenticated user to read all replies.
-- ============================================================================

DO $$
DECLARE
  policy_record record;
BEGIN
  FOR policy_record IN
    SELECT *
    FROM (VALUES
      ('Service role full access to ig rate limits', 'ig_rate_limit_tracking'),
      ('Service role full access to instagram accounts', 'instagram_accounts'),
      ('Service role full access to threads_webhook_events', 'threads_webhook_events'),
      ('Service role manages cron_locks', 'cron_locks'),
      ('Service role manages cron_runs', 'cron_runs'),
      ('Service role manages ig_pending_containers', 'ig_pending_containers'),
      ('Service role manages ig_webhook_events', 'ig_webhook_events'),
      ('Service role manages threads_webhook_events', 'threads_webhook_events'),
      ('Service role can manage sync jobs', 'sync_jobs'),
      ('Service role can insert notifications', 'notifications'),
      ('Users can read post_replies for their posts', 'post_replies')
    ) AS policy(policy_name, table_name)
  LOOP
    IF to_regclass('public.' || quote_ident(policy_record.table_name)) IS NOT NULL THEN
      EXECUTE format(
        'DROP POLICY IF EXISTS %I ON public.%I',
        policy_record.policy_name,
        policy_record.table_name
      );
    END IF;
  END LOOP;
END $$;

COMMIT;
