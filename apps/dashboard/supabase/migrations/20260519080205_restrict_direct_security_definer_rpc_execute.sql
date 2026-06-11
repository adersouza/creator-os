-- Move formerly browser-callable SECURITY DEFINER RPCs behind authenticated
-- Vercel API routes. Service-role routes now perform auth/ownership checks
-- before invoking these RPCs or equivalent service-role updates.
--
-- Clean replay may not include every historical RPC signature, so only alter
-- grants for functions present in pg_proc.

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
        ('assign_account_to_group', 'text, text, text'),
        ('get_aggregated_analytics', 'text, integer, text, text[]'),
        ('get_post_floor_aggregates', 'text, text[], timestamp with time zone, text'),
        ('mark_reply_as_read', 'uuid'),
        ('mark_all_replies_as_read', 'uuid')
    ) AS v(name, args)
  LOOP
    SELECT p.proname INTO fn_name
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname = target.name
      AND oidvectortypes(p.proargtypes) = target.args;

    IF fn_name IS NOT NULL THEN
      EXECUTE format('REVOKE EXECUTE ON FUNCTION public.%I(%s) FROM PUBLIC, anon, authenticated', target.name, target.args);
      EXECUTE format('GRANT EXECUTE ON FUNCTION public.%I(%s) TO service_role', target.name, target.args);
    END IF;
  END LOOP;
END $$;

COMMIT;
