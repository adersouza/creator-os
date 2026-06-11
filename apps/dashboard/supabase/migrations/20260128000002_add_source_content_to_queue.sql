-- Migration: Add source_content column to auto_post_queue
-- Stores the original competitor post content that was used to generate this AI post

ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS source_content TEXT;

COMMENT ON COLUMN public.auto_post_queue.source_content IS 'Original competitor post content that inspired this AI-generated post';
