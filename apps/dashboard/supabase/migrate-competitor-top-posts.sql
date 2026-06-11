-- Migration: Add competitor_top_posts table
-- Required for: Competitor Adaptation feature in Auto-Poster and Inspiration Engine

-- Drop existing table if it exists
DROP TABLE IF EXISTS public.competitor_top_posts CASCADE;

-- Create table with TEXT types to match existing competitors table
CREATE TABLE public.competitor_top_posts (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  competitor_id TEXT NOT NULL REFERENCES public.competitors(id) ON DELETE CASCADE,
  threads_post_id TEXT NOT NULL UNIQUE,
  content TEXT,
  media_url TEXT,
  media_type TEXT,
  permalink TEXT,
  like_count INTEGER DEFAULT 0,
  reply_count INTEGER DEFAULT 0,
  repost_count INTEGER DEFAULT 0,
  view_count INTEGER DEFAULT 0,
  engagement_score DECIMAL(10, 2) DEFAULT 0,
  published_at TIMESTAMPTZ,
  competitor_username TEXT,
  competitor_avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_competitor_top_posts_competitor_id ON public.competitor_top_posts(competitor_id);
CREATE INDEX idx_competitor_top_posts_engagement ON public.competitor_top_posts(engagement_score DESC);

-- Row Level Security
ALTER TABLE public.competitor_top_posts ENABLE ROW LEVEL SECURITY;

-- RLS policies (cast auth.uid() to text to match user_id column type)
CREATE POLICY "Users can view competitor top posts" ON public.competitor_top_posts FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM public.competitors
    WHERE competitors.id = competitor_top_posts.competitor_id
    AND competitors.user_id = auth.uid()::text
  ));

CREATE POLICY "Users can insert competitor top posts" ON public.competitor_top_posts FOR INSERT
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.competitors
    WHERE competitors.id = competitor_top_posts.competitor_id
    AND competitors.user_id = auth.uid()::text
  ));

SELECT 'competitor_top_posts table created successfully' AS status;
