-- Convert unique INDEX to unique CONSTRAINT for Supabase JS onConflict compatibility
-- The JS client needs an actual constraint, not just a unique index

-- Drop the existing unique index
DROP INDEX IF EXISTS idx_posts_instagram_post_id_unique;

-- Add as actual unique constraint (partial constraints aren't supported,
-- so we use a regular unique constraint — NULL values are always considered distinct in PG)
DO $$ BEGIN
  ALTER TABLE posts
    ADD CONSTRAINT uq_posts_user_instagram_post_id
    UNIQUE (user_id, instagram_post_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
