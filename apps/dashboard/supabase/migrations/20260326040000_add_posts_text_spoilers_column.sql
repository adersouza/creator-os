-- Add text_spoilers JSONB column to posts table for spoiler trick support
-- Previously only auto_post_queue had this; now manually scheduled posts get it too
ALTER TABLE posts ADD COLUMN IF NOT EXISTS text_spoilers JSONB DEFAULT NULL;
