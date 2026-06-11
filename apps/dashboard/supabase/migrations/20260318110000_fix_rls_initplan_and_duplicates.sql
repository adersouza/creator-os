-- Fix two Supabase linter warnings:
-- 1. auth_rls_initplan (0003): wrap auth.uid() in (select ...) for per-query eval
-- 2. multiple_permissive_policies (0006): drop redundant rls_user_* duplicates

-- ============================================================================
-- DROP DUPLICATE PERMISSIVE POLICIES
-- These are strictly less restrictive subsets of the workspace-scoped policies.
-- ============================================================================

DROP POLICY IF EXISTS "rls_user_inspiration_ideas" ON public.inspiration_ideas;
DROP POLICY IF EXISTS "rls_user_saved_competitor_posts" ON public.saved_competitor_posts;

-- ============================================================================
-- FIX auth_rls_initplan: wrap auth.uid() in (select ...) subselect
-- ============================================================================

-- 1. agent_actions — SELECT
DROP POLICY IF EXISTS "Users can read own agent actions" ON public.agent_actions;
CREATE POLICY "Users can read own agent actions" ON public.agent_actions
  FOR SELECT USING (((select auth.uid())::text = user_id));

-- 2. agent_actions — INSERT
DROP POLICY IF EXISTS "Users can insert own agent actions" ON public.agent_actions;
CREATE POLICY "Users can insert own agent actions" ON public.agent_actions
  FOR INSERT WITH CHECK (((select auth.uid())::text = user_id));

-- 3. agent_approvals — ALL
DROP POLICY IF EXISTS "Users manage own approvals" ON public.agent_approvals;
CREATE POLICY "Users manage own approvals" ON public.agent_approvals
  FOR ALL USING (((select auth.uid())::text = user_id));

-- 4. data_export_jobs — ALL
DROP POLICY IF EXISTS "Users manage own exports" ON public.data_export_jobs;
CREATE POLICY "Users manage own exports" ON public.data_export_jobs
  FOR ALL USING (((select auth.uid())::text = user_id));

-- 5. account_health_snapshots — SELECT
DROP POLICY IF EXISTS "Users can read own health snapshots" ON public.account_health_snapshots;
CREATE POLICY "Users can read own health snapshots" ON public.account_health_snapshots
  FOR SELECT USING (((select auth.uid())::text = user_id));

-- 6. agent_notes — ALL
DO $$
BEGIN
  IF to_regclass('public.agent_notes') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Users manage own agent notes" ON public.agent_notes;
    CREATE POLICY "Users manage own agent notes" ON public.agent_notes
      FOR ALL USING (((select auth.uid())::text = user_id));
  END IF;
END $$;

-- 7. revenue_snapshots — ALL
DO $$
BEGIN
  IF to_regclass('public.revenue_snapshots') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Users manage own revenue snapshots" ON public.revenue_snapshots;
    CREATE POLICY "Users manage own revenue snapshots" ON public.revenue_snapshots
      FOR ALL USING (((select auth.uid())::text = user_id));
  END IF;
END $$;
