-- ============================================================================
-- Revoke EXECUTE on analyze_small_tables() from PUBLIC
-- ============================================================================
-- Date: 2026-05-05
-- Migration 20260502193000 created analyze_small_tables() as SECURITY DEFINER
-- with GRANT TO service_role but never revoked the implicit PUBLIC grant.
-- Postgres grants EXECUTE to PUBLIC by default on function creation, so anon
-- and authenticated could call this RPC. Revoke it.
-- ============================================================================

BEGIN;

REVOKE EXECUTE ON FUNCTION public.analyze_small_tables() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.analyze_small_tables() FROM anon;
REVOKE EXECUTE ON FUNCTION public.analyze_small_tables() FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.analyze_small_tables() TO service_role;

COMMIT;
