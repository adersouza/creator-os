-- ============================================
-- GAP #13: RSS FEEDS → DRAFT PIPELINE
-- ============================================

CREATE TABLE IF NOT EXISTS public.rss_feeds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  feed_url TEXT NOT NULL,
  title TEXT,
  platform TEXT NOT NULL DEFAULT 'threads' CHECK (platform IN ('threads', 'instagram')),
  account_id TEXT REFERENCES public.accounts(id) ON DELETE SET NULL,
  instagram_account_id UUID REFERENCES public.instagram_accounts(id) ON DELETE SET NULL,
  -- Behavior
  is_active BOOLEAN DEFAULT true,
  auto_draft BOOLEAN DEFAULT true,        -- create drafts automatically
  auto_schedule BOOLEAN DEFAULT false,    -- schedule instead of draft (Pro+)
  adapt_with_ai BOOLEAN DEFAULT true,     -- rewrite for social media tone
  -- Polling state
  last_checked_at TIMESTAMPTZ,
  last_entry_guid TEXT,                   -- most recent guid/link seen (dedup)
  check_interval_hours INTEGER DEFAULT 6, -- how often to check (min 1)
  error_count INTEGER DEFAULT 0,          -- consecutive errors
  last_error TEXT,
  -- Limits
  max_drafts_per_check INTEGER DEFAULT 3, -- cap per poll cycle
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, feed_url)
);

CREATE INDEX IF NOT EXISTS idx_rss_feeds_user ON public.rss_feeds(user_id);
CREATE INDEX IF NOT EXISTS idx_rss_feeds_active ON public.rss_feeds(is_active, last_checked_at)
  WHERE is_active = true;

ALTER TABLE public.rss_feeds ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY "Users manage own RSS feeds"
    ON public.rss_feeds FOR ALL
    USING (auth.uid()::text = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Track which RSS entries have been processed (dedup)
CREATE TABLE IF NOT EXISTS public.rss_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feed_id UUID NOT NULL REFERENCES public.rss_feeds(id) ON DELETE CASCADE,
  guid TEXT NOT NULL,               -- RSS guid or link (unique identifier)
  title TEXT,
  link TEXT,
  content_snippet TEXT,             -- first 500 chars of content
  published_at TIMESTAMPTZ,
  post_id TEXT REFERENCES public.posts(id) ON DELETE SET NULL, -- created draft
  processed_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(feed_id, guid)
);

CREATE INDEX IF NOT EXISTS idx_rss_entries_feed ON public.rss_entries(feed_id);

ALTER TABLE public.rss_entries ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY "Users manage own RSS entries"
    ON public.rss_entries FOR ALL
    USING (
      EXISTS (
        SELECT 1 FROM public.rss_feeds rf
        WHERE rf.id = rss_entries.feed_id
        AND rf.user_id = auth.uid()::text
      )
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================
-- GAP #14: CONTENT RECYCLING / EVERGREEN
-- ============================================

ALTER TABLE public.posts
  ADD COLUMN IF NOT EXISTS is_evergreen BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS evergreen_interval_days INTEGER DEFAULT 30,
  ADD COLUMN IF NOT EXISTS last_recycled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS recycle_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS max_recycles INTEGER DEFAULT 5,
  ADD COLUMN IF NOT EXISTS evergreen_min_engagement DECIMAL(5,4) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS recycled_from_id TEXT REFERENCES public.posts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_posts_evergreen ON public.posts(is_evergreen, last_recycled_at)
  WHERE is_evergreen = true AND status = 'published';

-- ============================================
-- GAP #15: TREND FORECASTS
-- ============================================

CREATE TABLE IF NOT EXISTS public.trend_forecasts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id) ON DELETE CASCADE,
  forecast_date DATE NOT NULL,            -- the date this forecast was computed
  -- Follower projection (next 30 days)
  follower_forecast JSONB,                -- [{date, predicted, upper, lower}, ...]
  follower_trend TEXT CHECK (follower_trend IN ('accelerating', 'steady', 'decelerating', 'declining')),
  follower_velocity DECIMAL,              -- followers/day rate of change
  -- Engagement projection
  engagement_forecast JSONB,              -- [{date, predicted}, ...]
  engagement_trend TEXT CHECK (engagement_trend IN ('rising', 'stable', 'falling')),
  avg_engagement_rate DECIMAL(5,4),
  -- Best posting windows
  best_hours JSONB,                       -- [{hour, dayOfWeek, avgEngagement}, ...]
  best_content_types JSONB,               -- [{type, avgEngagement, count}, ...]
  -- Topic/hashtag trends
  rising_topics JSONB,                    -- [{topic, growth_pct, volume}, ...]
  declining_topics JSONB,                 -- [{topic, decline_pct, volume}, ...]
  -- Seasonal patterns
  seasonal_pattern JSONB,                 -- {dayOfWeek: {avgViews, avgLikes, avgEngagement}}
  -- Alerts / signals
  signals JSONB,                          -- [{type, severity, message}, ...]
  -- Metadata
  data_points_used INTEGER,
  r_squared DECIMAL(5,4),                 -- model fit quality
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trend_forecasts_unique
  ON public.trend_forecasts(user_id, account_id, forecast_date);
CREATE INDEX IF NOT EXISTS idx_trend_forecasts_user ON public.trend_forecasts(user_id);
CREATE INDEX IF NOT EXISTS idx_trend_forecasts_date ON public.trend_forecasts(forecast_date DESC);

ALTER TABLE public.trend_forecasts ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  CREATE POLICY "Users view own trend forecasts"
    ON public.trend_forecasts FOR ALL
    USING (auth.uid()::text = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
