-- Backfilled from DB migration history
DROP POLICY IF EXISTS "Owners manage pods" ON engagement_pods;
CREATE POLICY "Owners insert pods" ON engagement_pods
  FOR INSERT WITH CHECK (owner_id = ((select auth.uid()))::text);
CREATE POLICY "Owners update pods" ON engagement_pods
  FOR UPDATE USING (owner_id = ((select auth.uid()))::text);
CREATE POLICY "Owners delete pods" ON engagement_pods
  FOR DELETE USING (owner_id = ((select auth.uid()))::text);

DROP POLICY IF EXISTS "Users manage own membership" ON pod_members;
CREATE POLICY "Users insert own membership" ON pod_members
  FOR INSERT WITH CHECK (user_id = ((select auth.uid()))::text);
CREATE POLICY "Users update own membership" ON pod_members
  FOR UPDATE USING (user_id = ((select auth.uid()))::text);
CREATE POLICY "Users delete own membership" ON pod_members
  FOR DELETE USING (user_id = ((select auth.uid()))::text);

DROP POLICY IF EXISTS "Users manage own templates" ON post_templates;
CREATE POLICY "Users insert own templates" ON post_templates
  FOR INSERT WITH CHECK (((select auth.uid()))::text = user_id);
CREATE POLICY "Users update own templates" ON post_templates
  FOR UPDATE USING (((select auth.uid()))::text = user_id);
CREATE POLICY "Users delete own templates" ON post_templates
  FOR DELETE USING (((select auth.uid()))::text = user_id);
