-- Add story_expires_at column to posts table for Instagram Stories
-- Stories expire 24 hours after posting

ALTER TABLE posts ADD COLUMN IF NOT EXISTS story_expires_at TIMESTAMPTZ;

-- Index for querying active/expired stories
CREATE INDEX IF NOT EXISTS idx_posts_story_expires_at ON posts (story_expires_at) WHERE story_expires_at IS NOT NULL;
