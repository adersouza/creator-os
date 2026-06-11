-- Add columns needed by bulk_schedule_groups and the publish pipeline
ALTER TABLE posts ADD COLUMN IF NOT EXISTS topic_tag TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS media_type TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS media_ids TEXT[];
ALTER TABLE posts ADD COLUMN IF NOT EXISTS link_url TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS metadata JSONB;

CREATE INDEX IF NOT EXISTS idx_posts_topic_tag ON posts (topic_tag) WHERE topic_tag IS NOT NULL;
