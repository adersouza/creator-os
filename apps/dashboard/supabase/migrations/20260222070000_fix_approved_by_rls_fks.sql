-- Migration: fix_approved_by_rls_fks
-- Fixes: posts.approved_by type, smart_link_clicks RLS, workspace FK constraints, query indexes
-- Date: 2026-02-22

-- =============================================================================
-- 1. Fix posts.approved_by: UUID → TEXT
--    Missed in 20260222020000 (user_id_uuid_to_text) while rejected_by was fixed.
--    All user_id columns reference profiles(id) as TEXT, not auth.users(id) as UUID.
-- =============================================================================

ALTER TABLE posts DROP CONSTRAINT IF EXISTS posts_approved_by_fkey;
ALTER TABLE posts ALTER COLUMN approved_by TYPE text USING approved_by::text;
ALTER TABLE posts ADD CONSTRAINT posts_approved_by_fkey
  FOREIGN KEY (approved_by) REFERENCES profiles(id) ON DELETE SET NULL;

-- =============================================================================
-- 2. Add authenticated user SELECT policy for smart_link_clicks
--    Table has RLS enabled but only service_role policies.
--    Users need to read clicks on their own smart links for the dashboard widget.
-- =============================================================================

CREATE POLICY "Users read own clicks"
  ON smart_link_clicks
  FOR SELECT
  TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM smart_links sl
      WHERE sl.id = smart_link_clicks.smart_link_id
        AND sl.user_id = auth.uid()::text
    )
  );

-- =============================================================================
-- 3. Add FK constraints for workspace-scoped tables
--    These tables have workspace_id columns without foreign key constraints.
--    Using DO blocks with EXCEPTION handling for idempotency.
--    NOT NULL is intentionally omitted — existing rows may have NULLs.
-- =============================================================================

DO $$
BEGIN
  ALTER TABLE listening_results
    ADD CONSTRAINT listening_results_workspace_id_fkey
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE crisis_events
    ADD CONSTRAINT crisis_events_workspace_id_fkey
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TABLE influencer_collabs
    ADD CONSTRAINT influencer_collabs_workspace_id_fkey
      FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

-- =============================================================================
-- 4. Add composite indexes for query performance
-- =============================================================================

-- Composite index for smart_link_clicks analytics queries (revenue attribution dashboard)
CREATE INDEX IF NOT EXISTS idx_smart_link_clicks_link_time
  ON smart_link_clicks(smart_link_id, clicked_at DESC);

-- Partial index for active listening alerts (avoids scanning inactive rows)
CREATE INDEX IF NOT EXISTS idx_listening_alerts_workspace_active
  ON listening_alerts(workspace_id, is_active)
  WHERE is_active = true;
