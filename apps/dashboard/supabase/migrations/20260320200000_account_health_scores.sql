-- Account Health Scores — 0-100 per-account score for dynamic post allocation
-- Computed daily by health-monitor cron. Drives post frequency auto-adjustment.
-- Extends the existing account_health_snapshots table with a composite score.

-- Add health_score column to existing snapshots table
ALTER TABLE account_health_snapshots
  ADD COLUMN IF NOT EXISTS health_score integer DEFAULT 50,
  ADD COLUMN IF NOT EXISTS health_tier text DEFAULT 'healthy',  -- star | healthy | struggling | dead
  ADD COLUMN IF NOT EXISTS posts_per_day_override integer,  -- auto-calculated allocation
  ADD COLUMN IF NOT EXISTS views_per_post_7d numeric(10,2) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS reply_rate_7d numeric(8,4) DEFAULT 0,
  ADD COLUMN IF NOT EXISTS follower_growth_7d integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS days_since_zero_views integer DEFAULT 999,
  ADD COLUMN IF NOT EXISTS account_age_days integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS is_shadowbanned boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS consecutive_dead_days integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_recovery_attempt timestamptz,
  ADD COLUMN IF NOT EXISTS recovery_attempts integer DEFAULT 0,
  ADD COLUMN IF NOT EXISTS auto_disabled boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS auto_disabled_at timestamptz;

-- Index for dynamic allocation queries
CREATE INDEX IF NOT EXISTS idx_health_score_tier
  ON account_health_snapshots(user_id, health_tier, health_score DESC);

-- Index for auto-disable recovery checks
CREATE INDEX IF NOT EXISTS idx_health_auto_disabled
  ON account_health_snapshots(auto_disabled, last_recovery_attempt)
  WHERE auto_disabled = true;
