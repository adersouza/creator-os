-- Migration: Add engagement tracking columns to auto_post_queue
-- This enables tracking post performance for the PerformanceInsights dashboard

-- Add missing columns to auto_post_queue table
ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES public.accounts(id) ON DELETE SET NULL;

ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS threads_post_id TEXT;

ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'queue' CHECK (source_type IN ('queue', 'ai-generated', 'competitor-adapted'));

-- Engagement metrics (fetched 24h after posting)
ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS engagement_rate DECIMAL(5,4);

ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS views_at_24h INTEGER;

ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS likes_count INTEGER;

ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS replies_count INTEGER;

ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS reposts_count INTEGER;

ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS engagement_fetched_at TIMESTAMPTZ;

-- Create index for finding posts that need engagement metrics fetched
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_engagement_fetch
ON public.auto_post_queue(status, posted_at, engagement_fetched_at);

-- Create index on account_id
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_account_id
ON public.auto_post_queue(account_id);
