-- ============================================================================
-- Auto-Reply Queue table for autoposter engagement loop
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.auto_reply_queue (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  group_id TEXT REFERENCES account_groups(id) ON DELETE SET NULL,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  source_post_id TEXT NOT NULL,
  threads_post_id TEXT NOT NULL,
  comment_id TEXT NOT NULL UNIQUE,
  comment_username TEXT NOT NULL,
  comment_text TEXT NOT NULL,
  generated_reply TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'processing', 'posted', 'failed', 'skipped')),
  retry_count INT NOT NULL DEFAULT 0,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  posted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_auto_reply_queue_status
  ON public.auto_reply_queue(status, created_at)
  WHERE status IN ('pending', 'processing');

CREATE INDEX IF NOT EXISTS idx_auto_reply_queue_account
  ON public.auto_reply_queue(account_id, created_at);

CREATE INDEX IF NOT EXISTS idx_auto_reply_queue_workspace
  ON public.auto_reply_queue(workspace_id);

ALTER TABLE public.auto_reply_queue ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role has full access to auto_reply_queue"
  ON public.auto_reply_queue
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);

GRANT ALL ON TABLE public.auto_reply_queue TO service_role;

-- ============================================================================
-- Add auto-reply config columns to auto_post_group_config
-- ============================================================================

ALTER TABLE public.auto_post_group_config
  ADD COLUMN IF NOT EXISTS enable_auto_reply BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS auto_reply_trigger_count INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS auto_reply_window_hours INT NOT NULL DEFAULT 24,
  ADD COLUMN IF NOT EXISTS auto_reply_daily_limit INT NOT NULL DEFAULT 5,
  ADD COLUMN IF NOT EXISTS auto_reply_ratio REAL NOT NULL DEFAULT 0.5;

-- ============================================================================
-- Track which auto-posted content has been harvested for comments
-- ============================================================================

ALTER TABLE public.auto_post_queue
  ADD COLUMN IF NOT EXISTS reply_harvested_at TIMESTAMPTZ;
