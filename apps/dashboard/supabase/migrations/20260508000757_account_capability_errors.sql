CREATE TABLE IF NOT EXISTS public.account_capability_errors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  group_id TEXT REFERENCES public.account_groups(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
  platform TEXT NOT NULL CHECK (platform IN ('threads', 'instagram')),
  capability TEXT NOT NULL,
  error_code TEXT NOT NULL,
  message TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  blocked_until TIMESTAMPTZ,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (account_id, capability, error_code)
);

CREATE INDEX IF NOT EXISTS idx_account_capability_errors_active
  ON public.account_capability_errors(account_id, capability, error_code, blocked_until)
  WHERE resolved_at IS NULL;

ALTER TABLE public.account_capability_errors ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users view own account capability errors" ON public.account_capability_errors;
CREATE POLICY "Users view own account capability errors"
  ON public.account_capability_errors
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.accounts a
      WHERE a.id = account_capability_errors.account_id
        AND a.user_id = auth.uid()::text
    )
  );

DROP POLICY IF EXISTS "Service role manages account capability errors" ON public.account_capability_errors;
CREATE POLICY "Service role manages account capability errors"
  ON public.account_capability_errors
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

GRANT SELECT ON TABLE public.account_capability_errors TO authenticated;
GRANT ALL ON TABLE public.account_capability_errors TO service_role;
