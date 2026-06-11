-- Per-account config overrides for autoposter
-- Allows individual accounts within a group to override any group-level setting
-- Resolution: { ...groupConfig, ...accountOverrides }

CREATE TABLE IF NOT EXISTS public.auto_post_account_overrides (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  group_id TEXT NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  overrides JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(group_id, account_id)
);

CREATE INDEX IF NOT EXISTS idx_auto_post_account_overrides_workspace
ON public.auto_post_account_overrides(workspace_id);

CREATE INDEX IF NOT EXISTS idx_auto_post_account_overrides_account
ON public.auto_post_account_overrides(account_id);

ALTER TABLE public.auto_post_account_overrides ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role has full access to auto_post_account_overrides"
ON public.auto_post_account_overrides
FOR ALL TO service_role
USING (true) WITH CHECK (true);

GRANT ALL ON TABLE public.auto_post_account_overrides TO service_role;
