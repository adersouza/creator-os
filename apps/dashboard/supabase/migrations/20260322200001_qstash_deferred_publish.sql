-- QStash Deferred Publishing: add scheduled status + tracking columns to auto_post_queue
-- and max_interval_minutes to auto_post_group_config

-- Expand status check constraint to include 'scheduled'
ALTER TABLE public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_status_check;
ALTER TABLE public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_status_check
  CHECK (status IN ('pending','processing','posted','failed','dead_letter',
                    'queued','cancelled','canceled','published','scheduled'));

-- QStash tracking columns
ALTER TABLE public.auto_post_queue
  ADD COLUMN IF NOT EXISTS qstash_message_id TEXT,
  ADD COLUMN IF NOT EXISTS schedule_nonce TEXT;

-- Index for the publish endpoint to quickly find scheduled items ready to fire
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_scheduled
  ON public.auto_post_queue(status, scheduled_for) WHERE status = 'scheduled';

-- Per-group max interval for random spacing
ALTER TABLE public.auto_post_group_config
  ADD COLUMN IF NOT EXISTS max_interval_minutes INTEGER;
-- Default is NULL → calculatePublishTime() uses floor(min_interval_minutes * 2.5)
