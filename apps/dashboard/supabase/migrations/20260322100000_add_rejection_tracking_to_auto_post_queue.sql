-- Add rejection tracking to auto_post_queue
-- Enables: (1) storing why AI-generated posts were rejected by the content filter,
-- (2) auto-feeding rejected examples back into the system instruction,
-- (3) structured rejection reason analytics.

-- Add 'rejected' as a valid status + rejection_reason column
-- Include 'published' and 'cancelled' (British spelling) which exist in production data
ALTER TABLE public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_status_check;

ALTER TABLE public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_status_check
  CHECK (status IN ('pending', 'processing', 'posted', 'published', 'failed', 'dead_letter', 'canceled', 'cancelled', 'rejected'));

ALTER TABLE public.auto_post_queue
  ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

-- Index for querying recent rejections (auto-feed into system instruction)
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_rejected
  ON public.auto_post_queue(workspace_id, created_at DESC)
  WHERE status = 'rejected';
