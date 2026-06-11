-- Backfilled from DB migration history
CREATE TABLE IF NOT EXISTS agent_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  tool_name TEXT NOT NULL,
  params_json JSONB,
  result_summary TEXT,
  success BOOLEAN NOT NULL DEFAULT true,
  duration_ms INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_actions_user_created ON agent_actions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_actions_session ON agent_actions (session_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_tool ON agent_actions (user_id, tool_name);
ALTER TABLE agent_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can read own agent actions" ON agent_actions FOR SELECT USING (auth.uid()::text = user_id);
CREATE POLICY "Users can insert own agent actions" ON agent_actions FOR INSERT WITH CHECK (auth.uid()::text = user_id);
