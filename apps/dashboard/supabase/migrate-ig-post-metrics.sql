-- Migration: Add Reels-specific post metrics columns
-- Run in Supabase SQL editor

-- Reels-specific metrics (plays, replays, skip rate)
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS ig_plays INTEGER DEFAULT 0;
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS ig_video_views INTEGER DEFAULT 0;
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS ig_replays INTEGER DEFAULT 0;
ALTER TABLE public.posts ADD COLUMN IF NOT EXISTS ig_skip_rate NUMERIC DEFAULT 0;

SELECT 'Instagram Reels post metrics migration completed successfully' AS status;
