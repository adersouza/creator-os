-- Harden external side effects for auto replies and link tracking.

ALTER TABLE public.auto_reply_queue
  ADD COLUMN IF NOT EXISTS publish_claim_token TEXT,
  ADD COLUMN IF NOT EXISTS publish_claimed_at TIMESTAMPTZ;

ALTER TABLE public.auto_reply_queue
  DROP CONSTRAINT IF EXISTS auto_reply_queue_status_check;

ALTER TABLE public.auto_reply_queue
  ADD CONSTRAINT auto_reply_queue_status_check
  CHECK (status IN (
    'pending',
    'processing',
    'publishing',
    'posted',
    'failed',
    'skipped',
    'needs_review'
  ));

CREATE INDEX IF NOT EXISTS idx_auto_reply_queue_publish_claim
  ON public.auto_reply_queue(status, publish_claimed_at)
  WHERE status = 'publishing';

ALTER TABLE public.auto_reply_logs
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT,
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'completed';

ALTER TABLE public.auto_reply_logs
  DROP CONSTRAINT IF EXISTS auto_reply_logs_status_check;

ALTER TABLE public.auto_reply_logs
  ADD CONSTRAINT auto_reply_logs_status_check
  CHECK (status IN ('processing', 'completed', 'failed'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_auto_reply_logs_idempotency_key
  ON public.auto_reply_logs(idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_auto_reply_logs_processing
  ON public.auto_reply_logs(status, created_at)
  WHERE status = 'processing';
