-- Add engagement columns to competitor_snapshots for IG benchmarking
ALTER TABLE competitor_snapshots
  ADD COLUMN IF NOT EXISTS engagement_rate NUMERIC,
  ADD COLUMN IF NOT EXISTS avg_likes NUMERIC,
  ADD COLUMN IF NOT EXISTS avg_comments NUMERIC,
  ADD COLUMN IF NOT EXISTS media_count INTEGER;

-- Create competitor_alerts table for competitive intelligence notifications
CREATE TABLE IF NOT EXISTS competitor_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  competitor_id TEXT NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
  alert_type TEXT NOT NULL CHECK (alert_type IN ('follower_milestone', 'growth_spike', 'engagement_spike')),
  message TEXT NOT NULL,
  metadata JSONB DEFAULT '{}',
  read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: users see own alerts only
ALTER TABLE competitor_alerts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own alerts"
  ON competitor_alerts FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can update own alerts"
  ON competitor_alerts FOR UPDATE
  USING (auth.uid() = user_id);

-- Index for efficient queries on unread alerts
CREATE INDEX IF NOT EXISTS idx_competitor_alerts_user_read_created
  ON competitor_alerts (user_id, read, created_at DESC);
