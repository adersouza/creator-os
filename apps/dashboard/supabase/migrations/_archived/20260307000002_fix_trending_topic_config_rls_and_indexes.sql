-- Fix Supabase linter warnings on trending_topic_config:
-- 1. duplicate_index: drop redundant trending_topic_config_account_group_id_unique
--    (trending_topic_config_account_group_id_key from CREATE TABLE UNIQUE is identical)
-- 2. multiple_permissive_policies + auth_rls_initplan: drop users_manage_own_config
--    (bare auth.uid()) since "Users can manage their own trending configs"
--    already covers ALL operations with (select auth.uid())

-- Drop the duplicate unique constraint added in 20260307000001
ALTER TABLE public.trending_topic_config
  DROP CONSTRAINT IF EXISTS trending_topic_config_account_group_id_unique;

-- Drop the redundant policy that uses bare auth.uid() (causes initplan + duplicate policy warnings)
DROP POLICY IF EXISTS "users_manage_own_config" ON public.trending_topic_config;
