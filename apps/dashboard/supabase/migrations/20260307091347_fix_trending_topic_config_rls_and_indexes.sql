-- Backfilled from DB migration history
ALTER TABLE public.trending_topic_config
  DROP CONSTRAINT IF EXISTS trending_topic_config_account_group_id_unique;
DROP POLICY IF EXISTS "users_manage_own_config" ON public.trending_topic_config;
