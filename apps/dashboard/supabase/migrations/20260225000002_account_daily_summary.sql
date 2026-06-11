-- Pre-computed daily per-account metrics for fast dashboard loading
CREATE TABLE IF NOT EXISTS account_daily_summary (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  platform TEXT NOT NULL DEFAULT 'threads',
  date DATE NOT NULL,

  -- Core metrics
  followers_count INTEGER DEFAULT 0,
  follower_growth INTEGER DEFAULT 0,
  total_views INTEGER DEFAULT 0,
  total_likes INTEGER DEFAULT 0,
  total_replies INTEGER DEFAULT 0,
  total_reposts INTEGER DEFAULT 0,
  engagement_rate DECIMAL(8,4) DEFAULT 0,
  posts_published INTEGER DEFAULT 0,

  -- Best post of the day
  best_post_id TEXT,
  best_post_views INTEGER DEFAULT 0,
  avg_views_per_post INTEGER DEFAULT 0,

  -- Day-over-day trends (percentage change)
  views_trend_pct DECIMAL(8,2) DEFAULT 0,
  engagement_trend_pct DECIMAL(8,2) DEFAULT 0,
  follower_trend_pct DECIMAL(8,2) DEFAULT 0,

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(account_id, platform, date)
);

CREATE INDEX IF NOT EXISTS idx_account_daily_summary_account_date
  ON account_daily_summary(account_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_account_daily_summary_user_date
  ON account_daily_summary(user_id, date DESC);

ALTER TABLE account_daily_summary ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own account daily summaries"
  ON account_daily_summary FOR SELECT
  USING ((select auth.uid())::text = user_id);

CREATE POLICY "Service role full access on account_daily_summary"
  ON account_daily_summary FOR ALL
  USING (true) WITH CHECK (true);
