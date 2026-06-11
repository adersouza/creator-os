-- Queue fill dedup: checking existing items for a group at a scheduled time
-- Hot path: queue.ts, scheduleAndInsert.ts, publish-worker.ts
-- Partial index keeps it small — only pending/queued rows, not dead_letter/posted
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_group_scheduled
  ON auto_post_queue(group_id, scheduled_for)
  WHERE status IN ('pending', 'queued');

-- Multi-account analytics: user's posts filtered by status, ordered by date
-- Hot path: posts page, analytics calculations, GDPR export
CREATE INDEX IF NOT EXISTS idx_posts_user_status_created
  ON posts(user_id, status, created_at DESC);
