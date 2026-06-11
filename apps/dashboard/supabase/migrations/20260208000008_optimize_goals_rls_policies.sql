-- ============================================================================
-- Optimize RLS policies on user_goals and goal_history_snapshots
--
-- These tables were created after migration 000003 and still use bare
-- auth.uid() calls. Wrapping in (SELECT auth.uid()) ensures the planner
-- evaluates the function once per query instead of once per row.
-- ============================================================================

BEGIN;

DO $$
BEGIN
  IF to_regclass('public.user_goals') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Users can manage own goals" ON user_goals;
    CREATE POLICY "Users can manage own goals" ON user_goals
      FOR ALL USING ((SELECT auth.uid())::text = user_id);
  END IF;

  IF to_regclass('public.goal_history_snapshots') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Users can manage own goal history" ON goal_history_snapshots;
    CREATE POLICY "Users can manage own goal history" ON goal_history_snapshots
      FOR ALL USING ((SELECT auth.uid())::text = user_id);
  END IF;
END $$;

COMMIT;
