-- Instagram Hashtag Tracking
-- Enforces 30 unique hashtags per 7-day window per user (Instagram API limit)

CREATE TABLE IF NOT EXISTS ig_hashtag_tracking (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  ig_account_id TEXT NOT NULL,
  hashtag_name TEXT NOT NULL,
  hashtag_ig_id TEXT NOT NULL,
  searched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, hashtag_ig_id)
);

-- Index for efficient 7-day window queries
CREATE INDEX IF NOT EXISTS idx_ig_hashtag_tracking_user_searched
  ON ig_hashtag_tracking(user_id, searched_at DESC);

-- RLS policies
ALTER TABLE ig_hashtag_tracking ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own hashtag tracking"
  ON ig_hashtag_tracking FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own hashtag tracking"
  ON ig_hashtag_tracking FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete their own hashtag tracking"
  ON ig_hashtag_tracking FOR DELETE
  USING (auth.uid() = user_id);
