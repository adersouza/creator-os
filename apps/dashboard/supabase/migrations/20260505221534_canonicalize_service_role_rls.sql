-- ============================================================================
-- Canonicalize service-role RLS policies
-- ============================================================================
-- Date: 2026-05-05
-- Advisor flagged service-role policies whose quals used
-- `(SELECT (auth.jwt() ->> 'role'))`. Rewrite existing policies to the
-- canonical `(SELECT auth.role())` pattern and scope service-only policies to
-- `service_role`.
--
-- Historical clean replay can omit some production-only tables/policies, so
-- every ALTER is catalog-guarded.
-- ============================================================================

BEGIN;

DO $$
DECLARE
  target record;
BEGIN
  FOR target IN
    SELECT *
    FROM (
      VALUES
        ('account_health_signals', 'Service role manages account health signals', false, true),
        ('ai_action_log', 'Service role writes ai logs', false, true),
        ('autopilot_run_steps', 'autopilot_run_steps_service_all', false, true),
        ('autopilot_runs', 'autopilot_runs_service_all', false, true),
        ('portfolio_account_health', 'Service role manages health', false, true),
        ('post_originality_signals', 'Service role manages originality signals', false, true),
        ('report_send_log', 'Service role manages report send log', false, true),
        ('account_autoposter_state', 'service_role_all', true, true),
        ('account_schedule', 'service_role_all', true, true),
        ('auth_lockout_log', 'service_role_all', true, true),
        ('data_deletion_requests', 'service_role_all', true, true),
        ('follower_history', 'Service can manage follower history', true, true),
        ('link_page_variants', 'link_page_variants_service_insert', true, false),
        ('link_page_variants', 'link_page_variants_service_update', true, true),
        ('link_visitor_signals', 'service_role_all', true, true),
        ('publish_locks', 'service_role_all', true, true),
        ('queue_fill_log', 'service_role_all', true, true),
        ('reconciliation_runs', 'service_role_all', true, true),
        ('recovery_codes', 'service_role_all', true, true),
        ('reply_response_times', 'Service can manage reply times', true, true),
        ('scheduler_decisions', 'service_role_all', true, true),
        ('stripe_processed_events', 'service_role_all', true, true),
        ('webhook_deliveries', 'service_role_all', true, true)
    ) AS v(table_name, policy_name, set_service_role, has_using)
  LOOP
    IF EXISTS (
      SELECT 1
      FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename = target.table_name
        AND policyname = target.policy_name
    ) THEN
      IF target.has_using THEN
        EXECUTE format(
          'ALTER POLICY %I ON public.%I%s USING ((SELECT auth.role()) = ''service_role'') WITH CHECK ((SELECT auth.role()) = ''service_role'')',
          target.policy_name,
          target.table_name,
          CASE WHEN target.set_service_role THEN ' TO service_role' ELSE '' END
        );
      ELSE
        EXECUTE format(
          'ALTER POLICY %I ON public.%I%s WITH CHECK ((SELECT auth.role()) = ''service_role'')',
          target.policy_name,
          target.table_name,
          CASE WHEN target.set_service_role THEN ' TO service_role' ELSE '' END
        );
      END IF;
    END IF;
  END LOOP;
END $$;

COMMIT;
