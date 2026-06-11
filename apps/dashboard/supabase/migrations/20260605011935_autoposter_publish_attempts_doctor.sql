-- Immutable-ish ledger for autoposter publish, finalize, and reconciliation attempts.
-- The application updates a started row to its terminal result, but rows are never
-- deleted or reused by publish code. User deletion cascade removes rows for GDPR.

CREATE TABLE IF NOT EXISTS public.publish_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  queue_item_id TEXT NOT NULL,
  user_id TEXT REFERENCES public.profiles(id) ON DELETE SET NULL,
  workspace_id TEXT REFERENCES public.workspaces(id) ON DELETE SET NULL,
  group_id TEXT REFERENCES public.account_groups(id) ON DELETE SET NULL,
  claim_token UUID,
  account_id TEXT REFERENCES public.accounts(id) ON DELETE SET NULL,
  attempt_number INTEGER NOT NULL DEFAULT 1 CHECK (attempt_number > 0),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  meta_container_id TEXT,
  threads_post_id TEXT,
  result TEXT NOT NULL DEFAULT 'started' CHECK (
    result IN (
      'started',
      'claim_failed',
      'requeued',
      'dead_letter',
      'published',
      'needs_reconciliation',
      'reconciled',
      'reconcile_failed',
      'failed',
      'error'
    )
  ),
  error_code TEXT,
  error_message TEXT,
  completed_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_publish_attempts_queue_item
  ON public.publish_attempts(queue_item_id, attempt_number);

CREATE INDEX IF NOT EXISTS idx_publish_attempts_account_started
  ON public.publish_attempts(account_id, started_at DESC)
  WHERE account_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_publish_attempts_workspace_started
  ON public.publish_attempts(workspace_id, started_at DESC)
  WHERE workspace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_publish_attempts_result_started
  ON public.publish_attempts(result, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_publish_attempts_claim_token
  ON public.publish_attempts(claim_token)
  WHERE claim_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_publish_attempts_threads_post_id
  ON public.publish_attempts(threads_post_id)
  WHERE threads_post_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_attempts_queue_attempt_unique
  ON public.publish_attempts(queue_item_id, attempt_number);

ALTER TABLE IF EXISTS public.publish_attempts ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF to_regclass('public.publish_attempts') IS NOT NULL THEN
    DROP POLICY IF EXISTS "publish_attempts_owner_select" ON public.publish_attempts;
    CREATE POLICY "publish_attempts_owner_select"
      ON public.publish_attempts
      FOR SELECT
      USING (
        user_id = (select auth.uid())::text
        OR workspace_id IN (
          SELECT id FROM public.workspaces
          WHERE owner_id = (select auth.uid())::text
        )
      );
  END IF;
END $$;

GRANT SELECT ON public.publish_attempts TO authenticated;
GRANT ALL ON public.publish_attempts TO service_role;

COMMENT ON TABLE public.publish_attempts IS
  'Append-oriented audit ledger for autoposter claim, publish, finalization, and reconciliation attempts.';
COMMENT ON COLUMN public.publish_attempts.claim_token IS
  'Lease token held by the worker when this attempt was started, if any.';
COMMENT ON COLUMN public.publish_attempts.meta_container_id IS
  'Meta creation/container id when available. Threads text publishes may only produce threads_post_id.';
COMMENT ON COLUMN public.publish_attempts.threads_post_id IS
  'External Threads post id returned by Meta or later reconciled from queue metadata.';
