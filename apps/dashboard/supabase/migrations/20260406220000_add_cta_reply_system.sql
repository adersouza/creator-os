-- Delayed CTA reply system: replaces immediate self-reply threads.
-- Posts a CTA reply to yesterday's best-performing post, riding its distribution.

-- CTA templates on group config
ALTER TABLE auto_post_group_config
  ADD COLUMN IF NOT EXISTS cta_templates JSONB DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS cta_reply_enabled BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS cta_reply_min_likes INT DEFAULT 5,
  ADD COLUMN IF NOT EXISTS cta_reply_delay_hours INT DEFAULT 16;

-- Track which posts already got a CTA reply (prevent duplicates)
ALTER TABLE auto_post_queue
  ADD COLUMN IF NOT EXISTS cta_replied_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS cta_reply_thread_id TEXT;

-- Index for the cron query: find published posts eligible for CTA reply
CREATE INDEX IF NOT EXISTS idx_apq_cta_eligible
  ON auto_post_queue(group_id, status, posted_at)
  WHERE status = 'published' AND cta_replied_at IS NULL;
