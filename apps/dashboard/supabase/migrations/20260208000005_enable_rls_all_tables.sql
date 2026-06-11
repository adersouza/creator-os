-- ============================================================================
-- Enable RLS on all 34 remaining public tables
--
-- Clears the 62 security lint warnings. Policies use the optimized
-- (SELECT auth.uid()) pattern from the start.
--
-- service_role bypasses RLS automatically — backend API routes are unaffected.
-- ============================================================================

BEGIN;

-- ============================================================================
-- Step 1: ENABLE RLS on every table
-- ============================================================================

ALTER TABLE account_analytics    ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_groups       ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts             ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_config            ENABLE ROW LEVEL SECURITY;
ALTER TABLE auto_post_config     ENABLE ROW LEVEL SECURITY;
ALTER TABLE auto_post_queue      ENABLE ROW LEVEL SECURITY;
ALTER TABLE auto_post_state      ENABLE ROW LEVEL SECURITY;
ALTER TABLE auto_reply_rules     ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_posts     ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitor_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE competitors          ENABLE ROW LEVEL SECURITY;
ALTER TABLE creator_links        ENABLE ROW LEVEL SECURITY;
ALTER TABLE favorites            ENABLE ROW LEVEL SECURITY;
ALTER TABLE ig_comments          ENABLE ROW LEVEL SECURITY;
ALTER TABLE ig_endpoint_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE ig_mentions          ENABLE ROW LEVEL SECURITY;
ALTER TABLE ig_story_insights    ENABLE ROW LEVEL SECURITY;
ALTER TABLE listening_alerts     ENABLE ROW LEVEL SECURITY;
ALTER TABLE media                ENABLE ROW LEVEL SECURITY;
ALTER TABLE media_folders        ENABLE ROW LEVEL SECURITY;
ALTER TABLE mentions             ENABLE ROW LEVEL SECURITY;
ALTER TABLE post_replies         ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts                ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles             ENABLE ROW LEVEL SECURITY;
ALTER TABLE queue_slots          ENABLE ROW LEVEL SECURITY;
ALTER TABLE saved_competitor_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sent_replies         ENABLE ROW LEVEL SECURITY;
ALTER TABLE trial_emails         ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_preferences     ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_activity   ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_invites    ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_members    ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces           ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- Step 2A: Tables with user_id TEXT — direct ownership
-- (post_replies, sent_replies, workspace_members, workspaces already have
--  policies from earlier migrations — skip those)
-- ============================================================================

CREATE POLICY "Users manage own accounts"
  ON accounts FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own account groups"
  ON account_groups FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own AI config"
  ON ai_config FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own competitors"
  ON competitors FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own favorites"
  ON favorites FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own media"
  ON media FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own media folders"
  ON media_folders FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own mentions"
  ON mentions FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own posts"
  ON posts FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own queue slots"
  ON queue_slots FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own saved competitor posts"
  ON saved_competitor_posts FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own preferences"
  ON user_preferences FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Users manage own settings"
  ON user_settings FOR ALL
  USING ((SELECT auth.uid())::text = user_id);

-- workspace_activity: users can read own, backend inserts via service_role
CREATE POLICY "Users view own workspace activity"
  ON workspace_activity FOR SELECT
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- Step 2B: Special ownership patterns
-- ============================================================================

-- ig_mentions: user_id is UUID (not TEXT)
CREATE POLICY "Users manage own IG mentions"
  ON ig_mentions FOR ALL
  USING ((SELECT auth.uid()) = user_id);

-- profiles: id matches auth.users.id
CREATE POLICY "Users manage own profile"
  ON profiles FOR ALL
  USING ((SELECT auth.uid())::text = id);

-- ============================================================================
-- Step 2C: FK subquery policies — no direct user_id
-- ============================================================================

-- account_analytics → accounts.user_id
CREATE POLICY "Users access own account analytics"
  ON account_analytics FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM accounts
      WHERE accounts.id = account_analytics.account_id
        AND accounts.user_id = (SELECT auth.uid())::text
    )
  );

-- competitor_posts → competitors.user_id
CREATE POLICY "Users access own competitor posts"
  ON competitor_posts FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM competitors
      WHERE competitors.id = competitor_posts.competitor_id
        AND competitors.user_id = (SELECT auth.uid())::text
    )
  );

-- competitor_snapshots → competitors.user_id
CREATE POLICY "Users access own competitor snapshots"
  ON competitor_snapshots FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM competitors
      WHERE competitors.id = competitor_snapshots.competitor_id
        AND competitors.user_id = (SELECT auth.uid())::text
    )
  );

-- ig_comments → posts.user_id
CREATE POLICY "Users access own IG comments"
  ON ig_comments FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM posts
      WHERE posts.id = ig_comments.post_id
        AND posts.user_id = (SELECT auth.uid())::text
    )
  );

-- ============================================================================
-- Step 2D: Workspace-scoped tables — owner or member can read
-- ============================================================================

CREATE POLICY "Workspace members access config"
  ON auto_post_config FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM workspaces
      WHERE workspaces.id = auto_post_config.workspace_id
        AND (workspaces.owner_id = (SELECT auth.uid())::text
          OR is_workspace_member(workspaces.id, (SELECT auth.uid())::text))
    )
  );

CREATE POLICY "Workspace members access auto-reply rules"
  ON auto_reply_rules FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM workspaces
      WHERE workspaces.id = auto_reply_rules.workspace_id
        AND (workspaces.owner_id = (SELECT auth.uid())::text
          OR is_workspace_member(workspaces.id, (SELECT auth.uid())::text))
    )
  );

CREATE POLICY "Workspace members access creator links"
  ON creator_links FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM workspaces
      WHERE workspaces.id = creator_links.workspace_id
        AND (workspaces.owner_id = (SELECT auth.uid())::text
          OR is_workspace_member(workspaces.id, (SELECT auth.uid())::text))
    )
  );

CREATE POLICY "Workspace members access listening alerts"
  ON listening_alerts FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM workspaces
      WHERE workspaces.id = listening_alerts.workspace_id
        AND (workspaces.owner_id = (SELECT auth.uid())::text
          OR is_workspace_member(workspaces.id, (SELECT auth.uid())::text))
    )
  );

CREATE POLICY "Workspace members access invites"
  ON workspace_invites FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM workspaces
      WHERE workspaces.id = workspace_invites.workspace_id
        AND (workspaces.owner_id = (SELECT auth.uid())::text
          OR is_workspace_member(workspaces.id, (SELECT auth.uid())::text))
    )
  );

-- ============================================================================
-- Step 2E: Backend-only tables — no client policy
-- service_role bypasses RLS, authenticated/anon get zero access
-- ============================================================================

-- auto_post_queue    — cron worker + API only
-- auto_post_state    — cron state tracking only
-- ig_endpoint_rate_limits — API rate limit tracking only
-- ig_story_insights  — API route only (no user_id)
-- trial_emails       — internal system table (no user_id)

-- (No CREATE POLICY needed — RLS enabled with no policies = deny all for
--  authenticated/anon. service_role bypasses RLS automatically.)

COMMIT;
