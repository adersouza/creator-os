-- Harden service-role-only RPC grants that live advisors still reported as
-- callable by anon/authenticated roles after earlier function rewrites.
--
-- Clean replay may not include every production RPC signature, so revoke/grant
-- only signatures present in pg_proc.

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
        ('create_smart_link_with_quota', 'text, integer, jsonb'),
        ('create_link_page_with_quota', 'text, integer, jsonb'),
        ('create_link_item_with_quota', 'text, uuid, integer, jsonb'),
        ('smart_link_analytics', 'uuid, timestamp with time zone, text'),
        ('record_variant_impression', 'uuid'),
        ('record_variant_click', 'uuid')
    ) AS v(name, args)
  LOOP
    SELECT p.proname INTO fn_name
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname = target.name
      AND oidvectortypes(p.proargtypes) = target.args;

    IF fn_name IS NOT NULL THEN
      EXECUTE format('REVOKE EXECUTE ON FUNCTION public.%I(%s) FROM PUBLIC', target.name, target.args);
      EXECUTE format('REVOKE EXECUTE ON FUNCTION public.%I(%s) FROM anon, authenticated', target.name, target.args);
      EXECUTE format('GRANT EXECUTE ON FUNCTION public.%I(%s) TO service_role', target.name, target.args);
    END IF;
  END LOOP;
END $$;

COMMIT;
