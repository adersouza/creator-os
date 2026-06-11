-- Crisis Detection Events
-- Tracks negative sentiment spikes and engagement crashes

CREATE TABLE IF NOT EXISTS crisis_events (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id TEXT,
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  post_id TEXT,
  severity TEXT NOT NULL,
  trigger_reason TEXT NOT NULL,
  negative_count INTEGER,
  total_count INTEGER,
  negative_ratio NUMERIC,
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_crisis_events_user ON crisis_events(user_id);
CREATE INDEX IF NOT EXISTS idx_crisis_events_active ON crisis_events(user_id) WHERE resolved_at IS NULL;

ALTER TABLE crisis_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own crisis events" ON crisis_events
  FOR ALL USING (auth.uid() = user_id);
