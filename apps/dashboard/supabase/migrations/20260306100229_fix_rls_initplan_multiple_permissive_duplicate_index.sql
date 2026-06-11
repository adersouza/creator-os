-- Backfilled from DB migration history
DROP INDEX IF EXISTS idx_listening_alerts_user;

DROP POLICY IF EXISTS "Users can manage own push subscriptions" ON push_subscriptions;
CREATE POLICY "Users can manage own push subscriptions" ON push_subscriptions
  FOR ALL USING (((select auth.uid()))::text = user_id);

DROP POLICY IF EXISTS "Users can manage own domain verifications" ON domain_verifications;
CREATE POLICY "Users can manage own domain verifications" ON domain_verifications
  FOR ALL USING (((select auth.uid()))::text = user_id);

DROP POLICY IF EXISTS "Users can manage own listening alerts" ON listening_alerts;
CREATE POLICY "Users can manage own listening alerts" ON listening_alerts
  FOR ALL USING (user_id = ((select auth.uid()))::text);

DROP POLICY IF EXISTS "Users can view own listening results" ON listening_results;
CREATE POLICY "Users can view own listening results" ON listening_results
  FOR SELECT USING (alert_id IN (
    SELECT id FROM listening_alerts
    WHERE user_id = ((select auth.uid()))::text
  ));

DROP POLICY IF EXISTS "Users read own baselines" ON recommendation_baselines;
CREATE POLICY "Users read own baselines" ON recommendation_baselines
  FOR SELECT USING (account_id IN (
    SELECT id FROM accounts WHERE user_id = ((select auth.uid()))::text
  ));

DROP POLICY IF EXISTS "Users manage own quick wins" ON quick_wins;
CREATE POLICY "Users manage own quick wins" ON quick_wins
  FOR ALL
  USING (user_id = ((select auth.uid()))::text)
  WITH CHECK (user_id = ((select auth.uid()))::text);

DROP POLICY IF EXISTS "Users manage own folders" ON draft_folders;
CREATE POLICY "Users manage own folders" ON draft_folders
  FOR ALL USING (((select auth.uid()))::text = user_id);

DROP POLICY IF EXISTS "Users manage own watermarks" ON watermark_configs;
CREATE POLICY "Users manage own watermarks" ON watermark_configs
  FOR ALL USING (((select auth.uid()))::text = user_id);

DROP POLICY IF EXISTS "Owners manage pods" ON engagement_pods;
DROP POLICY IF EXISTS "Pod members see pods" ON engagement_pods;
CREATE POLICY "Owners manage pods" ON engagement_pods
  FOR ALL USING (owner_id = ((select auth.uid()))::text);
CREATE POLICY "Pod members and owners see pods" ON engagement_pods
  FOR SELECT USING (
    owner_id = ((select auth.uid()))::text
    OR id IN (
      SELECT pod_id FROM pod_members WHERE user_id = ((select auth.uid()))::text
    )
  );

DROP POLICY IF EXISTS "Pod members see members" ON pod_members;
DROP POLICY IF EXISTS "Users manage own membership" ON pod_members;
CREATE POLICY "Users manage own membership" ON pod_members
  FOR ALL USING (user_id = ((select auth.uid()))::text);
CREATE POLICY "Pod members see members" ON pod_members
  FOR SELECT USING (
    user_id = ((select auth.uid()))::text
    OR pod_id IN (
      SELECT pod_id FROM pod_members WHERE user_id = ((select auth.uid()))::text
    )
  );

DROP POLICY IF EXISTS "Pod members see posts" ON pod_posts;
CREATE POLICY "Pod members see posts" ON pod_posts
  FOR SELECT USING (pod_id IN (
    SELECT pod_id FROM pod_members WHERE user_id = ((select auth.uid()))::text
  ));
DROP POLICY IF EXISTS "Members submit posts" ON pod_posts;
CREATE POLICY "Members submit posts" ON pod_posts
  FOR INSERT WITH CHECK (member_id IN (
    SELECT id FROM pod_members WHERE user_id = ((select auth.uid()))::text
  ));

DROP POLICY IF EXISTS "Pod members see engagements" ON pod_engagements;
CREATE POLICY "Pod members see engagements" ON pod_engagements
  FOR SELECT USING (pod_post_id IN (
    SELECT pp.id FROM pod_posts pp
    JOIN pod_members pm ON pm.pod_id = pp.pod_id
    WHERE pm.user_id = ((select auth.uid()))::text
  ));
DROP POLICY IF EXISTS "Members record engagements" ON pod_engagements;
CREATE POLICY "Members record engagements" ON pod_engagements
  FOR INSERT WITH CHECK (member_id IN (
    SELECT id FROM pod_members WHERE user_id = ((select auth.uid()))::text
  ));

DROP POLICY IF EXISTS "Users manage own templates" ON post_templates;
DROP POLICY IF EXISTS "Team sees shared templates" ON post_templates;
CREATE POLICY "Users manage own templates" ON post_templates
  FOR ALL USING (((select auth.uid()))::text = user_id);
CREATE POLICY "Users and team see templates" ON post_templates
  FOR SELECT USING (
    ((select auth.uid()))::text = user_id
    OR (is_shared = true AND workspace_id IN (
      SELECT workspace_id FROM workspace_members
      WHERE user_id = ((select auth.uid()))::text
    ))
  );

DROP POLICY IF EXISTS "Workspace admins can manage inbox assignments" ON inbox_assignments;
DROP POLICY IF EXISTS "Workspace members can view inbox assignments" ON inbox_assignments;
DROP POLICY IF EXISTS "Members can self-assign inbox items" ON inbox_assignments;
DROP POLICY IF EXISTS "Members can unassign themselves" ON inbox_assignments;

CREATE POLICY "Workspace members can view inbox assignments" ON inbox_assignments
  FOR SELECT USING (EXISTS (
    SELECT 1 FROM workspace_members wm
    WHERE wm.workspace_id = inbox_assignments.workspace_id
    AND wm.user_id = ((select auth.uid()))::text
  ));
CREATE POLICY "Members can assign inbox items" ON inbox_assignments
  FOR INSERT WITH CHECK (EXISTS (
    SELECT 1 FROM workspace_members wm
    WHERE wm.workspace_id = inbox_assignments.workspace_id
    AND wm.user_id = ((select auth.uid()))::text
    AND (
      inbox_assignments.assigned_to = ((select auth.uid()))::text
      OR wm.role IN ('owner', 'admin')
    )
  ));
CREATE POLICY "Workspace admins can update inbox assignments" ON inbox_assignments
  FOR UPDATE USING (EXISTS (
    SELECT 1 FROM workspace_members wm
    WHERE wm.workspace_id = inbox_assignments.workspace_id
    AND wm.user_id = ((select auth.uid()))::text
    AND wm.role IN ('owner', 'admin')
  ));
CREATE POLICY "Members can unassign inbox items" ON inbox_assignments
  FOR DELETE USING (EXISTS (
    SELECT 1 FROM workspace_members wm
    WHERE wm.workspace_id = inbox_assignments.workspace_id
    AND wm.user_id = ((select auth.uid()))::text
    AND (
      inbox_assignments.assigned_to = ((select auth.uid()))::text
      OR wm.role IN ('owner', 'admin')
    )
  ));
