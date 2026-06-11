-- ============================================
-- TRENDS SERVICE MIGRATION
-- Run this in Supabase SQL Editor
-- ============================================

-- ============================================
-- TREND KEYWORDS (user's tracked keywords)
-- ============================================
CREATE TABLE IF NOT EXISTS public.trend_keywords (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,

  -- Keyword data
  keyword TEXT NOT NULL,
  category TEXT,
  is_active BOOLEAN DEFAULT TRUE,

  -- Sync tracking
  last_synced_at TIMESTAMPTZ,
  post_count INTEGER DEFAULT 0,
  total_engagement INTEGER DEFAULT 0,

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  -- Unique constraint: one keyword per user
  UNIQUE(user_id, keyword)
);

-- Create indexes for trend_keywords
CREATE INDEX IF NOT EXISTS idx_trend_keywords_user_id ON public.trend_keywords(user_id);
CREATE INDEX IF NOT EXISTS idx_trend_keywords_keyword ON public.trend_keywords(keyword);
CREATE INDEX IF NOT EXISTS idx_trend_keywords_is_active ON public.trend_keywords(is_active);

-- Enable RLS
ALTER TABLE public.trend_keywords ENABLE ROW LEVEL SECURITY;

-- Drop existing policy if exists (for re-running migration)
DROP POLICY IF EXISTS "Users can manage own trend keywords" ON public.trend_keywords;

-- Create RLS policy
CREATE POLICY "Users can manage own trend keywords" ON public.trend_keywords
  FOR ALL USING (auth.uid()::text = user_id);

-- ============================================
-- TREND POSTS (cached posts from searches)
-- ============================================
CREATE TABLE IF NOT EXISTS public.trend_posts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  keyword_id UUID NOT NULL REFERENCES public.trend_keywords(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,

  -- Post data from Threads API
  threads_post_id TEXT NOT NULL,
  content TEXT,
  username TEXT NOT NULL,
  media_url TEXT,
  media_type TEXT,
  permalink TEXT,

  -- Engagement metrics
  like_count INTEGER DEFAULT 0,
  reply_count INTEGER DEFAULT 0,
  repost_count INTEGER DEFAULT 0,
  view_count INTEGER DEFAULT 0,
  engagement_score INTEGER DEFAULT 0,

  -- Timestamps
  posted_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ DEFAULT NOW(),

  -- Unique constraint: one post per keyword
  UNIQUE(keyword_id, threads_post_id)
);

-- Create indexes for trend_posts
CREATE INDEX IF NOT EXISTS idx_trend_posts_keyword_id ON public.trend_posts(keyword_id);
CREATE INDEX IF NOT EXISTS idx_trend_posts_user_id ON public.trend_posts(user_id);
CREATE INDEX IF NOT EXISTS idx_trend_posts_engagement ON public.trend_posts(engagement_score DESC);
CREATE INDEX IF NOT EXISTS idx_trend_posts_fetched_at ON public.trend_posts(fetched_at DESC);

-- Enable RLS
ALTER TABLE public.trend_posts ENABLE ROW LEVEL SECURITY;

-- Drop existing policy if exists
DROP POLICY IF EXISTS "Users can manage own trend posts" ON public.trend_posts;

-- Create RLS policy
CREATE POLICY "Users can manage own trend posts" ON public.trend_posts
  FOR ALL USING (auth.uid()::text = user_id);

-- ============================================
-- TREND SNAPSHOTS (daily aggregated data)
-- ============================================
CREATE TABLE IF NOT EXISTS public.trend_snapshots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  keyword_id UUID NOT NULL REFERENCES public.trend_keywords(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,

  -- Snapshot data
  snapshot_date DATE NOT NULL,
  total_posts INTEGER DEFAULT 0,
  total_engagement INTEGER DEFAULT 0,
  avg_engagement NUMERIC(10, 2) DEFAULT 0,

  -- Top hashtags found in posts (JSONB array)
  top_hashtags JSONB DEFAULT '[]'::jsonb,

  -- Top post IDs for this day (JSONB array of UUIDs)
  top_post_ids JSONB DEFAULT '[]'::jsonb,

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),

  -- Unique constraint: one snapshot per keyword per day
  UNIQUE(keyword_id, snapshot_date)
);

-- Create indexes for trend_snapshots
CREATE INDEX IF NOT EXISTS idx_trend_snapshots_keyword_id ON public.trend_snapshots(keyword_id);
CREATE INDEX IF NOT EXISTS idx_trend_snapshots_user_id ON public.trend_snapshots(user_id);
CREATE INDEX IF NOT EXISTS idx_trend_snapshots_date ON public.trend_snapshots(snapshot_date DESC);

-- Enable RLS
ALTER TABLE public.trend_snapshots ENABLE ROW LEVEL SECURITY;

-- Drop existing policy if exists
DROP POLICY IF EXISTS "Users can manage own trend snapshots" ON public.trend_snapshots;

-- Create RLS policy
CREATE POLICY "Users can manage own trend snapshots" ON public.trend_snapshots
  FOR ALL USING (auth.uid()::text = user_id);

-- ============================================
-- TRIGGERS FOR updated_at
-- ============================================
-- Create trigger function if it doesn't exist
CREATE OR REPLACE FUNCTION update_trends_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if exists
DROP TRIGGER IF EXISTS update_trend_keywords_updated_at ON public.trend_keywords;

-- Create trigger for updated_at
CREATE TRIGGER update_trend_keywords_updated_at
  BEFORE UPDATE ON public.trend_keywords
  FOR EACH ROW EXECUTE FUNCTION update_trends_updated_at();

-- ============================================
-- DONE!
-- ============================================
-- To verify, run:
-- SELECT * FROM information_schema.tables WHERE table_name LIKE 'trend%';
