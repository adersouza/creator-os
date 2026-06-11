-- ============================================================================
-- Hard Database Rigor & Performance Optimization
-- Targets remaining Supabase Linter warnings:
-- 1. auth_rls_initplan: (SELECT auth.<func>())
-- 2. multiple_permissive_policies: Consolidation
-- 3. duplicate_index: Drop redundant indexes
-- ============================================================================

BEGIN;

-- ── 1. Consolidation of Multiple Permissive Policies ──

-- Table: public.audience_demographics
-- Merge threads and instagram policies into one (SELECT)
DROP POLICY IF EXISTS "Users can view own demographics via instagram" ON audience_demographics;
DROP POLICY IF EXISTS "Users can view own demographics via threads" ON audience_demographics;
DROP POLICY IF EXISTS "Users can view own demographics" ON audience_demographics;
DROP POLICY IF EXISTS "Users access own demographics" ON audience_demographics;
CREATE POLICY "Users access own demographics" ON audience_demographics
  FOR SELECT TO authenticated
  USING (
    account_id IN (SELECT id FROM accounts WHERE user_id = (SELECT auth.uid())::text)
    OR instagram_account_id IN (SELECT id FROM instagram_accounts WHERE user_id = (SELECT auth.uid())::text)
  );

-- Table: public.listening_alerts
-- Merge "Users manage own listening alerts" and "Workspace members access listening alerts"
DROP POLICY IF EXISTS "Users manage own listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Workspace members access listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Users access own listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Users access listening alerts" ON listening_alerts;
CREATE POLICY "Users access listening alerts" ON listening_alerts
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

-- Table: public.recommendation_dismissals
DROP POLICY IF EXISTS "Users can manage own dismissals" ON recommendation_dismissals;
DROP POLICY IF EXISTS "Manage own dismissals" ON recommendation_dismissals;
CREATE POLICY "Manage own dismissals" ON recommendation_dismissals
  FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- Table: public.referral_codes
DROP POLICY IF EXISTS "Anyone can validate referral codes" ON referral_codes;
DROP POLICY IF EXISTS "Users can read own referral codes" ON referral_codes;
DROP POLICY IF EXISTS "Read referral codes" ON referral_codes;
DROP POLICY IF EXISTS "Access referral codes" ON referral_codes;
CREATE POLICY "Access referral codes" ON referral_codes
  FOR SELECT TO public
  USING (is_active = true OR (SELECT auth.uid())::text = user_id);


-- ── 2. Fix auth_rls_initplan (Wrap all auth.uid() in SELECT) ──

-- post_success_signals
DROP POLICY IF EXISTS "Users own their signals" ON post_success_signals;
CREATE POLICY "Users own their signals" ON post_success_signals
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- referrals
DROP POLICY IF EXISTS "Users can read own referrals" ON referrals;
CREATE POLICY "Users can read own referrals" ON referrals
  FOR SELECT TO authenticated USING ((SELECT auth.uid())::text = referrer_id OR (SELECT auth.uid())::text = referred_id);

DROP POLICY IF EXISTS "Users can create referrals as referred" ON referrals;
CREATE POLICY "Users can create referrals as referred" ON referrals
  FOR INSERT TO authenticated WITH CHECK ((SELECT auth.uid())::text = referred_id);

-- style_bibles
DROP POLICY IF EXISTS "Users can manage own style bibles" ON style_bibles;
CREATE POLICY "Users can manage own style bibles" ON style_bibles
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id) WITH CHECK ((SELECT auth.uid())::text = user_id);

-- copilot_memory
DROP POLICY IF EXISTS "Users own their copilot memory" ON copilot_memory;
CREATE POLICY "Users own their copilot memory" ON copilot_memory
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id) WITH CHECK ((SELECT auth.uid())::text = user_id);

-- creator_events
DROP POLICY IF EXISTS "Users can view their own creator events" ON creator_events;
CREATE POLICY "Users can view their own creator events" ON creator_events
  FOR SELECT TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- crisis_events
DROP POLICY IF EXISTS "Users can view own crisis events" ON crisis_events;
CREATE POLICY "Users can view own crisis events" ON crisis_events
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- feature_usage
DROP POLICY IF EXISTS "Users own their usage" ON feature_usage;
CREATE POLICY "Users own their usage" ON feature_usage
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- ai_feedback
DROP POLICY IF EXISTS "Users own their feedback" ON ai_feedback;
CREATE POLICY "Users own their feedback" ON ai_feedback
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- post_metric_history
DROP POLICY IF EXISTS "Users can view own post history" ON post_metric_history;
CREATE POLICY "Users can view own post history" ON post_metric_history
  FOR SELECT TO authenticated USING (account_id IN (SELECT id FROM accounts WHERE user_id = (SELECT auth.uid())::text));

-- agency_branding
DROP POLICY IF EXISTS "Users manage own branding" ON agency_branding;
CREATE POLICY "Users manage own branding" ON agency_branding
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- anomaly_alerts
DROP POLICY IF EXISTS "Users can view own alerts" ON anomaly_alerts;
CREATE POLICY "Users can view own alerts" ON anomaly_alerts
  FOR SELECT TO authenticated USING ((SELECT auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can dismiss own alerts" ON anomaly_alerts;
CREATE POLICY "Users can dismiss own alerts" ON anomaly_alerts
  FOR UPDATE TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- api_keys
DROP POLICY IF EXISTS "Users manage own API keys" ON api_keys;
CREATE POLICY "Users manage own API keys" ON api_keys
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- post_reflections
DROP POLICY IF EXISTS "Users can read their own reflections" ON post_reflections;
CREATE POLICY "Users can read their own reflections" ON post_reflections
  FOR SELECT TO authenticated USING ((SELECT auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can insert their own reflections" ON post_reflections;
CREATE POLICY "Users can insert their own reflections" ON post_reflections
  FOR INSERT TO authenticated WITH CHECK ((SELECT auth.uid())::text = user_id);

-- influencer_collabs
DROP POLICY IF EXISTS "Users manage own collabs" ON influencer_collabs;
CREATE POLICY "Users manage own collabs" ON influencer_collabs
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- viral_score_calibration
DROP POLICY IF EXISTS "Users can view own calibration data" ON viral_score_calibration;
CREATE POLICY "Users can view own calibration data" ON viral_score_calibration
  FOR SELECT TO authenticated USING ((SELECT auth.uid())::text = user_id);

-- webhook_subscriptions
DROP POLICY IF EXISTS "Users can manage own webhooks" ON webhook_subscriptions;
CREATE POLICY "Users can manage own webhooks" ON webhook_subscriptions
  FOR ALL TO authenticated USING ((SELECT auth.uid())::text = user_id);


-- ── 3. Drop Duplicate Indexes ──

-- idx_analytics_account_date is identical to idx_account_analytics_account_date
DROP INDEX IF EXISTS public.idx_analytics_account_date;

COMMIT;
