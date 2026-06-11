-- ============================================================================
-- Drop overly-permissive link_clicks INSERT policy
--
-- "Anyone can insert clicks" used WITH CHECK(true) on {public}, allowing
-- any user (including anon) to insert arbitrary rows.
--
-- Click tracking is done server-side via api/link-page/track.ts using
-- service_role, which bypasses RLS. No client INSERT policy is needed.
-- The user SELECT policy ("Users view their own clicks") is preserved.
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.link_clicks') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Anyone can insert clicks" ON link_clicks;
  END IF;
END $$;
