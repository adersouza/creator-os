-- Harden auto_post_queue publishing against stale QStash messages and
-- post-claim worker races.

ALTER TABLE IF EXISTS public.auto_post_queue
  ADD COLUMN IF NOT EXISTS claim_token TEXT,
  ADD COLUMN IF NOT EXISTS claim_expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_publish_claim_token
  ON public.auto_post_queue(claim_token)
  WHERE status = 'publishing' AND claim_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_publish_claim_expiry
  ON public.auto_post_queue(claim_expires_at)
  WHERE status = 'publishing';
