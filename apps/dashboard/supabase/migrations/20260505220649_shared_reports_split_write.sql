-- ============================================================================
-- shared_reports: split ALL policy into write-only to deduplicate SELECT
-- ============================================================================
-- Date: 2026-05-05
-- "Public read by share token" (SELECT, qual=true) covers SELECT for own reports
-- already, so "Users manage own shared reports" (ALL) was duplicating SELECT
-- evaluation for authenticated owners. Split it into INSERT+UPDATE+DELETE only.
-- ============================================================================

BEGIN;

DROP POLICY IF EXISTS "Users manage own shared reports" ON public.shared_reports;

CREATE POLICY "shared_reports_owner_insert" ON public.shared_reports
  FOR INSERT TO authenticated
  WITH CHECK (((SELECT auth.uid()))::text = user_id);

CREATE POLICY "shared_reports_owner_update" ON public.shared_reports
  FOR UPDATE TO authenticated
  USING (((SELECT auth.uid()))::text = user_id)
  WITH CHECK (((SELECT auth.uid()))::text = user_id);

CREATE POLICY "shared_reports_owner_delete" ON public.shared_reports
  FOR DELETE TO authenticated
  USING (((SELECT auth.uid()))::text = user_id);

COMMIT;
