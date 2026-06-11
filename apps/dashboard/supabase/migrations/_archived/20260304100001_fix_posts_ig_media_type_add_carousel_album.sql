-- Fix: Instagram API returns 'CAROUSEL_ALBUM' for carousel posts,
-- but the check constraint only allowed 'CAROUSEL'.
-- Add 'CAROUSEL_ALBUM' to the allowed values.
ALTER TABLE posts DROP CONSTRAINT IF EXISTS posts_ig_media_type_check;
ALTER TABLE posts ADD CONSTRAINT posts_ig_media_type_check
  CHECK (ig_media_type IS NULL OR ig_media_type IN ('IMAGE', 'VIDEO', 'REELS', 'CAROUSEL', 'CAROUSEL_ALBUM', 'STORIES'));
