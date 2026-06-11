-- Migration: Add shares columns to posts and account_analytics tables
-- Run this in Supabase SQL Editor

-- Add shares_count to posts table
ALTER TABLE public.posts
ADD COLUMN IF NOT EXISTS shares_count INTEGER DEFAULT 0;

-- Add total_shares to account_analytics table
ALTER TABLE public.account_analytics
ADD COLUMN IF NOT EXISTS total_shares INTEGER DEFAULT 0;

-- Update any existing rows to have 0 for shares (already default, but explicit)
UPDATE public.posts SET shares_count = 0 WHERE shares_count IS NULL;
UPDATE public.account_analytics SET total_shares = 0 WHERE total_shares IS NULL;

-- Add comment for documentation
COMMENT ON COLUMN public.posts.shares_count IS 'Number of times this post was shared (from Threads API insights)';
COMMENT ON COLUMN public.account_analytics.total_shares IS 'Total shares across all posts for this account on this date';
