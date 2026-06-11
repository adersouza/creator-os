-- Standardize all user_id columns from UUID (FK auth.users) to TEXT (FK profiles)
--
-- profiles.id is TEXT. auth.users.id is UUID.
-- These 22 tables had user_id UUID REFERENCES auth.users(id).
-- Converting to user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE.
--
-- Pattern per table:
--   1. Drop RLS policies that reference user_id
--   2. Drop FK to auth.users
--   3. ALTER COLUMN user_id TYPE text
--   4. Add FK to profiles(id) ON DELETE CASCADE
--   5. Recreate RLS policies with auth.uid()::text cast

BEGIN;

-- ══════════════════════════════════════════════
-- 1. agency_branding
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users manage own branding" ON agency_branding;
ALTER TABLE agency_branding DROP CONSTRAINT IF EXISTS agency_branding_user_id_fkey;
ALTER TABLE agency_branding ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE agency_branding ADD CONSTRAINT agency_branding_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users manage own branding" ON agency_branding FOR ALL TO public USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 2. anomaly_alerts
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can dismiss own alerts" ON anomaly_alerts;
DROP POLICY IF EXISTS "Users can view own alerts" ON anomaly_alerts;
ALTER TABLE anomaly_alerts DROP CONSTRAINT IF EXISTS anomaly_alerts_user_id_fkey;
ALTER TABLE anomaly_alerts ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE anomaly_alerts ADD CONSTRAINT anomaly_alerts_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can dismiss own alerts" ON anomaly_alerts FOR UPDATE TO public USING (auth.uid()::text = user_id);
CREATE POLICY "Users can view own alerts" ON anomaly_alerts FOR SELECT TO public USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 3. api_keys
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users manage own API keys" ON api_keys;
ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_user_id_fkey;
ALTER TABLE api_keys ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE api_keys ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users manage own API keys" ON api_keys FOR ALL TO public USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 4. competitor_alerts
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can update own alerts" ON competitor_alerts;
DROP POLICY IF EXISTS "Users can view own alerts" ON competitor_alerts;
ALTER TABLE competitor_alerts DROP CONSTRAINT IF EXISTS competitor_alerts_user_id_fkey;
ALTER TABLE competitor_alerts ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE competitor_alerts ADD CONSTRAINT competitor_alerts_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can update own alerts" ON competitor_alerts FOR UPDATE TO public USING ((SELECT auth.uid())::text = user_id);
CREATE POLICY "Users can view own alerts" ON competitor_alerts FOR SELECT TO public USING ((SELECT auth.uid())::text = user_id);

-- ══════════════════════════════════════════════
-- 5. copilot_memory
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users own their copilot memory" ON copilot_memory;
ALTER TABLE copilot_memory DROP CONSTRAINT IF EXISTS copilot_memory_user_id_fkey;
ALTER TABLE copilot_memory ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE copilot_memory ADD CONSTRAINT copilot_memory_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users own their copilot memory" ON copilot_memory FOR ALL TO public USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 6. creator_events
-- ══════════════════════════════════════════════
-- Service role policies don't reference user_id but drop/recreate for safety
DROP POLICY IF EXISTS "Service role can insert creator events" ON creator_events;
DROP POLICY IF EXISTS "Service role can update creator events" ON creator_events;
DROP POLICY IF EXISTS "Users can view their own creator events" ON creator_events;
ALTER TABLE creator_events DROP CONSTRAINT IF EXISTS creator_events_user_id_fkey;
ALTER TABLE creator_events ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE creator_events ADD CONSTRAINT creator_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Service role can insert creator events" ON creator_events FOR INSERT TO service_role WITH CHECK (true);
CREATE POLICY "Service role can update creator events" ON creator_events FOR UPDATE TO service_role USING (true);
CREATE POLICY "Users can view their own creator events" ON creator_events FOR SELECT TO authenticated USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 7. crisis_events
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can view own crisis events" ON crisis_events;
ALTER TABLE crisis_events DROP CONSTRAINT IF EXISTS crisis_events_user_id_fkey;
ALTER TABLE crisis_events ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE crisis_events ADD CONSTRAINT crisis_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can view own crisis events" ON crisis_events FOR ALL TO public USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 8. feature_usage
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users own their usage" ON feature_usage;
ALTER TABLE feature_usage DROP CONSTRAINT IF EXISTS feature_usage_user_id_fkey;
ALTER TABLE feature_usage ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE feature_usage ADD CONSTRAINT feature_usage_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users own their usage" ON feature_usage FOR ALL TO public USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 9. ig_auto_responders
--    Cross-dep: ig_auto_response_log policies JOIN to ig_auto_responders.user_id
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "rls_user_ig_auto_responders" ON ig_auto_responders;
ALTER TABLE ig_auto_responders DROP CONSTRAINT IF EXISTS ig_auto_responders_user_id_fkey;
ALTER TABLE ig_auto_responders ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE ig_auto_responders ADD CONSTRAINT ig_auto_responders_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "rls_user_ig_auto_responders" ON ig_auto_responders FOR ALL TO public USING ((SELECT auth.uid())::text = user_id);
DO $$
BEGIN
  IF to_regclass('public.ig_auto_response_log') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Users can view their own auto-response logs" ON public.ig_auto_response_log;
    DROP POLICY IF EXISTS "Users can insert their own auto-response logs" ON public.ig_auto_response_log;

    CREATE POLICY "Users can view their own auto-response logs" ON public.ig_auto_response_log FOR SELECT TO public
      USING (EXISTS (SELECT 1 FROM ig_auto_responders ar WHERE ar.id = ig_auto_response_log.auto_responder_id AND ar.user_id = (SELECT auth.uid())::text));
    CREATE POLICY "Users can insert their own auto-response logs" ON public.ig_auto_response_log FOR INSERT TO public
      WITH CHECK (EXISTS (SELECT 1 FROM ig_auto_responders ar WHERE ar.id = ig_auto_response_log.auto_responder_id AND ar.user_id = (SELECT auth.uid())::text));
  END IF;
END $$;

-- ══════════════════════════════════════════════
-- 10. ig_dm_templates
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "rls_user_ig_dm_templates" ON ig_dm_templates;
ALTER TABLE ig_dm_templates DROP CONSTRAINT IF EXISTS ig_dm_templates_user_id_fkey;
ALTER TABLE ig_dm_templates ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE ig_dm_templates ADD CONSTRAINT ig_dm_templates_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "rls_user_ig_dm_templates" ON ig_dm_templates FOR ALL TO public USING ((SELECT auth.uid())::text = user_id);

-- ══════════════════════════════════════════════
-- 11. ig_hashtag_tracking
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can delete their own hashtag tracking" ON ig_hashtag_tracking;
DROP POLICY IF EXISTS "Users can insert their own hashtag tracking" ON ig_hashtag_tracking;
DROP POLICY IF EXISTS "Users can view their own hashtag tracking" ON ig_hashtag_tracking;
ALTER TABLE ig_hashtag_tracking DROP CONSTRAINT IF EXISTS ig_hashtag_tracking_user_id_fkey;
ALTER TABLE ig_hashtag_tracking ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE ig_hashtag_tracking ADD CONSTRAINT ig_hashtag_tracking_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can delete their own hashtag tracking" ON ig_hashtag_tracking FOR DELETE TO public USING ((SELECT auth.uid())::text = user_id);
CREATE POLICY "Users can insert their own hashtag tracking" ON ig_hashtag_tracking FOR INSERT TO public WITH CHECK ((SELECT auth.uid())::text = user_id);
CREATE POLICY "Users can view their own hashtag tracking" ON ig_hashtag_tracking FOR SELECT TO public USING ((SELECT auth.uid())::text = user_id);

-- ══════════════════════════════════════════════
-- 12. ig_mentions
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users manage own IG mentions" ON ig_mentions;
ALTER TABLE ig_mentions DROP CONSTRAINT IF EXISTS ig_mentions_user_id_fkey;
ALTER TABLE ig_mentions ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE ig_mentions ADD CONSTRAINT ig_mentions_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users manage own IG mentions" ON ig_mentions FOR ALL TO public USING ((SELECT auth.uid())::text = user_id);

-- ══════════════════════════════════════════════
-- 13. influencer_collabs
--     Cross-dep: influencer_collab_posts policy JOINs to influencer_collabs.user_id
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users manage own collab posts" ON influencer_collab_posts;
DROP POLICY IF EXISTS "Users manage own collabs" ON influencer_collabs;
ALTER TABLE influencer_collabs DROP CONSTRAINT IF EXISTS influencer_collabs_user_id_fkey;
ALTER TABLE influencer_collabs ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE influencer_collabs ADD CONSTRAINT influencer_collabs_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users manage own collabs" ON influencer_collabs FOR ALL TO public USING (auth.uid()::text = user_id);
CREATE POLICY "Users manage own collab posts" ON influencer_collab_posts FOR ALL TO public
  USING (EXISTS (SELECT 1 FROM influencer_collabs ic WHERE ic.id = influencer_collab_posts.collab_id AND ic.user_id = auth.uid()::text));

-- ══════════════════════════════════════════════
-- 14. listening_alerts
--     Cross-dep: listening_results policy JOINs to listening_alerts.user_id
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can view own listening results" ON listening_results;
DROP POLICY IF EXISTS "Users manage own listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Workspace members access listening alerts" ON listening_alerts;
ALTER TABLE listening_alerts DROP CONSTRAINT IF EXISTS listening_alerts_user_id_fkey;
ALTER TABLE listening_alerts ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE listening_alerts ADD CONSTRAINT listening_alerts_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users manage own listening alerts" ON listening_alerts FOR ALL TO public USING (auth.uid()::text = user_id);
CREATE POLICY "Workspace members access listening alerts" ON listening_alerts FOR ALL TO public
  USING (EXISTS (
    SELECT 1 FROM workspaces
    WHERE workspaces.id = listening_alerts.workspace_id
    AND (workspaces.owner_id = (SELECT auth.uid())::text
         OR is_workspace_member(workspaces.id, (SELECT auth.uid())::text))
  ));
CREATE POLICY "Users can view own listening results" ON listening_results FOR SELECT TO public
  USING (alert_id IN (SELECT listening_alerts.id FROM listening_alerts WHERE listening_alerts.user_id = auth.uid()::text));

-- ══════════════════════════════════════════════
-- 15. post_reflections
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can insert their own reflections" ON post_reflections;
DROP POLICY IF EXISTS "Users can read their own reflections" ON post_reflections;
ALTER TABLE post_reflections DROP CONSTRAINT IF EXISTS post_reflections_user_id_fkey;
ALTER TABLE post_reflections ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE post_reflections ADD CONSTRAINT post_reflections_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can read their own reflections" ON post_reflections FOR SELECT TO public USING (auth.uid()::text = user_id);
CREATE POLICY "Users can insert their own reflections" ON post_reflections FOR INSERT TO public WITH CHECK (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 16. post_success_signals
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users own their signals" ON post_success_signals;
ALTER TABLE post_success_signals DROP CONSTRAINT IF EXISTS post_success_signals_user_id_fkey;
ALTER TABLE post_success_signals ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE post_success_signals ADD CONSTRAINT post_success_signals_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users own their signals" ON post_success_signals FOR ALL TO public USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 17. recommendation_dismissals
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can manage own dismissals" ON recommendation_dismissals;
DROP POLICY IF EXISTS "Users manage own dismissals" ON recommendation_dismissals;
ALTER TABLE recommendation_dismissals DROP CONSTRAINT IF EXISTS recommendation_dismissals_user_id_fkey;
ALTER TABLE recommendation_dismissals ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE recommendation_dismissals ADD CONSTRAINT recommendation_dismissals_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can manage own dismissals" ON recommendation_dismissals FOR ALL TO public USING (auth.uid()::text = user_id);
CREATE POLICY "Users manage own dismissals" ON recommendation_dismissals FOR ALL TO public USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 18. referral_codes
-- ══════════════════════════════════════════════
-- "Anyone can validate referral codes" doesn't reference user_id — drop/recreate for safety
DROP POLICY IF EXISTS "Anyone can validate referral codes" ON referral_codes;
DROP POLICY IF EXISTS "Users can create own referral codes" ON referral_codes;
DROP POLICY IF EXISTS "Users can read own referral codes" ON referral_codes;
DROP POLICY IF EXISTS "Users can update own referral codes" ON referral_codes;
ALTER TABLE referral_codes DROP CONSTRAINT IF EXISTS referral_codes_user_id_fkey;
ALTER TABLE referral_codes ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE referral_codes ADD CONSTRAINT referral_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Anyone can validate referral codes" ON referral_codes FOR SELECT TO public USING (is_active = true);
CREATE POLICY "Users can create own referral codes" ON referral_codes FOR INSERT TO public WITH CHECK (auth.uid()::text = user_id);
CREATE POLICY "Users can read own referral codes" ON referral_codes FOR SELECT TO public USING (auth.uid()::text = user_id);
CREATE POLICY "Users can update own referral codes" ON referral_codes FOR UPDATE TO public USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 19. style_bibles
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can manage own style bibles" ON style_bibles;
ALTER TABLE style_bibles DROP CONSTRAINT IF EXISTS style_bibles_user_id_fkey;
ALTER TABLE style_bibles ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE style_bibles ADD CONSTRAINT style_bibles_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can manage own style bibles" ON style_bibles FOR ALL TO public USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 20. sync_jobs
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can view own sync jobs" ON sync_jobs;
ALTER TABLE sync_jobs DROP CONSTRAINT IF EXISTS sync_jobs_user_id_fkey;
ALTER TABLE sync_jobs ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE sync_jobs ADD CONSTRAINT sync_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can view own sync jobs" ON sync_jobs FOR SELECT TO public USING ((SELECT auth.uid())::text = user_id);

-- ══════════════════════════════════════════════
-- 21. viral_score_calibration
-- ══════════════════════════════════════════════
-- "Service role can manage calibration data" doesn't reference user_id
DROP POLICY IF EXISTS "Service role can manage calibration data" ON viral_score_calibration;
DROP POLICY IF EXISTS "Users can view own calibration data" ON viral_score_calibration;
ALTER TABLE viral_score_calibration DROP CONSTRAINT IF EXISTS viral_score_calibration_user_id_fkey;
ALTER TABLE viral_score_calibration ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE viral_score_calibration ADD CONSTRAINT viral_score_calibration_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Service role can manage calibration data" ON viral_score_calibration FOR ALL TO public USING (true) WITH CHECK (true);
CREATE POLICY "Users can view own calibration data" ON viral_score_calibration FOR SELECT TO public USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 22. webhook_subscriptions
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can manage own webhooks" ON webhook_subscriptions;
ALTER TABLE webhook_subscriptions DROP CONSTRAINT IF EXISTS webhook_subscriptions_user_id_fkey;
ALTER TABLE webhook_subscriptions ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE webhook_subscriptions ADD CONSTRAINT webhook_subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can manage own webhooks" ON webhook_subscriptions FOR ALL TO public USING (auth.uid()::text = user_id);

-- ══════════════════════════════════════════════
-- 23. posts.rejected_by (not user_id, but UUID → auth.users)
-- ══════════════════════════════════════════════
ALTER TABLE posts DROP CONSTRAINT IF EXISTS posts_rejected_by_fkey;
ALTER TABLE posts ALTER COLUMN rejected_by TYPE text USING rejected_by::text;
ALTER TABLE posts ADD CONSTRAINT posts_rejected_by_fkey FOREIGN KEY (rejected_by) REFERENCES profiles(id) ON DELETE SET NULL;

-- ══════════════════════════════════════════════
-- 24. referrals.referrer_id + referred_id (UUID → auth.users)
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can create referrals as referred" ON referrals;
DROP POLICY IF EXISTS "Users can read own referrals" ON referrals;
ALTER TABLE referrals DROP CONSTRAINT IF EXISTS referrals_referrer_id_fkey;
ALTER TABLE referrals DROP CONSTRAINT IF EXISTS referrals_referred_id_fkey;
ALTER TABLE referrals ALTER COLUMN referrer_id TYPE text USING referrer_id::text;
ALTER TABLE referrals ALTER COLUMN referred_id TYPE text USING referred_id::text;
ALTER TABLE referrals ADD CONSTRAINT referrals_referrer_id_fkey FOREIGN KEY (referrer_id) REFERENCES profiles(id) ON DELETE CASCADE;
ALTER TABLE referrals ADD CONSTRAINT referrals_referred_id_fkey FOREIGN KEY (referred_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can create referrals as referred" ON referrals FOR INSERT TO public WITH CHECK (auth.uid()::text = referred_id);
CREATE POLICY "Users can read own referrals" ON referrals FOR SELECT TO public USING (auth.uid()::text = referrer_id OR auth.uid()::text = referred_id);

-- ══════════════════════════════════════════════
-- 25. instagram_accounts.user_id (last table FK'd to auth.users)
--     Cross-deps: audience_demographics, ig_dm_ai_rate_limits, ig_dm_ai_responses
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can view own demographics via instagram" ON audience_demographics;
DROP POLICY IF EXISTS "Users can manage AI DM rate limits for their accounts" ON ig_dm_ai_rate_limits;
DROP POLICY IF EXISTS "Users can view AI DM responses for their accounts" ON ig_dm_ai_responses;
DROP POLICY IF EXISTS "Users can delete own instagram accounts" ON instagram_accounts;
DROP POLICY IF EXISTS "Users can insert own instagram accounts" ON instagram_accounts;
DROP POLICY IF EXISTS "Users can update own instagram accounts" ON instagram_accounts;
DROP POLICY IF EXISTS "Users can view own instagram accounts" ON instagram_accounts;
ALTER TABLE instagram_accounts DROP CONSTRAINT IF EXISTS instagram_accounts_user_id_fkey;
ALTER TABLE instagram_accounts ALTER COLUMN user_id TYPE text USING user_id::text;
ALTER TABLE instagram_accounts ADD CONSTRAINT instagram_accounts_user_id_fkey FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;
CREATE POLICY "Users can delete own instagram accounts" ON instagram_accounts FOR DELETE TO public USING ((SELECT auth.uid())::text = user_id);
CREATE POLICY "Users can insert own instagram accounts" ON instagram_accounts FOR INSERT TO public WITH CHECK ((SELECT auth.uid())::text = user_id);
CREATE POLICY "Users can update own instagram accounts" ON instagram_accounts FOR UPDATE TO public USING ((SELECT auth.uid())::text = user_id);
CREATE POLICY "Users can view own instagram accounts" ON instagram_accounts FOR SELECT TO public USING ((SELECT auth.uid())::text = user_id);
CREATE POLICY "Users can view own demographics via instagram" ON audience_demographics FOR SELECT TO public
  USING (instagram_account_id IN (SELECT instagram_accounts.id FROM instagram_accounts WHERE instagram_accounts.user_id = auth.uid()::text));
CREATE POLICY "Users can manage AI DM rate limits for their accounts" ON ig_dm_ai_rate_limits FOR ALL TO public
  USING (EXISTS (SELECT 1 FROM instagram_accounts WHERE instagram_accounts.id = ig_dm_ai_rate_limits.account_id AND instagram_accounts.user_id = (SELECT auth.uid())::text));
CREATE POLICY "Users can view AI DM responses for their accounts" ON ig_dm_ai_responses FOR ALL TO public
  USING (EXISTS (SELECT 1 FROM instagram_accounts WHERE instagram_accounts.id = ig_dm_ai_responses.account_id AND instagram_accounts.user_id = (SELECT auth.uid())::text));

COMMIT;
