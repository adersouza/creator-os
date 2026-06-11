-- Add topic_tag for Threads notification-style headers
-- e.g. "waiting for your reply", "sent you friend request"
-- Shows as bold text above post content, drives engagement
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS topic_tag TEXT DEFAULT NULL;
