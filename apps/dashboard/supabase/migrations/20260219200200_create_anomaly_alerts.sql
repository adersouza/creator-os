CREATE TABLE IF NOT EXISTS anomaly_alerts (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  account_id text REFERENCES accounts(id) ON DELETE CASCADE,
  instagram_account_id uuid REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  platform text NOT NULL CHECK (platform IN ('threads', 'instagram')),
  alert_type text NOT NULL CHECK (alert_type IN ('shadowban_suspected', 'engagement_drop', 'reach_anomaly', 'follower_drop')),
  severity text NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  title text NOT NULL,
  description text,
  data jsonb DEFAULT '{}',
  ai_analysis text,
  dismissed_at timestamptz,
  created_at timestamptz DEFAULT now()
);

ALTER TABLE anomaly_alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own alerts" ON anomaly_alerts FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "Users can dismiss own alerts" ON anomaly_alerts FOR UPDATE USING (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS idx_anomaly_alerts_user ON anomaly_alerts(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomaly_alerts_account ON anomaly_alerts(account_id, created_at DESC);
