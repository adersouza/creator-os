-- Add missing columns to account_analytics for delta calculations
-- and Instagram-specific metrics tracking

ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS followers_count INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS following_count INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS follower_growth INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS total_quotes INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS total_shares INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS total_reach INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS total_saves INTEGER DEFAULT 0;

-- Instagram-specific account-level metrics
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_reach INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_impressions INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_accounts_engaged INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_total_interactions INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_profile_views INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_website_clicks INTEGER DEFAULT 0;
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_non_follower_reach_pct NUMERIC DEFAULT 0;
