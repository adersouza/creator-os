CREATE TABLE IF NOT EXISTS post_metric_history (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  post_id text NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  account_id text NOT NULL,
  platform text NOT NULL,
  snapshot_at timestamptz DEFAULT now(),
  hours_since_publish numeric,
  views_count integer DEFAULT 0,
  likes_count integer DEFAULT 0,
  replies_count integer DEFAULT 0,
  reposts_count integer DEFAULT 0,
  shares_count integer DEFAULT 0,
  saves_count integer DEFAULT 0,
  reach integer DEFAULT 0,
  engagement_rate numeric DEFAULT 0
);

ALTER TABLE post_metric_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own post history" ON post_metric_history FOR SELECT USING (
  account_id IN (SELECT id FROM accounts WHERE user_id = auth.uid()::text)
);
CREATE INDEX IF NOT EXISTS idx_post_metric_history_post ON post_metric_history(post_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_post_metric_history_account ON post_metric_history(account_id, snapshot_at);
