-- ============================================================================
-- Fix Supabase database linter warnings (2026-02-23)
--
-- 1. auth_rls_initplan: Wrap auth.uid() with (SELECT auth.uid()) in 33 policies
--    across 24 tables. This makes PostgreSQL evaluate the function once as a
--    subquery instead of re-evaluating per row.
--
-- 2. multiple_permissive_policies: Merge duplicate/overlapping policies on:
--    - recommendation_dismissals (2 near-identical policies → 1)
--    - listening_alerts (user_id + workspace → combined OR)
--    - audience_demographics (2 SELECT policies → 1 combined)
--    - referral_codes (2 SELECT policies → 1 combined)
--    - viral_score_calibration (already fixed in 20260223000000)
--
-- 3. duplicate_index: Drop idx_analytics_account_date (duplicate of
--    idx_account_analytics_account_date on account_analytics)
--
-- All policies scoped TO authenticated (not public) since auth.uid() is
-- required. Anon users get NULL from auth.uid() → USING returns false anyway.
-- Exception: referral_codes SELECT stays TO public for anonymous validation.
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. post_success_signals
-- ============================================================================
DROP POLICY IF EXISTS "Users own their signals" ON post_success_signals;
CREATE POLICY "Users own their signals" ON post_success_signals
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 2. recommendation_dismissals — also fixes multiple_permissive
--    Had two nearly identical policies: "Users can manage own dismissals"
--    and "Users manage own dismissals". Merge into one.
-- ============================================================================
DROP POLICY IF EXISTS "Users can manage own dismissals" ON recommendation_dismissals;
DROP POLICY IF EXISTS "Users manage own dismissals" ON recommendation_dismissals;
CREATE POLICY "Users manage own dismissals" ON recommendation_dismissals
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 3. referrals
-- ============================================================================
DROP POLICY IF EXISTS "Users can create referrals as referred" ON referrals;
CREATE POLICY "Users can create referrals as referred" ON referrals
  FOR INSERT TO authenticated
  WITH CHECK ((SELECT auth.uid())::text = referred_id);

DROP POLICY IF EXISTS "Users can read own referrals" ON referrals;
CREATE POLICY "Users can read own referrals" ON referrals
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid())::text = referrer_id OR (SELECT auth.uid())::text = referred_id);

-- ============================================================================
-- 4. referral_codes — also fixes multiple_permissive
--    Had "Anyone can validate referral codes" (SELECT, is_active) and
--    "Users can read own referral codes" (SELECT, user_id). Merge into one
--    SELECT policy: active codes visible to all, own codes visible to owner.
-- ============================================================================
DROP POLICY IF EXISTS "Anyone can validate referral codes" ON referral_codes;
DROP POLICY IF EXISTS "Users can read own referral codes" ON referral_codes;
CREATE POLICY "Read referral codes" ON referral_codes
  FOR SELECT TO public
  USING (is_active = true OR (SELECT auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can create own referral codes" ON referral_codes;
CREATE POLICY "Users can create own referral codes" ON referral_codes
  FOR INSERT TO authenticated
  WITH CHECK ((SELECT auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can update own referral codes" ON referral_codes;
CREATE POLICY "Users can update own referral codes" ON referral_codes
  FOR UPDATE TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 5. style_bibles
-- ============================================================================
DROP POLICY IF EXISTS "Users can manage own style bibles" ON style_bibles;
CREATE POLICY "Users can manage own style bibles" ON style_bibles
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 6. audience_demographics — also fixes multiple_permissive
--    Had two SELECT policies (via instagram + via threads). Merge into one.
-- ============================================================================
DROP POLICY IF EXISTS "Users can view own demographics via instagram" ON audience_demographics;
DROP POLICY IF EXISTS "Users can view own demographics via threads" ON audience_demographics;
CREATE POLICY "Users can view own demographics" ON audience_demographics
  FOR SELECT TO authenticated
  USING (
    account_id IN (SELECT id FROM accounts WHERE user_id = (SELECT auth.uid())::text)
    OR instagram_account_id IN (SELECT id FROM instagram_accounts WHERE user_id = (SELECT auth.uid())::text)
  );

-- ============================================================================
-- 7. copilot_memory
-- ============================================================================
DROP POLICY IF EXISTS "Users own their copilot memory" ON copilot_memory;
CREATE POLICY "Users own their copilot memory" ON copilot_memory
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 8. creator_events
-- ============================================================================
DROP POLICY IF EXISTS "Users can view their own creator events" ON creator_events;
CREATE POLICY "Users can view their own creator events" ON creator_events
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 9. smart_link_conversions
-- ============================================================================
DROP POLICY IF EXISTS "users_read_own_conversions" ON smart_link_conversions;
CREATE POLICY "users_read_own_conversions" ON smart_link_conversions
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM smart_links sl
      WHERE sl.id = smart_link_conversions.smart_link_id
        AND sl.user_id = (SELECT auth.uid())::text
    )
  );

-- ============================================================================
-- 10. crisis_events
-- ============================================================================
DROP POLICY IF EXISTS "Users can view own crisis events" ON crisis_events;
CREATE POLICY "Users can view own crisis events" ON crisis_events
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 11. feature_usage
-- ============================================================================
DROP POLICY IF EXISTS "Users own their usage" ON feature_usage;
CREATE POLICY "Users own their usage" ON feature_usage
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 12. auto_post_state (3 policies)
-- ============================================================================
DROP POLICY IF EXISTS "Users can read own auto_post_state" ON auto_post_state;
CREATE POLICY "Users can read own auto_post_state" ON auto_post_state
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM accounts a
      WHERE a.id::text = auto_post_state.workspace_id
        AND a.user_id = (SELECT auth.uid())::text
    )
  );

DROP POLICY IF EXISTS "Users can insert own auto_post_state" ON auto_post_state;
CREATE POLICY "Users can insert own auto_post_state" ON auto_post_state
  FOR INSERT TO authenticated
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM accounts a
      WHERE a.id::text = auto_post_state.workspace_id
        AND a.user_id = (SELECT auth.uid())::text
    )
  );

DROP POLICY IF EXISTS "Users can update own auto_post_state" ON auto_post_state;
CREATE POLICY "Users can update own auto_post_state" ON auto_post_state
  FOR UPDATE TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM accounts a
      WHERE a.id::text = auto_post_state.workspace_id
        AND a.user_id = (SELECT auth.uid())::text
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM accounts a
      WHERE a.id::text = auto_post_state.workspace_id
        AND a.user_id = (SELECT auth.uid())::text
    )
  );

-- ============================================================================
-- 13. ai_feedback
-- ============================================================================
DROP POLICY IF EXISTS "Users own their feedback" ON ai_feedback;
CREATE POLICY "Users own their feedback" ON ai_feedback
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 14. post_metric_history
-- ============================================================================
DROP POLICY IF EXISTS "Users can view own post history" ON post_metric_history;
CREATE POLICY "Users can view own post history" ON post_metric_history
  FOR SELECT TO authenticated
  USING (
    account_id IN (SELECT id FROM accounts WHERE user_id = (SELECT auth.uid())::text)
  );

-- ============================================================================
-- 15. agency_branding
-- ============================================================================
DROP POLICY IF EXISTS "Users manage own branding" ON agency_branding;
CREATE POLICY "Users manage own branding" ON agency_branding
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 16. anomaly_alerts (2 policies)
-- ============================================================================
DROP POLICY IF EXISTS "Users can view own alerts" ON anomaly_alerts;
CREATE POLICY "Users can view own alerts" ON anomaly_alerts
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can dismiss own alerts" ON anomaly_alerts;
CREATE POLICY "Users can dismiss own alerts" ON anomaly_alerts
  FOR UPDATE TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 17. api_keys
-- ============================================================================
DROP POLICY IF EXISTS "Users manage own API keys" ON api_keys;
CREATE POLICY "Users manage own API keys" ON api_keys
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 18. post_reflections (2 policies)
-- ============================================================================
DROP POLICY IF EXISTS "Users can read their own reflections" ON post_reflections;
CREATE POLICY "Users can read their own reflections" ON post_reflections
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can insert their own reflections" ON post_reflections;
CREATE POLICY "Users can insert their own reflections" ON post_reflections
  FOR INSERT TO authenticated
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 19. influencer_collabs
-- ============================================================================
DROP POLICY IF EXISTS "Users manage own collabs" ON influencer_collabs;
CREATE POLICY "Users manage own collabs" ON influencer_collabs
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 20. influencer_collab_posts
-- ============================================================================
DROP POLICY IF EXISTS "Users manage own collab posts" ON influencer_collab_posts;
CREATE POLICY "Users manage own collab posts" ON influencer_collab_posts
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM influencer_collabs ic
      WHERE ic.id = influencer_collab_posts.collab_id
        AND ic.user_id = (SELECT auth.uid())::text
    )
  );

-- ============================================================================
-- 21. listening_alerts — also fixes multiple_permissive
--     Had "Users manage own listening alerts" (user_id check, FOR ALL) and
--     "Workspace members access listening alerts" (workspace subquery, FOR ALL).
--     Merge into one policy with OR.
-- ============================================================================
DROP POLICY IF EXISTS "Users manage own listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Workspace members access listening alerts" ON listening_alerts;
CREATE POLICY "Users access own listening alerts" ON listening_alerts
  FOR ALL TO authenticated
  USING (
    (SELECT auth.uid())::text = user_id
    OR EXISTS (
      SELECT 1 FROM workspaces
      WHERE workspaces.id = listening_alerts.workspace_id
        AND (workspaces.owner_id = (SELECT auth.uid())::text
             OR is_workspace_member(workspaces.id, (SELECT auth.uid())::text))
    )
  );

-- ============================================================================
-- 22. listening_results
-- ============================================================================
DROP POLICY IF EXISTS "Users can view own listening results" ON listening_results;
CREATE POLICY "Users can view own listening results" ON listening_results
  FOR SELECT TO authenticated
  USING (
    alert_id IN (
      SELECT id FROM listening_alerts
      WHERE user_id = (SELECT auth.uid())::text
    )
  );

-- ============================================================================
-- 23. viral_score_calibration
--     Note: "Service role can manage calibration data" already fixed in
--     20260223000000_fix_linter_warnings.sql (changed TO service_role).
-- ============================================================================
DROP POLICY IF EXISTS "Users can view own calibration data" ON viral_score_calibration;
CREATE POLICY "Users can view own calibration data" ON viral_score_calibration
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- 24. webhook_subscriptions
-- ============================================================================
DROP POLICY IF EXISTS "Users can manage own webhooks" ON webhook_subscriptions;
CREATE POLICY "Users can manage own webhooks" ON webhook_subscriptions
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- PART 2: Drop duplicate index
-- idx_analytics_account_date is identical to idx_account_analytics_account_date
-- Both index account_analytics(account_id, date DESC).
-- ============================================================================
DROP INDEX IF EXISTS idx_analytics_account_date;

COMMIT;
