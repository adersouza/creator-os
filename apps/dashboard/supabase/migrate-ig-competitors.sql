-- Migration: Add Instagram competitor support to existing competitors infrastructure
-- Run in Supabase SQL editor

-- Add platform and IG-specific columns to competitors table
ALTER TABLE public.competitors ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'threads';
ALTER TABLE public.competitors ADD COLUMN IF NOT EXISTS instagram_user_id TEXT;
ALTER TABLE public.competitors ADD COLUMN IF NOT EXISTS media_count INTEGER DEFAULT 0;
ALTER TABLE public.competitors ADD COLUMN IF NOT EXISTS avg_likes NUMERIC DEFAULT 0;
ALTER TABLE public.competitors ADD COLUMN IF NOT EXISTS avg_comments NUMERIC DEFAULT 0;
ALTER TABLE public.competitors ADD COLUMN IF NOT EXISTS engagement_rate NUMERIC DEFAULT 0;
ALTER TABLE public.competitors ADD COLUMN IF NOT EXISTS website TEXT;

-- Add platform to competitor_top_posts for filtering
ALTER TABLE public.competitor_top_posts ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'threads';

-- IG-specific fields on top posts (likes/comments instead of Threads metrics)
ALTER TABLE public.competitor_top_posts ADD COLUMN IF NOT EXISTS like_count INTEGER DEFAULT 0;
ALTER TABLE public.competitor_top_posts ADD COLUMN IF NOT EXISTS comments_count INTEGER DEFAULT 0;
ALTER TABLE public.competitor_top_posts ADD COLUMN IF NOT EXISTS media_url TEXT;
ALTER TABLE public.competitor_top_posts ADD COLUMN IF NOT EXISTS media_type TEXT;

-- Index for platform-filtered queries
CREATE INDEX IF NOT EXISTS idx_competitors_platform ON public.competitors(user_id, platform);
CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_platform ON public.competitor_top_posts(competitor_id, platform);

SELECT 'Instagram competitor migration completed successfully' AS status;
