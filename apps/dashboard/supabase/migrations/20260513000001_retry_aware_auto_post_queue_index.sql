-- Optimize autoposter dispatch/reconciliation queries that now honor next_retry_at.
-- No data shape changes; retry columns already exist.

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_retry_due
  ON public.auto_post_queue (workspace_id, group_id, status, scheduled_for, next_retry_at)
  WHERE status IN ('pending', 'queued');
