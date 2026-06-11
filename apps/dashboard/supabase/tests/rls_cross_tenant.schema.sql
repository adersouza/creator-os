-- Minimal schema fixture for supabase/tests/rls_cross_tenant.test.sql.
--
-- The repository migration directory is incremental and the checked-in
-- production snapshot is not a reliable zero-state restore. This fixture keeps
-- the RLS regression focused on the high-risk tables and policies it asserts.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE public.posts (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL,
  content TEXT NOT NULL
);

CREATE TABLE public.accounts (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL,
  threads_user_id TEXT NOT NULL UNIQUE,
  username TEXT NOT NULL,
  threads_access_token_encrypted TEXT
);

CREATE TABLE public.instagram_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  instagram_user_id TEXT NOT NULL UNIQUE
);

CREATE TABLE public.ai_config (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL UNIQUE
);

CREATE TABLE public.account_analytics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id TEXT NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  UNIQUE(account_id, date)
);

CREATE TABLE public.workspaces (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  name TEXT NOT NULL,
  owner_id TEXT NOT NULL
);

CREATE TABLE public.workspace_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  UNIQUE(workspace_id, user_id)
);

CREATE TABLE public.auto_post_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  scheduled_for TIMESTAMPTZ
);

CREATE TABLE public.reports (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('scheduled', 'one-off')),
  cadence TEXT NOT NULL CHECK (cadence IN ('weekly', 'monthly', 'quarterly', 'one-off')),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('active', 'paused', 'generated', 'draft'))
);

CREATE TABLE public.smart_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  code TEXT UNIQUE NOT NULL,
  target_url TEXT NOT NULL
);

CREATE TABLE public.recovery_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.instagram_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.account_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auto_post_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.smart_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recovery_codes ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.is_workspace_member(p_workspace_id TEXT, p_user_id TEXT)
RETURNS BOOLEAN AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.workspace_members
    WHERE workspace_id = p_workspace_id AND user_id = p_user_id
  );
$$ LANGUAGE sql SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION public.is_workspace_owner(p_workspace_id TEXT, p_user_id TEXT)
RETURNS BOOLEAN AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.workspaces
    WHERE id = p_workspace_id AND owner_id = p_user_id
  );
$$ LANGUAGE sql SECURITY DEFINER SET search_path = public;

CREATE POLICY posts_owner ON public.posts
  FOR ALL USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

CREATE POLICY accounts_owner ON public.accounts
  FOR ALL USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

CREATE POLICY instagram_accounts_owner ON public.instagram_accounts
  FOR ALL USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

CREATE POLICY ai_config_owner ON public.ai_config
  FOR ALL USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

CREATE POLICY account_analytics_account_owner ON public.account_analytics
  FOR SELECT USING (
    EXISTS (
      SELECT 1
      FROM public.accounts
      WHERE accounts.id = account_analytics.account_id
        AND accounts.user_id = (SELECT auth.uid())::text
    )
  );

CREATE POLICY workspaces_member_read ON public.workspaces
  FOR SELECT USING (
    owner_id = (SELECT auth.uid())::text
    OR public.is_workspace_member(id, (SELECT auth.uid())::text)
  );

CREATE POLICY workspaces_owner_update ON public.workspaces
  FOR UPDATE USING (owner_id = (SELECT auth.uid())::text);

CREATE POLICY workspace_members_visible ON public.workspace_members
  FOR SELECT USING (
    user_id = (SELECT auth.uid())::text
    OR public.is_workspace_owner(workspace_id, (SELECT auth.uid())::text)
  );

CREATE POLICY auto_post_queue_workspace_member ON public.auto_post_queue
  FOR ALL USING (public.is_workspace_member(workspace_id, (SELECT auth.uid())::text))
  WITH CHECK (public.is_workspace_member(workspace_id, (SELECT auth.uid())::text));

CREATE POLICY reports_owner ON public.reports
  FOR ALL USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

CREATE POLICY smart_links_owner ON public.smart_links
  FOR ALL USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- recovery_codes intentionally has RLS enabled and no policies.

GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO anon;
