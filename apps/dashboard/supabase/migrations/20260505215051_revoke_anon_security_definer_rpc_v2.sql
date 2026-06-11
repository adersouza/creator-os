-- ============================================================================
-- Revoke anon-callable SECURITY DEFINER RPC functions — corrected pass
-- ============================================================================
-- Date: 2026-05-05
-- Prior migration 20260505214731 keeps authenticated grants for frontend/RLS
-- helpers. This pass removes PUBLIC grants for those helpers and explicit
-- anon/authenticated grants for backend-only functions.
--
-- Clean replay may not contain every historical function overload, so every
-- REVOKE is driven from pg_proc and missing signatures are skipped.
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
        -- Pattern 1: REVOKE FROM PUBLIC. Authenticated keeps explicit grant.
        ('mark_reply_as_read', 'uuid', 'PUBLIC'),
        ('mark_all_replies_as_read', 'uuid', 'PUBLIC'),
        ('assign_account_to_group', 'text, text, text', 'PUBLIC'),
        ('get_post_floor_aggregates', 'text, text[], timestamp with time zone, text', 'PUBLIC'),
        ('is_workspace_member', 'text', 'PUBLIC'),
        ('is_workspace_member', 'text, text', 'PUBLIC'),
        ('is_workspace_admin', 'text', 'PUBLIC'),
        ('is_workspace_owner', 'text, text', 'PUBLIC'),

        -- Pattern 2: backend/cron functions are service_role only.
        ('analyze_small_tables', '', 'anon, authenticated'),
        ('classify_account_cohorts', '', 'anon, authenticated'),
        ('cleanup_old_audit_logs', '', 'anon, authenticated'),
        ('cleanup_old_cron_runs', 'integer', 'anon, authenticated'),
        ('refresh_group_analytics', '', 'anon, authenticated'),
        ('refresh_group_analytics', 'text, date', 'anon, authenticated'),
        ('rls_auto_enable', '', 'anon, authenticated'),
        ('check_publish_rate_limit', 'text, text', 'anon, authenticated'),
        ('check_reply_rate_limit', 'text, integer, integer', 'anon, authenticated'),
        ('check_trigram_dupe', 'text, text, real', 'anon, authenticated'),
        ('claim_beta_spot', 'text, integer', 'anon, authenticated'),
        ('get_smart_link_revenue_summary', 'text, integer', 'anon, authenticated'),
        ('ig_check_and_increment_rate_limit', 'uuid, integer', 'anon, authenticated'),
        ('increment_api_usage', 'text, text', 'anon, authenticated'),
        ('increment_group_posts_today', 'text, text, text', 'anon, authenticated'),
        ('webhook_p95_latency_seconds', 'text, timestamp with time zone', 'anon, authenticated'),
        ('handle_new_user', '', 'anon, authenticated'),
        ('update_updated_at', '', 'anon, authenticated')
    ) AS v(name, args, revoke_from)
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
    END IF;
  END LOOP;
END $$;

COMMIT;
