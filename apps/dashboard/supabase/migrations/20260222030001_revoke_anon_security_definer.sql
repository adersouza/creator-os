-- Revoke anon access to SECURITY DEFINER workspace functions
-- These functions bypass RLS and should only be callable by authenticated users.
-- Previously granted to anon in 20260214000001_fix_workspace_rls_recursion.sql

REVOKE EXECUTE ON FUNCTION public.is_workspace_member(TEXT, TEXT) FROM anon;
REVOKE EXECUTE ON FUNCTION public.is_workspace_owner(TEXT, TEXT) FROM anon;
