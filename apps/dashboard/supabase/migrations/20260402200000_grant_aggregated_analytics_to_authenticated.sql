-- Fix: get_aggregated_analytics was revoked from authenticated in 20260325100000
-- but the frontend calls it via supabase.rpc() which uses the authenticated role.
-- The function already has an auth.uid() guard (added in the same migration),
-- so granting back to authenticated is safe — no IDOR risk.

GRANT EXECUTE ON FUNCTION public.get_aggregated_analytics(TEXT, INTEGER, TEXT, TEXT[]) TO authenticated;
