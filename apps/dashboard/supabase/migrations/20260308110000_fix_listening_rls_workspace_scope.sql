-- Fix RLS workspace isolation on listening_alerts and listening_results
--
-- Problem: Both tables have a workspace_id column (with FK to workspaces), but
-- the RLS policies only check user_id = auth.uid()::text. A user with two
-- workspaces can see alerts from workspace A while operating in workspace B.
--
-- Fix strategy:
--   - listening_alerts: user_id check + workspace membership (NULL workspace_id =
--     legacy rows created before workspace support — always visible to their owner).
--   - listening_results: inherits workspace scope by joining through listening_alerts.
--
-- Backward compatibility: workspace_id IS NULL rows remain visible to their owner.
-- No schema changes — the column already exists on both tables.
-- ============================================================================

-- ============================================================================
-- listening_alerts
-- ============================================================================

DROP POLICY IF EXISTS "Users can manage own listening alerts" ON listening_alerts;

CREATE POLICY "Users manage own listening alerts" ON listening_alerts
  FOR ALL USING (
    user_id = (select auth.uid())::text
    AND (
      workspace_id IS NULL
      OR EXISTS (
        SELECT 1 FROM workspaces w
        WHERE w.id = listening_alerts.workspace_id
          AND (
            w.owner_id = (select auth.uid())::text
            OR is_workspace_member(w.id, (select auth.uid())::text)
          )
      )
    )
  );

-- ============================================================================
-- listening_results
-- ============================================================================
-- listening_results has its own workspace_id column but no user_id column.
-- Ownership is established through the FK to listening_alerts.
-- The SELECT policy must verify both user ownership and workspace membership.
-- ============================================================================

DROP POLICY IF EXISTS "Users can view own listening results" ON listening_results;

CREATE POLICY "Users view own listening results" ON listening_results
  FOR SELECT USING (
    alert_id IN (
      SELECT la.id
      FROM listening_alerts la
      WHERE la.user_id = (select auth.uid())::text
        AND (
          la.workspace_id IS NULL
          OR EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.id = la.workspace_id
              AND (
                w.owner_id = (select auth.uid())::text
                OR is_workspace_member(w.id, (select auth.uid())::text)
              )
          )
        )
    )
  );
