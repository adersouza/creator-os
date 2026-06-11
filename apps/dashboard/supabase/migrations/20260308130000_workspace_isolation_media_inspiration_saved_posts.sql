-- Workspace isolation: media, inspiration_ideas, saved_competitor_posts
--
-- Context (2026-03-08): One user has 18 workspaces in production. Multi-workspace
-- usage is real, so this migration is necessary.
--
-- Strategy:
--   - media, saved_competitor_posts: ADD workspace_id TEXT nullable + index
--   - inspiration_ideas: workspace_id nullable already exists — RLS only
--   - All three tables: workspace-aware RLS following the listening_alerts pattern
--     (Fix 6A from 20260308110000).
--   - Existing rows keep workspace_id = NULL. The NULL branch in every policy
--     keeps them visible to their owner — no data is hidden by this migration.
--   - Write paths in application code set workspace_id = null until the UI layer
--     threads workspace context through (tracked separately).
-- ============================================================================

-- ============================================================================
-- media
-- ============================================================================

ALTER TABLE media
  ADD COLUMN IF NOT EXISTS workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_media_user_workspace
  ON media(user_id, workspace_id);

DROP POLICY IF EXISTS "Users manage own media" ON media;

CREATE POLICY "Users manage own media" ON media
  FOR ALL USING (
    user_id::text = (select auth.uid())::text
    AND (
      workspace_id IS NULL
      OR EXISTS (
        SELECT 1 FROM workspaces w
        WHERE w.id = media.workspace_id::text
          AND (
            w.owner_id = (select auth.uid())::text
            OR is_workspace_member(w.id, (select auth.uid())::text)
          )
      )
    )
  );

-- ============================================================================
-- inspiration_ideas  (workspace_id nullable already exists in production)
-- ============================================================================

DROP POLICY IF EXISTS "Users can manage own inspiration ideas" ON inspiration_ideas;
DROP POLICY IF EXISTS "Users manage own inspiration ideas" ON inspiration_ideas;

CREATE POLICY "Users manage own inspiration ideas" ON inspiration_ideas
  FOR ALL USING (
    user_id::text = (select auth.uid())::text
    AND (
      workspace_id IS NULL
      OR EXISTS (
        SELECT 1 FROM workspaces w
        WHERE w.id = inspiration_ideas.workspace_id::text
          AND (
            w.owner_id = (select auth.uid())::text
            OR is_workspace_member(w.id, (select auth.uid())::text)
          )
      )
    )
  );

-- ============================================================================
-- saved_competitor_posts
-- ============================================================================

ALTER TABLE saved_competitor_posts
  ADD COLUMN IF NOT EXISTS workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_saved_competitor_posts_user_workspace
  ON saved_competitor_posts(user_id, workspace_id);

DROP POLICY IF EXISTS "Users manage own saved competitor posts" ON saved_competitor_posts;

CREATE POLICY "Users manage own saved competitor posts" ON saved_competitor_posts
  FOR ALL USING (
    user_id::text = (select auth.uid())::text
    AND (
      workspace_id IS NULL
      OR EXISTS (
        SELECT 1 FROM workspaces w
        WHERE w.id = saved_competitor_posts.workspace_id::text
          AND (
            w.owner_id = (select auth.uid())::text
            OR is_workspace_member(w.id, (select auth.uid())::text)
          )
      )
    )
  );
