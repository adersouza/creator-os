-- Share of voice history: track competitive share over time
CREATE TABLE IF NOT EXISTS share_of_voice_history (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL,
  competitor_id TEXT,
  date DATE NOT NULL,
  engagement_share NUMERIC(5,2),
  follower_share NUMERIC(5,2),
  content_volume_share NUMERIC(5,2),
  recorded_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE share_of_voice_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users access own SoV history"
  ON share_of_voice_history FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

CREATE UNIQUE INDEX idx_sov_history_user_account_date
  ON share_of_voice_history(user_id, account_id, date);

CREATE INDEX idx_sov_history_account_date
  ON share_of_voice_history(account_id, date);
