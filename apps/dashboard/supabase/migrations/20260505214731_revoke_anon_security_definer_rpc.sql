-- ============================================================================
-- Revoke anon-callable SECURITY DEFINER RPC functions
-- ============================================================================
-- Date: 2026-05-05
-- Findings: Supabase security advisor flagged SECURITY DEFINER functions
-- callable by the anon role via PostgREST /rest/v1/rpc/.
--
-- Clean branch replay may not contain every historical function overload. Use
-- pg_proc-backed dynamic REVOKE/GRANT so missing signatures are skipped instead
-- of aborting replay.
-- ============================================================================

BEGIN;

DO $$
DECLARE
  target record;
  fn_name text;
BEGIN
  FOR target IN
    SELECT *
    FROM (
      VALUES
        -- Group A: REVOKE from anon only; authenticated + service_role keep EXECUTE.
        ('aal2_or_no_mfa', '', 'anon', 'authenticated, service_role'),
        ('is_workspace_member', 'text', 'anon', 'authenticated, service_role'),
        ('is_workspace_member', 'text, text', 'anon', 'authenticated, service_role'),
        ('is_workspace_admin', 'text', 'anon', 'authenticated, service_role'),
        ('is_workspace_owner', 'text, text', 'anon', 'authenticated, service_role'),
        ('mark_reply_as_read', 'uuid', 'anon', 'authenticated, service_role'),
        ('mark_all_replies_as_read', 'uuid', 'anon', 'authenticated, service_role'),
        ('assign_account_to_group', 'text, text, text', 'anon', 'authenticated, service_role'),
        ('get_post_floor_aggregates', 'text, text[], timestamp with time zone, text', 'anon', 'authenticated, service_role'),

        -- Group B: REVOKE from PUBLIC; service_role only.
        ('analyze_small_tables', '', 'PUBLIC', 'service_role'),
        ('classify_account_cohorts', '', 'PUBLIC', 'service_role'),
        ('cleanup_old_audit_logs', '', 'PUBLIC', 'service_role'),
        ('cleanup_old_cron_runs', 'integer', 'PUBLIC', 'service_role'),
        ('refresh_group_analytics', '', 'PUBLIC', 'service_role'),
        ('refresh_group_analytics', 'text, date', 'PUBLIC', 'service_role'),
        ('rls_auto_enable', '', 'PUBLIC', 'service_role'),
        ('check_publish_rate_limit', 'text, text', 'PUBLIC', 'service_role'),
        ('check_reply_rate_limit', 'text, integer, integer', 'PUBLIC', 'service_role'),
        ('check_trigram_dupe', 'text, text, real', 'PUBLIC', 'service_role'),
        ('claim_beta_spot', 'text, integer', 'PUBLIC', 'service_role'),
        ('get_smart_link_revenue_summary', 'text, integer', 'PUBLIC', 'service_role'),
        ('ig_check_and_increment_rate_limit', 'uuid, integer', 'PUBLIC', 'service_role'),
        ('increment_api_usage', 'text, text', 'PUBLIC', 'service_role'),
        ('increment_group_posts_today', 'text, text, text', 'PUBLIC', 'service_role'),
        ('webhook_p95_latency_seconds', 'text, timestamp with time zone', 'PUBLIC', 'service_role'),
        ('handle_new_user', '', 'PUBLIC', 'service_role'),
        ('update_updated_at', '', 'PUBLIC', 'service_role')
    ) AS v(name, args, revoke_from, grant_to)
  LOOP
    SELECT p.proname INTO fn_name
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname = target.name
      AND oidvectortypes(p.proargtypes) = target.args;

    IF fn_name IS NOT NULL THEN
      EXECUTE format(
        'REVOKE EXECUTE ON FUNCTION public.%I(%s) FROM %s',
        target.name,
        target.args,
        target.revoke_from
      );
      EXECUTE format(
        'GRANT EXECUTE ON FUNCTION public.%I(%s) TO %s',
        target.name,
        target.args,
        target.grant_to
      );
    END IF;
  END LOOP;
END $$;

COMMIT;
