-- ============================================================================
-- Fix Supabase database linter warnings (2026-02-23)
--
-- 1. Set search_path on increment_smart_link_click (SQL function)
-- 2. Set search_path on increment_view_count (SECURITY DEFINER)
-- 3. Fix overly permissive RLS policy on viral_score_calibration
-- 4. Add explicit service_role policies to 5 backend-only tables
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. Fix mutable search_path on increment_smart_link_click
--    Created in 20260222040000_smart_links.sql, missed by earlier fix pass.
-- ============================================================================
ALTER FUNCTION public.increment_smart_link_click(uuid)
  SET search_path = '';

-- ============================================================================
-- 2. Fix mutable search_path on increment_view_count (SECURITY DEFINER)
--    Created in 20260219050000, missed by earlier fix pass.
-- ============================================================================
ALTER FUNCTION public.increment_view_count(uuid)
  SET search_path = '';

-- ============================================================================
-- 3. Fix overly permissive RLS on viral_score_calibration
--    The "Service role can manage calibration data" policy uses USING(true)
--    WITH CHECK(true) granted TO public — this gives authenticated/anon full
--    access. Replace with a service_role-only policy.
-- ============================================================================
DROP POLICY IF EXISTS "Service role can manage calibration data" ON viral_score_calibration;

CREATE POLICY "Service role manages calibration data"
  ON viral_score_calibration FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- 4. Add explicit service_role policies to backend-only tables
--    These tables have RLS enabled but zero policies. service_role bypasses
--    RLS automatically, but explicit policies silence the linter and make
--    intent clear. authenticated/anon remain denied (no policy = no access).
-- ============================================================================

-- auto_post_engagement_snapshots (cron engagement velocity tracking)
CREATE POLICY "Service role manages engagement snapshots"
  ON auto_post_engagement_snapshots FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- auto_reply_logs (auto-reply cooldown/audit)
CREATE POLICY "Service role manages auto reply logs"
  ON auto_reply_logs FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ig_endpoint_rate_limits (API rate limit tracking)
CREATE POLICY "Service role manages IG endpoint rate limits"
  ON ig_endpoint_rate_limits FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ig_story_insights (API route only, no user_id)
CREATE POLICY "Service role manages IG story insights"
  ON ig_story_insights FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- trial_emails (internal system table, no user_id)
CREATE POLICY "Service role manages trial emails"
  ON trial_emails FOR ALL TO service_role
  USING (true) WITH CHECK (true);

COMMIT;
