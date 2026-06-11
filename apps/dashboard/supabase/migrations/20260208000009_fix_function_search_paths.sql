-- ============================================================================
-- Fix mutable search_path on all 13 public functions
--
-- Functions without explicit search_path resolve unqualified names using the
-- caller's session search_path. This is especially dangerous for the 5
-- SECURITY DEFINER functions which run with elevated (owner) privileges.
--
-- Setting search_path = public ensures deterministic name resolution.
-- ============================================================================

DO $$
DECLARE
  function_signature text;
  function_regprocedure regprocedure;
BEGIN
  FOREACH function_signature IN ARRAY ARRAY[
    'public.increment_dm_template_use(uuid, uuid)',
    'public.increment_link_click(uuid)',
    'public.mark_all_replies_as_read(uuid)',
    'public.mark_reply_as_read(uuid)',
    'public.refresh_group_analytics(text, date)',
    'public.acquire_cron_lock(text, text, integer)',
    'public.release_cron_lock(text, text)',
    'public.check_ig_endpoint_limit(uuid, text, integer, integer)',
    'public.ig_check_and_increment_rate_limit(uuid, integer)',
    'public.ig_check_and_increment_rate_limit(text, integer)',
    'public.update_inspiration_updated_at()',
    'public.update_saved_searches_updated_at()',
    'public.update_sync_jobs_updated_at()',
    'public.update_trends_updated_at()'
  ]
  LOOP
    function_regprocedure := to_regprocedure(function_signature);

    IF function_regprocedure IS NOT NULL THEN
      EXECUTE format('ALTER FUNCTION %s SET search_path = public', function_regprocedure);
    END IF;
  END LOOP;
END $$;
