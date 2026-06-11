-- ============================================================================
-- Dedupe multiple_permissive_policies
-- ============================================================================
-- Date: 2026-05-05
-- Per-row Postgres has to evaluate every permissive policy applying to the
-- caller's role + cmd and OR the results. The advisor flagged ~62 such
-- duplicates. Fixes:
--
--   A. Drop redundant duplicate user policies (5 tables — same predicate,
--      same role coverage as the kept policy).
--   B. Scope user policies from TO public → TO authenticated.
--   C. Scope service-role policies from TO public → TO service_role.
--   D. Convert ALL-cmd policies overlapping a SELECT-cmd policy into
--      INSERT+UPDATE+DELETE only (drop+recreate) for auto_post_state and
--      banned_phrases.
-- ============================================================================

BEGIN;

-- ============================================================================
-- A. Drop redundant duplicate user policies
-- ============================================================================

DROP POLICY IF EXISTS "Users manage own keys" ON public.api_keys;
DROP POLICY IF EXISTS "rls_user_inspiration_config" ON public.inspiration_config;
DROP POLICY IF EXISTS "rls_user_trend_keywords" ON public.trend_keywords;
DROP POLICY IF EXISTS "rls_user_trend_posts" ON public.trend_posts;
DROP POLICY IF EXISTS "rls_user_trend_snapshots" ON public.trend_snapshots;

-- ============================================================================
-- B. Scope user policies to authenticated only
-- ============================================================================

ALTER POLICY "Users read own account daily summaries"
  ON public.account_daily_summary TO authenticated;

ALTER POLICY "Users view own account health signals"
  ON public.account_health_signals TO authenticated;

ALTER POLICY "Users view own ai logs"
  ON public.ai_action_log TO authenticated;

ALTER POLICY "Users can read own cross-replies"
  ON public.auto_cross_replies TO authenticated;

ALTER POLICY "Users can read own self-replies"
  ON public.auto_self_replies TO authenticated;

ALTER POLICY "autopilot_run_steps_select_own"
  ON public.autopilot_run_steps TO authenticated;

ALTER POLICY "autopilot_runs_select_own"
  ON public.autopilot_runs TO authenticated;

ALTER POLICY "Users view own portfolio health"
  ON public.portfolio_account_health TO authenticated;

ALTER POLICY "Users view own originality signals"
  ON public.post_originality_signals TO authenticated;

ALTER POLICY "Users view own report send log"
  ON public.report_send_log TO authenticated;

ALTER POLICY "Users manage own shared reports"
  ON public.shared_reports TO authenticated;

ALTER POLICY "users_read_own_conversions"
  ON public.smart_link_conversions TO authenticated;

ALTER POLICY "Users can view own sync jobs"
  ON public.sync_jobs TO authenticated;

ALTER POLICY "users_manage_own_discoveries"
  ON public.trend_discoveries TO authenticated;

ALTER POLICY "Users can manage their own trending configs"
  ON public.trending_topic_config TO authenticated;

-- ============================================================================
-- C. Scope service-role policies stuck at public → TO service_role
-- ============================================================================

ALTER POLICY "Service role manages account health signals"
  ON public.account_health_signals TO service_role;

ALTER POLICY "Service role writes ai logs"
  ON public.ai_action_log TO service_role;

ALTER POLICY "autopilot_run_steps_service_all"
  ON public.autopilot_run_steps TO service_role;

ALTER POLICY "autopilot_runs_service_all"
  ON public.autopilot_runs TO service_role;

ALTER POLICY "Service role manages health"
  ON public.portfolio_account_health TO service_role;

ALTER POLICY "Service role manages originality signals"
  ON public.post_originality_signals TO service_role;

ALTER POLICY "Service role manages report send log"
  ON public.report_send_log TO service_role;

-- ============================================================================
-- D. Convert ALL-cmd policies overlapping SELECT-cmd policies into write-only
-- ============================================================================

-- auto_post_state: _read covers SELECT; _write was ALL with same predicate
DROP POLICY IF EXISTS "auto_post_state_write" ON public.auto_post_state;
CREATE POLICY "auto_post_state_write_insert" ON public.auto_post_state
  FOR INSERT TO authenticated
  WITH CHECK (workspace_id IN (
    SELECT workspace_members.workspace_id FROM workspace_members
    WHERE workspace_members.user_id = ((SELECT auth.uid()))::text
  ));
CREATE POLICY "auto_post_state_write_update" ON public.auto_post_state
  FOR UPDATE TO authenticated
  USING (workspace_id IN (
    SELECT workspace_members.workspace_id FROM workspace_members
    WHERE workspace_members.user_id = ((SELECT auth.uid()))::text
  ))
  WITH CHECK (workspace_id IN (
    SELECT workspace_members.workspace_id FROM workspace_members
    WHERE workspace_members.user_id = ((SELECT auth.uid()))::text
  ));
CREATE POLICY "auto_post_state_write_delete" ON public.auto_post_state
  FOR DELETE TO authenticated
  USING (workspace_id IN (
    SELECT workspace_members.workspace_id FROM workspace_members
    WHERE workspace_members.user_id = ((SELECT auth.uid()))::text
  ));

DROP POLICY IF EXISTS "auto_post_state_read" ON public.auto_post_state;
DROP POLICY IF EXISTS "Users can read own auto_post_state" ON public.auto_post_state;
CREATE POLICY "auto_post_state_read" ON public.auto_post_state
  FOR SELECT TO authenticated
  USING (workspace_id IN (
    SELECT workspace_members.workspace_id FROM workspace_members
    WHERE workspace_members.user_id = ((SELECT auth.uid()))::text
  ));

-- banned_phrases: members_read covers SELECT (owner is also member);
-- owner_write was ALL with owner predicate
DROP POLICY IF EXISTS "banned_phrases_owner_write" ON public.banned_phrases;
CREATE POLICY "banned_phrases_owner_insert" ON public.banned_phrases
  FOR INSERT TO authenticated
  WITH CHECK (is_workspace_owner(workspace_id, ((SELECT auth.uid()))::text));
CREATE POLICY "banned_phrases_owner_update" ON public.banned_phrases
  FOR UPDATE TO authenticated
  USING (is_workspace_owner(workspace_id, ((SELECT auth.uid()))::text))
  WITH CHECK (is_workspace_owner(workspace_id, ((SELECT auth.uid()))::text));
CREATE POLICY "banned_phrases_owner_delete" ON public.banned_phrases
  FOR DELETE TO authenticated
  USING (is_workspace_owner(workspace_id, ((SELECT auth.uid()))::text));

DROP POLICY IF EXISTS "banned_phrases_members_read" ON public.banned_phrases;
CREATE POLICY "banned_phrases_members_read" ON public.banned_phrases
  FOR SELECT TO authenticated
  USING (is_workspace_member(workspace_id, ((SELECT auth.uid()))::text));

COMMIT;
