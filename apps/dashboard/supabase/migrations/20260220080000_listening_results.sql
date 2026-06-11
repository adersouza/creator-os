-- Social Listening Alerts + Results
-- Keyword monitoring configuration and trend analysis

-- listening_alerts may already exist (created by frontend).
-- Add missing columns if needed.
ALTER TABLE listening_alerts ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE listening_alerts ADD COLUMN IF NOT EXISTS alert_type TEXT NOT NULL DEFAULT 'spike';
ALTER TABLE listening_alerts ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_listening_alerts_user ON listening_alerts(user_id);

ALTER TABLE listening_alerts ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "Users manage own listening alerts" ON listening_alerts
    FOR ALL USING (auth.uid() = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS listening_results (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  alert_id UUID REFERENCES listening_alerts(id) ON DELETE CASCADE,
  workspace_id TEXT,
  keyword TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'combined',
  result_count INTEGER NOT NULL DEFAULT 0,
  sentiment_breakdown JSONB,
  sample_posts JSONB,
  checked_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_listening_results_alert ON listening_results(alert_id);
CREATE INDEX IF NOT EXISTS idx_listening_results_checked ON listening_results(checked_at);

ALTER TABLE listening_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own listening results" ON listening_results
  FOR SELECT USING (
    alert_id IN (SELECT id FROM listening_alerts WHERE user_id = auth.uid())
  );
