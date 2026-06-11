-- Harden the analytics atomic upsert RPC after the v6 function rewrite.
-- The API calls this through the service-role Supabase client, so direct
-- client/anon execution is unnecessary.

BEGIN;

ALTER FUNCTION public.upsert_account_analytics_atomic(jsonb, jsonb)
  SET search_path = public;

REVOKE EXECUTE ON FUNCTION public.upsert_account_analytics_atomic(jsonb, jsonb) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.upsert_account_analytics_atomic(jsonb, jsonb) FROM anon;
REVOKE EXECUTE ON FUNCTION public.upsert_account_analytics_atomic(jsonb, jsonb) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_account_analytics_atomic(jsonb, jsonb) TO service_role;

COMMIT;
