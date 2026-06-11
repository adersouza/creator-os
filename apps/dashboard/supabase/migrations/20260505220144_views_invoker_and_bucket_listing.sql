-- ============================================================================
-- security_definer_view + public_bucket_allows_listing
-- ============================================================================
-- Date: 2026-05-05
--
-- 1. security_definer_view: 4 views run with creator's privileges, bypassing RLS
--    on underlying tables. All four are simple SELECT projections — switching to
--    security_invoker makes them respect the underlying table's RLS policies.
--    Also revoke SELECT from anon (these views don't need anonymous access).
--
-- 2. public_bucket_allows_listing: media + post-media buckets have broad SELECT
--    policies that let any role enumerate the entire bucket. Public buckets in
--    Supabase serve files via direct URL without needing SELECT on storage.objects;
--    these policies only enable LIST. Dropping them blocks anonymous enumeration
--    while preserving direct-URL reads (because bucket.public = true).
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. Views — switch to SECURITY INVOKER, revoke anon SELECT
-- ============================================================================

ALTER VIEW public.export_jobs SET (security_invoker = true);
REVOKE SELECT ON public.export_jobs FROM anon;

ALTER VIEW public.exports SET (security_invoker = true);
REVOKE SELECT ON public.exports FROM anon;

ALTER VIEW public.instagram_competitors SET (security_invoker = true);
REVOKE SELECT ON public.instagram_competitors FROM anon;

ALTER VIEW public.instagram_posts SET (security_invoker = true);
REVOKE SELECT ON public.instagram_posts FROM anon;

-- ============================================================================
-- 2. Storage — drop broad-SELECT policies; URL access keeps working
-- ============================================================================

DROP POLICY IF EXISTS "Public read access for media" ON storage.objects;
DROP POLICY IF EXISTS "Public read access for post-media" ON storage.objects;

COMMIT;
