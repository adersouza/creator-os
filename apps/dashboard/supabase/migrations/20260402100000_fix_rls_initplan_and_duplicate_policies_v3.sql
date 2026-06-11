-- Fix Supabase linter warnings (2026-04-02):
-- 1. auth_rls_initplan (0003): wrap auth.uid() in (select ...) for 7 policies
-- 2. multiple_permissive_policies (0006): drop duplicate SELECT policies on 3 tables

-- ============================================================================
-- FIX auth_rls_initplan: wrap auth.uid() / auth.<fn>() in (select ...)
-- ============================================================================

-- 1. watchdog_alerts — FOR ALL (subquery in workspace_id IN (...))
DROP POLICY IF EXISTS "watchdog_alerts_owner" ON public.watchdog_alerts;
CREATE POLICY "watchdog_alerts_owner" ON public.watchdog_alerts
  FOR ALL USING (
    workspace_id IN (SELECT id FROM workspaces WHERE owner_id = (select auth.uid())::text)
  );

-- 2. account_metrics_history — SELECT (subquery in account_id IN (...))
DROP POLICY IF EXISTS "Users can view own account history" ON public.account_metrics_history;
CREATE POLICY "Users can view own account history" ON public.account_metrics_history
  FOR SELECT USING (
    account_id IN (SELECT id FROM accounts WHERE user_id = (select auth.uid())::text)
  );

-- 3. competitor_metrics_history — SELECT
DROP POLICY IF EXISTS "Users can view own competitor history" ON public.competitor_metrics_history;
CREATE POLICY "Users can view own competitor history" ON public.competitor_metrics_history
  FOR SELECT USING (
    user_id = (select auth.uid())::text
  );

-- 4. auto_self_replies — SELECT
DROP POLICY IF EXISTS "Users can read own self-replies" ON public.auto_self_replies;
CREATE POLICY "Users can read own self-replies" ON public.auto_self_replies
  FOR SELECT USING ((select auth.uid())::text = user_id);

-- 5. auto_cross_replies — SELECT
DROP POLICY IF EXISTS "Users can read own cross-replies" ON public.auto_cross_replies;
CREATE POLICY "Users can read own cross-replies" ON public.auto_cross_replies
  FOR SELECT USING ((select auth.uid())::text = user_id);

-- 6. ig_comments — SELECT (EXISTS subquery)
DROP POLICY IF EXISTS "Users can read own post comments" ON public.ig_comments;
CREATE POLICY "Users can read own post comments" ON public.ig_comments
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM posts p
      WHERE p.id = ig_comments.post_id
        AND p.user_id = (select auth.uid())::text
    )
  );

-- 7. ig_collab_invites — SELECT
DROP POLICY IF EXISTS "Users see own collab invites" ON public.ig_collab_invites;
CREATE POLICY "Users see own collab invites" ON public.ig_collab_invites
  FOR SELECT USING ((select auth.uid())::text = user_id);

-- ============================================================================
-- FIX multiple_permissive_policies: drop duplicate SELECT policies
-- The "Service role can manage" FOR ALL policies already cover service_role.
-- The "Users access own" FOR ALL policies from 20260208 overlap with the
-- more specific FOR SELECT policies added later.
-- ============================================================================

-- auto_cross_replies: "Service role can manage cross-replies" (FOR ALL) overlaps
-- with "Users can read own cross-replies" (FOR SELECT) for every role.
-- The service role policy is overly broad (USING true) — it grants ALL ops to
-- ALL roles. Replace with a restrictive service_role-only policy.
DROP POLICY IF EXISTS "Service role can manage cross-replies" ON public.auto_cross_replies;
CREATE POLICY "Service role can manage cross-replies" ON public.auto_cross_replies
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- auto_self_replies: same issue
DROP POLICY IF EXISTS "Service role can manage self-replies" ON public.auto_self_replies;
CREATE POLICY "Service role can manage self-replies" ON public.auto_self_replies
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- ig_comments: "Users access own IG comments" (FOR ALL, 20260208) overlaps
-- with "Users can read own post comments" (FOR SELECT, 20260322).
-- The FOR ALL policy is the broader one; drop it and keep the SELECT-only one.
DROP POLICY IF EXISTS "Users access own IG comments" ON public.ig_comments;
