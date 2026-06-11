-- Deduplicate existing instagram posts (keep the one with the most recent updated_at)
DELETE FROM posts a
USING posts b
WHERE a.instagram_post_id IS NOT NULL
  AND a.instagram_post_id = b.instagram_post_id
  AND a.user_id = b.user_id
  AND a.id < b.id;

-- Add unique constraint to prevent future duplicates
CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_instagram_post_id_unique
  ON posts(user_id, instagram_post_id)
  WHERE instagram_post_id IS NOT NULL;
