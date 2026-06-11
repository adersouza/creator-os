-- Add predicted_viral_score to posts table (float, stores the score at publish time)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS predicted_viral_score REAL;

-- Viral score calibration table: stores predicted vs actual pairs per user
CREATE TABLE IF NOT EXISTS viral_score_calibration (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  predicted REAL NOT NULL,
  actual REAL NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(post_id)
);

-- Index for fast lookup by user
CREATE INDEX IF NOT EXISTS idx_viral_score_calibration_user_id ON viral_score_calibration(user_id);

-- RLS
ALTER TABLE viral_score_calibration ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own calibration data"
  ON viral_score_calibration FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage calibration data"
  ON viral_score_calibration FOR ALL
  USING (true)
  WITH CHECK (true);
