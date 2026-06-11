-- Infrastructure Audit: Missing Indexes
--
-- Fixes 4 missing indexes identified by codebase audit.
-- schema.sql confirmed the other 6 reported-missing indexes already exist.

-- ── auto_post_queue: pending/queued items fetch (ORDER BY created_at ASC) ──
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_pending
  ON auto_post_queue (created_at ASC)
  WHERE status IN ('pending', 'queued');

-- ── auto_post_queue: retry items fetch ──
-- Column renamed retry_after → next_retry_at in later autoposter work.
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_retry
  ON auto_post_queue (next_retry_at ASC)
  WHERE status = 'retry';

-- ── sent_replies: rate-limit checks per account (account_id + recent created_at) ──
CREATE INDEX IF NOT EXISTS idx_sent_replies_account_created
  ON sent_replies (account_id, created_at DESC);

-- ── ig_comments: time-range queries not scoped to a specific post ──
CREATE INDEX IF NOT EXISTS idx_ig_comments_created_at
  ON ig_comments (created_at DESC);
