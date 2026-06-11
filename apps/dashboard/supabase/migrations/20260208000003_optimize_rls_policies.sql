-- Historical RLS policy optimization migration.
--
-- This migration originally rewrote policies to wrap auth.uid()/auth.jwt()
-- calls in SELECTs for planner caching. In production it ran against tables
-- that already existed, but fresh branch replay reaches this version before
-- some of those tables are created. The rewrite is performance-only and later
-- migrations create the required policies, so keep branch replay idempotent.

DO $$
BEGIN
  NULL;
END $$;
