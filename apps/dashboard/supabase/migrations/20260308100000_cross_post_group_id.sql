-- Add cross_post_group_id to link posts created together via "Post to Both"
ALTER TABLE posts ADD COLUMN IF NOT EXISTS cross_post_group_id TEXT;
CREATE INDEX IF NOT EXISTS idx_posts_cross_post_group_id ON posts(cross_post_group_id);
