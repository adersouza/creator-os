-- ============================================
-- DISCOVER PAGE MIGRATION
-- Run this in Supabase SQL Editor
-- ============================================

-- ============================================
-- SAVED SEARCHES (user's saved search queries)
-- ============================================
CREATE TABLE IF NOT EXISTS public.saved_searches (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,

  -- Search configuration
  name TEXT NOT NULL,
  query TEXT NOT NULL,
  search_mode TEXT DEFAULT 'KEYWORD' CHECK (search_mode IN ('KEYWORD', 'TAG')),
  search_type TEXT DEFAULT 'RECENT' CHECK (search_type IN ('RECENT', 'TOP')),
  media_type TEXT CHECK (media_type IS NULL OR media_type IN ('TEXT', 'IMAGE', 'VIDEO')),

  -- Metrics (updated by cron)
  last_volume INTEGER DEFAULT 0,
  volume_change INTEGER DEFAULT 0,
  volume_change_percent NUMERIC(5,2) DEFAULT 0,
  last_refreshed_at TIMESTAMPTZ,

  -- Alert settings (Empire tier)
  alerts_enabled BOOLEAN DEFAULT FALSE,
  alert_threshold INTEGER DEFAULT 100,

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  -- Unique constraint: prevent duplicate queries per user
  UNIQUE(user_id, query, search_mode)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_saved_searches_user_id ON public.saved_searches(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_searches_query ON public.saved_searches(query);
CREATE INDEX IF NOT EXISTS idx_saved_searches_last_refreshed ON public.saved_searches(last_refreshed_at);

-- Enable RLS
ALTER TABLE public.saved_searches ENABLE ROW LEVEL SECURITY;

-- Drop existing policy if exists
DROP POLICY IF EXISTS "Users can manage own saved searches" ON public.saved_searches;

-- Create RLS policy
CREATE POLICY "Users can manage own saved searches" ON public.saved_searches
  FOR ALL USING (auth.uid()::text = user_id);

-- ============================================
-- SAVED SEARCH SNAPSHOTS (daily metrics history)
-- ============================================
CREATE TABLE IF NOT EXISTS public.saved_search_snapshots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  saved_search_id UUID NOT NULL REFERENCES public.saved_searches(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,

  -- Snapshot data
  snapshot_date DATE NOT NULL,
  post_volume INTEGER DEFAULT 0,
  total_engagement INTEGER DEFAULT 0,
  avg_engagement NUMERIC(10,2) DEFAULT 0,

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),

  -- Unique constraint: one snapshot per search per day
  UNIQUE(saved_search_id, snapshot_date)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_search_snapshots_search_id ON public.saved_search_snapshots(saved_search_id);
CREATE INDEX IF NOT EXISTS idx_search_snapshots_user_id ON public.saved_search_snapshots(user_id);
CREATE INDEX IF NOT EXISTS idx_search_snapshots_date ON public.saved_search_snapshots(snapshot_date DESC);

-- Enable RLS
ALTER TABLE public.saved_search_snapshots ENABLE ROW LEVEL SECURITY;

-- Drop existing policy if exists
DROP POLICY IF EXISTS "Users can manage own search snapshots" ON public.saved_search_snapshots;

-- Create RLS policy
CREATE POLICY "Users can manage own search snapshots" ON public.saved_search_snapshots
  FOR ALL USING (auth.uid()::text = user_id);

-- ============================================
-- TRIGGERS FOR updated_at
-- ============================================
-- Create trigger function if it doesn't exist
CREATE OR REPLACE FUNCTION update_saved_searches_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if exists
DROP TRIGGER IF EXISTS update_saved_searches_updated_at ON public.saved_searches;

-- Create trigger for updated_at
CREATE TRIGGER update_saved_searches_updated_at
  BEFORE UPDATE ON public.saved_searches
  FOR EACH ROW EXECUTE FUNCTION update_saved_searches_updated_at();

-- ============================================
-- DONE!
-- ============================================
-- To verify, run:
-- SELECT * FROM information_schema.tables WHERE table_name LIKE 'saved_search%';
