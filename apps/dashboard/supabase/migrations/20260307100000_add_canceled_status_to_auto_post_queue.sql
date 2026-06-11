-- Add 'canceled' as a valid status for auto_post_queue items
-- Used when a workspace owner downgrades from Empire and orphaned queue items
-- need to be marked as terminal without publishing them.

ALTER TABLE public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_status_check;

ALTER TABLE public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_status_check
  CHECK (status IN ('pending', 'processing', 'posted', 'failed', 'dead_letter', 'canceled'));
