-- ============================================================================
-- Add 'needs_review' status to auto_reply_queue for negative comment routing
-- ============================================================================
-- Research (Reply Engagement Strategy S8): 53% of customers expect quick
-- response to complaints. Mishandled negative interactions carry brand risk.
-- Instead of silently dropping flagged comments, route them to human review.

-- Widen the CHECK constraint to include 'needs_review'
ALTER TABLE public.auto_reply_queue
  DROP CONSTRAINT IF EXISTS auto_reply_queue_status_check;

ALTER TABLE public.auto_reply_queue
  ADD CONSTRAINT auto_reply_queue_status_check
  CHECK (status IN ('pending', 'processing', 'posted', 'failed', 'skipped', 'needs_review'));

-- Add flagged_reason column for why a comment was routed to review
ALTER TABLE public.auto_reply_queue
  ADD COLUMN IF NOT EXISTS flagged_reason TEXT;

-- Index for efficient needs_review queries (MCP + dashboard)
CREATE INDEX IF NOT EXISTS idx_auto_reply_queue_needs_review
  ON public.auto_reply_queue(workspace_id, created_at DESC)
  WHERE status = 'needs_review';
