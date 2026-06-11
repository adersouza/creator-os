-- Add self_reply_ratio to auto_post_group_config
-- Controls what percentage of text-only Threads posts become 2-part self-reply threads.
-- Default NULL = use system default (0.40 = 40%).
-- Set to 0 to disable threading for a group, or 1.0 for 100% threading.

ALTER TABLE public.auto_post_group_config
  ADD COLUMN IF NOT EXISTS self_reply_ratio REAL;

COMMENT ON COLUMN public.auto_post_group_config.self_reply_ratio
  IS 'Ratio of text-only Threads posts published as 2-part self-reply threads (0-1, NULL=default 0.40)';

-- Add metadata column to auto_post_queue if not exists
-- Used for thread chain data (is_thread_chain, self_reply_content) and video format info
ALTER TABLE public.auto_post_queue
  ADD COLUMN IF NOT EXISTS metadata JSONB;

COMMENT ON COLUMN public.auto_post_queue.metadata
  IS 'Flexible metadata: thread chain info, video format, etc.';
