-- Migration: Group-Level Analytics Aggregation
-- Date: 2026-02-12
-- Purpose: Pre-computed group-level analytics to replace client-side N+1 aggregation.
-- Populated by the analytics-refresh cron job.

-- ============================================================================
-- 1. Group analytics table (daily snapshots per group)
-- ============================================================================

CREATE TABLE IF NOT EXISTS group_analytics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id TEXT NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  date DATE NOT NULL,

  -- Aggregate metrics across all accounts in the group
  total_followers INTEGER DEFAULT 0,
  total_views INTEGER DEFAULT 0,
  total_likes INTEGER DEFAULT 0,
  total_replies INTEGER DEFAULT 0,
  total_reposts INTEGER DEFAULT 0,
  total_quotes INTEGER DEFAULT 0,
  posts_count INTEGER DEFAULT 0,
  accounts_count INTEGER DEFAULT 0,

  -- Computed metrics
  avg_engagement_rate DECIMAL(8,4) DEFAULT 0,
  follower_growth INTEGER DEFAULT 0,   -- net change from previous day
  top_performing_account_id TEXT,       -- account with highest engagement

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(group_id, date)
);

-- ============================================================================
-- 2. Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_group_analytics_group_date
  ON group_analytics(group_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_group_analytics_user_date
  ON group_analytics(user_id, date DESC);

-- ============================================================================
-- 3. RLS Policies
-- ============================================================================

ALTER TABLE group_analytics ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own group analytics"
  ON group_analytics FOR SELECT
  USING ((select auth.uid())::text = user_id);

-- Service role (cron jobs) can insert/update
CREATE POLICY "Service role full access to group analytics"
  ON group_analytics FOR ALL
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- 4. SQL Function: Refresh group analytics for a user
-- ============================================================================

CREATE OR REPLACE FUNCTION refresh_group_analytics(p_user_id TEXT, p_date DATE DEFAULT CURRENT_DATE)
RETURNS INTEGER AS $$
DECLARE
  v_group RECORD;
  v_count INTEGER := 0;
  v_account_ids TEXT[];
  v_stats RECORD;
  v_prev_followers INTEGER;
  v_top_account TEXT;
BEGIN
  -- Loop through each group belonging to the user
  FOR v_group IN
    SELECT id, account_ids
    FROM account_groups
    WHERE user_id = p_user_id
      AND account_ids IS NOT NULL
      AND array_length(account_ids, 1) > 0
  LOOP
    -- Cast UUID[] to TEXT[] for the accounts query
    v_account_ids := v_group.account_ids::TEXT[];

    -- Aggregate latest analytics for accounts in this group
    SELECT
      COALESCE(SUM(aa.followers_count), 0) AS total_followers,
      COALESCE(SUM(aa.total_views), 0) AS total_views,
      COALESCE(SUM(aa.total_likes), 0) AS total_likes,
      COALESCE(SUM(aa.total_replies), 0) AS total_replies,
      COALESCE(SUM(aa.total_reposts), 0) AS total_reposts,
      COALESCE(SUM(aa.total_quotes), 0) AS total_quotes,
      COALESCE(SUM(aa.posts_count), 0) AS posts_count,
      COUNT(DISTINCT aa.account_id) AS accounts_count,
      CASE WHEN SUM(aa.total_views) > 0
        THEN (SUM(aa.total_likes) + SUM(aa.total_replies) + SUM(aa.total_reposts))::DECIMAL / SUM(aa.total_views) * 100
        ELSE 0
      END AS avg_engagement_rate
    INTO v_stats
    FROM account_analytics aa
    WHERE aa.account_id::TEXT = ANY(v_account_ids)
      AND aa.date = p_date;

    -- Get previous day's follower count for growth calculation
    SELECT COALESCE(total_followers, 0)
    INTO v_prev_followers
    FROM group_analytics
    WHERE group_id = v_group.id
      AND date = p_date - 1;

    -- Find top performing account (highest engagement rate)
    SELECT aa.account_id::TEXT
    INTO v_top_account
    FROM account_analytics aa
    WHERE aa.account_id::TEXT = ANY(v_account_ids)
      AND aa.date = p_date
      AND aa.total_views > 0
    ORDER BY (aa.total_likes + aa.total_replies + aa.total_reposts)::DECIMAL / aa.total_views DESC
    LIMIT 1;

    -- Upsert group analytics
    INSERT INTO group_analytics (
      group_id, user_id, date,
      total_followers, total_views, total_likes, total_replies,
      total_reposts, total_quotes, posts_count, accounts_count,
      avg_engagement_rate, follower_growth, top_performing_account_id,
      updated_at
    ) VALUES (
      v_group.id, p_user_id, p_date,
      v_stats.total_followers, v_stats.total_views, v_stats.total_likes,
      v_stats.total_replies, v_stats.total_reposts, v_stats.total_quotes,
      v_stats.posts_count, v_stats.accounts_count,
      v_stats.avg_engagement_rate,
      v_stats.total_followers - COALESCE(v_prev_followers, v_stats.total_followers),
      v_top_account,
      NOW()
    )
    ON CONFLICT (group_id, date) DO UPDATE SET
      total_followers = EXCLUDED.total_followers,
      total_views = EXCLUDED.total_views,
      total_likes = EXCLUDED.total_likes,
      total_replies = EXCLUDED.total_replies,
      total_reposts = EXCLUDED.total_reposts,
      total_quotes = EXCLUDED.total_quotes,
      posts_count = EXCLUDED.posts_count,
      accounts_count = EXCLUDED.accounts_count,
      avg_engagement_rate = EXCLUDED.avg_engagement_rate,
      follower_growth = EXCLUDED.follower_growth,
      top_performing_account_id = EXCLUDED.top_performing_account_id,
      updated_at = NOW();

    v_count := v_count + 1;
  END LOOP;

  RETURN v_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;
