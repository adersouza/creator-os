-- Fix auth_rls_initplan warnings: wrap auth.uid() in (select ...) so Postgres
-- evaluates it once per query instead of once per row.
-- Affects 11 policies across 8 tables.

-- ============================================================
-- 1. referral_codes (2 policies)
-- ============================================================
DROP POLICY IF EXISTS "Users can create own referral codes" ON referral_codes;
CREATE POLICY "Users can create own referral codes"
    ON referral_codes FOR INSERT
    WITH CHECK ((select auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can update own referral codes" ON referral_codes;
CREATE POLICY "Users can update own referral codes"
    ON referral_codes FOR UPDATE
    USING ((select auth.uid())::text = user_id);

-- ============================================================
-- 2. smart_link_conversions (1 policy)
-- ============================================================
DROP POLICY IF EXISTS "users_read_own_conversions" ON smart_link_conversions;
CREATE POLICY "users_read_own_conversions"
    ON smart_link_conversions FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM smart_links sl
        WHERE sl.id = smart_link_conversions.smart_link_id
          AND sl.user_id = (select auth.uid())::text
    ));

-- ============================================================
-- 3. auto_post_state (3 policies)
-- ============================================================
DROP POLICY IF EXISTS "Users can read own auto_post_state" ON auto_post_state;
CREATE POLICY "Users can read own auto_post_state"
    ON auto_post_state FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = auto_post_state.workspace_id
          AND a.user_id = (select auth.uid())::text
    ));

DROP POLICY IF EXISTS "Users can insert own auto_post_state" ON auto_post_state;
CREATE POLICY "Users can insert own auto_post_state"
    ON auto_post_state FOR INSERT
    WITH CHECK (EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = auto_post_state.workspace_id
          AND a.user_id = (select auth.uid())::text
    ));

DROP POLICY IF EXISTS "Users can update own auto_post_state" ON auto_post_state;
CREATE POLICY "Users can update own auto_post_state"
    ON auto_post_state FOR UPDATE
    USING (EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = auto_post_state.workspace_id
          AND a.user_id = (select auth.uid())::text
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM accounts a
        WHERE a.id = auto_post_state.workspace_id
          AND a.user_id = (select auth.uid())::text
    ));

-- ============================================================
-- 4. influencer_collab_posts (1 policy)
-- ============================================================
DROP POLICY IF EXISTS "Users manage own collab posts" ON influencer_collab_posts;
CREATE POLICY "Users manage own collab posts"
    ON influencer_collab_posts FOR ALL
    USING (EXISTS (
        SELECT 1 FROM influencer_collabs ic
        WHERE ic.id = influencer_collab_posts.collab_id
          AND ic.user_id = (select auth.uid())::text
    ));

-- ============================================================
-- 5. listening_results (1 policy)
-- ============================================================
DROP POLICY IF EXISTS "Users can view own listening results" ON listening_results;
CREATE POLICY "Users can view own listening results"
    ON listening_results FOR SELECT
    USING (alert_id IN (
        SELECT listening_alerts.id FROM listening_alerts
        WHERE listening_alerts.user_id = (select auth.uid())::text
    ));

-- ============================================================
-- 6. rss_feeds (1 policy)
-- ============================================================
DROP POLICY IF EXISTS "Users manage own RSS feeds" ON rss_feeds;
CREATE POLICY "Users manage own RSS feeds"
    ON rss_feeds FOR ALL
    USING ((select auth.uid())::text = user_id);

-- ============================================================
-- 7. rss_entries (1 policy)
-- ============================================================
DROP POLICY IF EXISTS "Users manage own RSS entries" ON rss_entries;
CREATE POLICY "Users manage own RSS entries"
    ON rss_entries FOR ALL
    USING (EXISTS (
        SELECT 1 FROM rss_feeds rf
        WHERE rf.id = rss_entries.feed_id
          AND rf.user_id = (select auth.uid())::text
    ));

-- ============================================================
-- 8. trend_forecasts (1 policy)
-- ============================================================
DROP POLICY IF EXISTS "Users view own trend forecasts" ON trend_forecasts;
CREATE POLICY "Users view own trend forecasts"
    ON trend_forecasts FOR ALL
    USING ((select auth.uid())::text = user_id);
