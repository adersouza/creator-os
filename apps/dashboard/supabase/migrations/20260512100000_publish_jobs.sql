CREATE TABLE IF NOT EXISTS public.publish_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  workspace_id TEXT,
  platform TEXT NOT NULL CHECK (platform IN ('threads', 'instagram')),
  account_id TEXT,
  post_id TEXT,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'publishing', 'retrying', 'published', 'failed')),
  stage TEXT NOT NULL DEFAULT 'queued' CHECK (stage IN ('queued', 'preflight', 'publishing', 'processing', 'published', 'failed', 'retrying')),
  payload JSONB NOT NULL,
  result JSONB,
  error_code TEXT,
  error_message TEXT,
  request_id UUID,
  idempotency_key TEXT,
  qstash_message_id TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_jobs_idempotency
  ON public.publish_jobs(user_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_publish_jobs_user_created
  ON public.publish_jobs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_publish_jobs_worker_claim
  ON public.publish_jobs(status, updated_at)
  WHERE status IN ('queued', 'retrying');

ALTER TABLE public.publish_jobs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own publish jobs" ON public.publish_jobs;
CREATE POLICY "Users read own publish jobs" ON public.publish_jobs
  FOR SELECT
  USING ((select auth.uid()) = user_id);
