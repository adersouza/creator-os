-- Schema hardening: CHECK constraints, missing indexes, FK cascades
-- Part of Wave 3 professional-grade remediation.

-- ============================================================================
-- 1. CHECK constraint on posts.media_type (added in 20260326030000 with no constraint)
-- ============================================================================
-- Normalize existing data to lowercase
UPDATE posts SET media_type = LOWER(media_type) WHERE media_type IS NOT NULL AND media_type != LOWER(media_type);
-- Map variant names to canonical values
UPDATE posts SET media_type = 'text' WHERE media_type = 'text_post';
UPDATE posts SET media_type = 'reel' WHERE media_type = 'reels';
UPDATE posts SET media_type = 'story' WHERE media_type = 'stories';
UPDATE posts SET media_type = 'carousel' WHERE media_type = 'carousel_album';

ALTER TABLE posts DROP CONSTRAINT IF EXISTS chk_posts_media_type;
ALTER TABLE posts ADD CONSTRAINT chk_posts_media_type
  CHECK (media_type IS NULL OR media_type IN ('text', 'image', 'video', 'carousel', 'reel', 'story'));

-- ============================================================================
-- 2. Reverse-composite index for "latest analytics per account" queries
--    The existing idx covers (account_id, date) but dashboard queries
--    filter by date DESC first, then group by account.
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_account_analytics_date_desc_account
  ON account_analytics(date DESC, account_id);

-- ============================================================================
-- 3. GIN index on posts.metadata JSONB for publish pipeline queries
--    (e.g., filtering by metadata->>variant_of, metadata->>crossreshareToIg)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_posts_metadata_gin
  ON posts USING GIN (metadata) WHERE metadata IS NOT NULL;

-- ============================================================================
-- 4. Fix ON DELETE for auto_post_queue.group_id and auto_post_activity.group_id
--    SET NULL leaves orphaned queue items when groups are deleted.
--    CASCADE is correct: deleting a group should clear its queue.
-- ============================================================================

-- auto_post_queue.group_id: SET NULL → CASCADE
ALTER TABLE auto_post_queue DROP CONSTRAINT IF EXISTS auto_post_queue_group_id_fkey;
ALTER TABLE auto_post_queue
  ADD CONSTRAINT auto_post_queue_group_id_fkey
  FOREIGN KEY (group_id) REFERENCES account_groups(id) ON DELETE CASCADE;

-- auto_post_activity.group_id: SET NULL → CASCADE (activity logs for deleted groups are noise)
ALTER TABLE auto_post_activity DROP CONSTRAINT IF EXISTS auto_post_activity_group_id_fkey;
ALTER TABLE auto_post_activity
  ADD CONSTRAINT auto_post_activity_group_id_fkey
  FOREIGN KEY (group_id) REFERENCES account_groups(id) ON DELETE CASCADE;
