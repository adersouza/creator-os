-- ThreadsDashboard Migration v3
-- Additional tables for Vercel migration
-- Run this in Supabase SQL Editor AFTER migrate-safe-v2.sql

-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- COMPETITORS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS public.competitors (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL,
  threads_user_id TEXT NOT NULL,
  threads_numeric_id TEXT,
  username TEXT NOT NULL,
  display_name TEXT,
  avatar_url TEXT,
  bio TEXT,
  follower_count INTEGER DEFAULT 0,
  is_verified BOOLEAN DEFAULT FALSE,
  likes_count_7d INTEGER DEFAULT 0,
  quotes_count_7d INTEGER DEFAULT 0,
  replies_count_7d INTEGER DEFAULT 0,
  reposts_count_7d INTEGER DEFAULT 0,
  views_count_7d INTEGER DEFAULT 0,
  added_at TIMESTAMPTZ DEFAULT NOW(),
  last_synced_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, threads_user_id)
);

CREATE INDEX IF NOT EXISTS idx_competitors_user_id ON public.competitors(user_id);

-- ============================================
-- COMPETITOR SNAPSHOTS (for sparkline charts)
-- ============================================
CREATE TABLE IF NOT EXISTS public.competitor_snapshots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  competitor_id UUID NOT NULL REFERENCES public.competitors(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  follower_count INTEGER DEFAULT 0,
  likes_count_7d INTEGER DEFAULT 0,
  quotes_count_7d INTEGER DEFAULT 0,
  replies_count_7d INTEGER DEFAULT 0,
  reposts_count_7d INTEGER DEFAULT 0,
  views_count_7d INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(competitor_id, date)
);

CREATE INDEX IF NOT EXISTS idx_competitor_snapshots_competitor_id ON public.competitor_snapshots(competitor_id);

-- ============================================
-- COMPETITOR TOP POSTS
-- ============================================
CREATE TABLE IF NOT EXISTS public.competitor_top_posts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  competitor_id UUID NOT NULL REFERENCES public.competitors(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_competitor_id ON public.competitor_top_posts(competitor_id);
CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_engagement ON public.competitor_top_posts(engagement_score DESC);

-- ============================================
-- AUTO-POST CONFIG
-- ============================================
CREATE TABLE IF NOT EXISTS public.auto_post_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL UNIQUE,
  enabled BOOLEAN DEFAULT FALSE,
  posts_per_day INTEGER DEFAULT 8,
  min_interval_minutes INTEGER DEFAULT 20,
  max_interval_minutes INTEGER DEFAULT 45,
  media_attachment_chance INTEGER DEFAULT 50,
  media_source TEXT DEFAULT 'global',
  active_hours_start INTEGER DEFAULT 8,
  active_hours_end INTEGER DEFAULT 22,
  enable_weekends BOOLEAN DEFAULT TRUE,
  round_robin_enabled BOOLEAN DEFAULT TRUE,
  selected_groups TEXT[],
  pause_on_low_performance BOOLEAN DEFAULT FALSE,
  performance_threshold DECIMAL(5, 2) DEFAULT 2.0,
  performance_check_window INTEGER DEFAULT 10,
  enable_competitor_adaptation BOOLEAN DEFAULT FALSE,
  competitor_adapt_ratio INTEGER DEFAULT 20,
  last_updated TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- AUTO-POST QUEUE
-- ============================================
CREATE TABLE IF NOT EXISTS public.auto_post_queue (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL,
  content TEXT NOT NULL,
  group_id TEXT,
  times_used INTEGER DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  added_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_workspace_id ON public.auto_post_queue(workspace_id);

-- ============================================
-- AUTO-POST STATE
-- ============================================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'auto_post_state' AND column_name = 'current_queue_index') THEN
    ALTER TABLE public.auto_post_state ADD COLUMN current_queue_index INTEGER DEFAULT 0;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'auto_post_state' AND column_name = 'current_account_index') THEN
    ALTER TABLE public.auto_post_state ADD COLUMN current_account_index INTEGER DEFAULT 0;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'auto_post_state' AND column_name = 'next_post_time') THEN
    ALTER TABLE public.auto_post_state ADD COLUMN next_post_time TIMESTAMPTZ;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'auto_post_state' AND column_name = 'last_reset_date') THEN
    ALTER TABLE public.auto_post_state ADD COLUMN last_reset_date DATE;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'auto_post_state' AND column_name = 'account_post_counts') THEN
    ALTER TABLE public.auto_post_state ADD COLUMN account_post_counts JSONB DEFAULT '{}';
  END IF;
END $$;

-- ============================================
-- AUTO-POST ACTIVITY (live feed)
-- ============================================
CREATE TABLE IF NOT EXISTS public.auto_post_activity (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL,
  activity_type TEXT NOT NULL,
  account_handle TEXT,
  post_index INTEGER,
  next_post_in INTEGER,
  message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auto_post_activity_workspace_id ON public.auto_post_activity(workspace_id);

-- ============================================
-- SAVED COMPETITOR POSTS - Add missing columns
-- ============================================
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'post_url') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN post_url TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'tags') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN tags TEXT[];
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'thumbnail_url') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN thumbnail_url TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'author_name') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN author_name TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'post_text') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN post_text TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'author_avatar_url') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN author_avatar_url TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'timestamp') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN timestamp TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'is_favorite') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN is_favorite BOOLEAN DEFAULT FALSE;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'engagement_score') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN engagement_score DECIMAL(10, 2);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'like_count') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN like_count INTEGER;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'reply_count') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN reply_count INTEGER;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'repost_count') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN repost_count INTEGER;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'view_count') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN view_count INTEGER;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'auto_populated') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN auto_populated BOOLEAN DEFAULT FALSE;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'source_type') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN source_type TEXT DEFAULT 'manual';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'media_type') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN media_type TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'media_url') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN media_url TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'saved_competitor_posts' AND column_name = 'saved_at') THEN
    ALTER TABLE public.saved_competitor_posts ADD COLUMN saved_at TIMESTAMPTZ DEFAULT NOW();
  END IF;
END $$;

-- ============================================
-- ENABLE RLS
-- ============================================
ALTER TABLE public.competitors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.competitor_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.competitor_top_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auto_post_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auto_post_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auto_post_activity ENABLE ROW LEVEL SECURITY;

-- ============================================
-- RLS POLICIES
-- ============================================

-- Competitors
DROP POLICY IF EXISTS "Users can manage own competitors" ON public.competitors;
CREATE POLICY "Users can manage own competitors" ON public.competitors
  FOR ALL USING (auth.uid()::text = user_id);

-- Competitor Snapshots (through competitor ownership)
DROP POLICY IF EXISTS "Users can view competitor snapshots" ON public.competitor_snapshots;
CREATE POLICY "Users can view competitor snapshots" ON public.competitor_snapshots
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.competitors
      WHERE competitors.id = competitor_snapshots.competitor_id
      AND competitors.user_id = auth.uid()::text
    )
  );

DROP POLICY IF EXISTS "Users can insert competitor snapshots" ON public.competitor_snapshots;
CREATE POLICY "Users can insert competitor snapshots" ON public.competitor_snapshots
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.competitors
      WHERE competitors.id = competitor_snapshots.competitor_id
      AND competitors.user_id = auth.uid()::text
    )
  );

-- Competitor Top Posts
DROP POLICY IF EXISTS "Users can view competitor top posts" ON public.competitor_top_posts;
CREATE POLICY "Users can view competitor top posts" ON public.competitor_top_posts
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.competitors
      WHERE competitors.id = competitor_top_posts.competitor_id
      AND competitors.user_id = auth.uid()::text
    )
  );

DROP POLICY IF EXISTS "Users can insert competitor top posts" ON public.competitor_top_posts;
CREATE POLICY "Users can insert competitor top posts" ON public.competitor_top_posts
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.competitors
      WHERE competitors.id = competitor_top_posts.competitor_id
      AND competitors.user_id = auth.uid()::text
    )
  );

-- Auto-post config (through workspace ownership)
DROP POLICY IF EXISTS "Users can manage auto post config" ON public.auto_post_config;
CREATE POLICY "Users can manage auto post config" ON public.auto_post_config
  FOR ALL USING (
    EXISTS (
      SELECT 1 FROM public.workspaces
      WHERE workspaces.id::text = auto_post_config.workspace_id
      AND workspaces.owner_id = auth.uid()::text
    )
  );

-- Auto-post queue
DROP POLICY IF EXISTS "Users can manage auto post queue" ON public.auto_post_queue;
CREATE POLICY "Users can manage auto post queue" ON public.auto_post_queue
  FOR ALL USING (
    EXISTS (
      SELECT 1 FROM public.workspaces
      WHERE workspaces.id::text = auto_post_queue.workspace_id
      AND workspaces.owner_id = auth.uid()::text
    )
  );

-- Auto-post activity
DROP POLICY IF EXISTS "Users can view auto post activity" ON public.auto_post_activity;
CREATE POLICY "Users can view auto post activity" ON public.auto_post_activity
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.workspaces
      WHERE workspaces.id::text = auto_post_activity.workspace_id
      AND workspaces.owner_id = auth.uid()::text
    )
  );

DROP POLICY IF EXISTS "Users can insert auto post activity" ON public.auto_post_activity;
CREATE POLICY "Users can insert auto post activity" ON public.auto_post_activity
  FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.workspaces
      WHERE workspaces.id::text = auto_post_activity.workspace_id
      AND workspaces.owner_id = auth.uid()::text
    )
  );

-- ============================================
-- DONE!
-- ============================================
SELECT 'Migration v3 completed successfully!' as status;
