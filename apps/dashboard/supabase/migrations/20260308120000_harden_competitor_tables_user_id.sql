-- Harden competitor_top_posts and competitor_snapshots: add user_id column
--
-- Problem: Neither table has a user_id column. Security relies entirely on an
-- EXISTS subquery that joins through competitors.user_id. If the competitors
-- RLS chain is weakened by any future policy change, both tables are exposed.
-- Additionally, competitor_top_posts is missing UPDATE and DELETE policies.
--
-- Fix:
--   1. Add user_id TEXT column to both tables (nullable for safe backfill)
--   2. Backfill user_id from the parent competitors table (idempotent)
--   3. Add direct user_id check to all RLS policies (defense in depth)
--   4. Keep existing EXISTS chain as a second layer
--   5. Add missing UPDATE + DELETE policies on competitor_top_posts
--
-- No data is at risk: the backfill is a read-only copy from competitors.
-- Existing rows with NULL user_id (if any remain after backfill) are still
-- reachable via the EXISTS chain.
-- ============================================================================

-- ============================================================================
-- competitor_top_posts
-- ============================================================================

ALTER TABLE competitor_top_posts
  ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE;

-- Backfill user_id from parent competitors row (idempotent via WHERE NULL)
DO $$
DECLARE
  user_id_type TEXT;
BEGIN
  SELECT data_type INTO user_id_type
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND table_name = 'competitor_top_posts'
    AND column_name = 'user_id';

  IF user_id_type = 'uuid' THEN
    UPDATE competitor_top_posts ctp
    SET user_id = c.user_id::uuid
    FROM competitors c
    WHERE ctp.competitor_id::text = c.id
      AND ctp.user_id IS NULL
      AND c.user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
  ELSIF user_id_type IS NOT NULL THEN
    UPDATE competitor_top_posts ctp
    SET user_id = c.user_id
    FROM competitors c
    WHERE ctp.competitor_id::text = c.id
      AND ctp.user_id IS NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_user_id
  ON competitor_top_posts(user_id);

-- Drop all existing policies and replace with hardened versions
DROP POLICY IF EXISTS "Users can view competitor top posts" ON competitor_top_posts;
DROP POLICY IF EXISTS "Users can insert competitor top posts" ON competitor_top_posts;
DROP POLICY IF EXISTS "Users can update competitor top posts" ON competitor_top_posts;
DROP POLICY IF EXISTS "Users can delete competitor top posts" ON competitor_top_posts;

-- Defense-in-depth: direct user_id check AND EXISTS chain through competitors.
-- user_id IS NULL fallback keeps any un-backfilled legacy rows accessible
-- via the EXISTS chain alone.

CREATE POLICY "Users can view competitor top posts" ON competitor_top_posts
  FOR SELECT USING (
    (user_id IS NOT NULL AND user_id::text = (select auth.uid())::text)
    OR EXISTS (
      SELECT 1 FROM competitors
      WHERE competitors.id = competitor_top_posts.competitor_id::text
        AND competitors.user_id = (select auth.uid())::text
    )
  );

CREATE POLICY "Users can insert competitor top posts" ON competitor_top_posts
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM competitors
      WHERE competitors.id = competitor_top_posts.competitor_id::text
        AND competitors.user_id = (select auth.uid())::text
    )
  );

-- Previously missing: UPDATE policy
CREATE POLICY "Users can update competitor top posts" ON competitor_top_posts
  FOR UPDATE USING (
    (user_id IS NOT NULL AND user_id::text = (select auth.uid())::text)
    OR EXISTS (
      SELECT 1 FROM competitors
      WHERE competitors.id = competitor_top_posts.competitor_id::text
        AND competitors.user_id = (select auth.uid())::text
    )
  );

-- Previously missing: DELETE policy
CREATE POLICY "Users can delete competitor top posts" ON competitor_top_posts
  FOR DELETE USING (
    (user_id IS NOT NULL AND user_id::text = (select auth.uid())::text)
    OR EXISTS (
      SELECT 1 FROM competitors
      WHERE competitors.id = competitor_top_posts.competitor_id::text
        AND competitors.user_id = (select auth.uid())::text
    )
  );

-- ============================================================================
-- competitor_snapshots
-- ============================================================================

ALTER TABLE competitor_snapshots
  ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE;

-- Backfill user_id from parent competitors row (idempotent)
DO $$
DECLARE
  user_id_type TEXT;
BEGIN
  SELECT data_type INTO user_id_type
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND table_name = 'competitor_snapshots'
    AND column_name = 'user_id';

  IF user_id_type = 'uuid' THEN
    UPDATE competitor_snapshots cs
    SET user_id = c.user_id::uuid
    FROM competitors c
    WHERE cs.competitor_id::text = c.id
      AND cs.user_id IS NULL
      AND c.user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
  ELSIF user_id_type IS NOT NULL THEN
    UPDATE competitor_snapshots cs
    SET user_id = c.user_id
    FROM competitors c
    WHERE cs.competitor_id::text = c.id
      AND cs.user_id IS NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_competitor_snapshots_user_id
  ON competitor_snapshots(user_id);

DROP POLICY IF EXISTS "Users access own competitor snapshots" ON competitor_snapshots;
DROP POLICY IF EXISTS "Users can view competitor snapshots" ON competitor_snapshots;
DROP POLICY IF EXISTS "Users can insert competitor snapshots" ON competitor_snapshots;

CREATE POLICY "Users access own competitor snapshots" ON competitor_snapshots
  FOR ALL USING (
    (user_id IS NOT NULL AND user_id::text = (select auth.uid())::text)
    OR EXISTS (
      SELECT 1 FROM competitors
      WHERE competitors.id = competitor_snapshots.competitor_id::text
        AND competitors.user_id = (select auth.uid())::text
    )
  );
