-- ============================================================================
-- Fix SECURITY DEFINER on dead_letter_items view
--
-- In Postgres 15+, views without security_invoker=true run with the view
-- owner's permissions (SECURITY DEFINER), bypassing the caller's RLS.
-- Since this view reads from 4 backend-only tables (no client policies),
-- changing to SECURITY INVOKER means:
--   - service_role: still sees everything (bypasses RLS)
--   - authenticated/anon: gets zero rows (correct — admin-only view)
-- ============================================================================

DO $$
BEGIN
  IF to_regclass('public.dead_letter_items') IS NOT NULL THEN
    ALTER VIEW public.dead_letter_items SET (security_invoker = true);
  END IF;
END $$;
