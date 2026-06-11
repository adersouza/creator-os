-- Fix Supabase linter warnings:
-- 1. function_search_path_mutable on get_aggregated_analytics
-- 2. function_search_path_mutable on classify_account_cohorts
-- 3. auth_rls_initplan on trending_topic_config

-- Pin search_path to prevent search path manipulation attacks
ALTER FUNCTION public.get_aggregated_analytics(TEXT, INTEGER, TEXT, TEXT[])
  SET search_path = public;

ALTER FUNCTION public.classify_account_cohorts()
  SET search_path = public;

-- Use (select auth.uid()) to evaluate once per query instead of per row
DROP POLICY IF EXISTS "Users can manage their own trending configs" ON trending_topic_config;
CREATE POLICY "Users can manage their own trending configs"
  ON trending_topic_config
  FOR ALL
  USING ((select auth.uid())::text = user_id)
  WITH CHECK ((select auth.uid())::text = user_id);
