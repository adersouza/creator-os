-- Database audit (2026-04-02): composite index for most common queue query pattern
-- WHERE workspace_id = ? AND status = ? ORDER BY posted_at DESC
--
-- Note: auto_post_activity.account_id doesn't exist in production schema.
-- ig_rate_limit_tracking and ig_endpoint_rate_limits already have UNIQUE
-- constraints on account_id which create implicit indexes.

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_ws_status_posted
  ON auto_post_queue(workspace_id, status, posted_at DESC);
