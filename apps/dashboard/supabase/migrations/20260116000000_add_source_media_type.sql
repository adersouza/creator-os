-- Migration: Add source_media_type column to auto_post_queue
-- Stores the competitor's original media type so we can match it when posting

ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS source_media_type TEXT;

-- Comment explaining the column
COMMENT ON COLUMN public.auto_post_queue.source_media_type IS 'Media type of the source competitor post (IMAGE, VIDEO, CAROUSEL_ALBUM, TEXT) for media matching';
