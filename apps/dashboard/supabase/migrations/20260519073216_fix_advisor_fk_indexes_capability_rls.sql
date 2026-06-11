-- Address live Supabase advisor findings:
-- - Add covering indexes for foreign keys used by cascade/set-null checks.
-- - Avoid per-row auth.uid() evaluation in account_capability_errors RLS.

CREATE INDEX IF NOT EXISTS idx_account_capability_errors_workspace_id
  ON public.account_capability_errors(workspace_id);

CREATE INDEX IF NOT EXISTS idx_account_capability_errors_group_id
  ON public.account_capability_errors(group_id);

CREATE INDEX IF NOT EXISTS idx_account_health_snapshots_workspace_id
  ON public.account_health_snapshots(workspace_id);

CREATE INDEX IF NOT EXISTS idx_posts_approved_by
  ON public.posts(approved_by);

CREATE INDEX IF NOT EXISTS idx_posts_draft_folder_id
  ON public.posts(draft_folder_id);

DROP POLICY IF EXISTS "Users view own account capability errors"
  ON public.account_capability_errors;

CREATE POLICY "Users view own account capability errors"
  ON public.account_capability_errors
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.accounts a
      WHERE a.id = account_capability_errors.account_id
        AND a.user_id = (SELECT auth.uid())::text
    )
  );
