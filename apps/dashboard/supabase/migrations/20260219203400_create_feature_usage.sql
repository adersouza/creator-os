CREATE TABLE IF NOT EXISTS feature_usage (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  feature_name text NOT NULL,
  used_at timestamptz DEFAULT now()
);
ALTER TABLE feature_usage ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users own their usage" ON feature_usage FOR ALL USING (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS idx_feature_usage_user ON feature_usage(user_id, feature_name, used_at);
