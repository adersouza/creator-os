-- Backfilled from DB migration history
CREATE TABLE IF NOT EXISTS agent_approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  session_id TEXT,
  context TEXT NOT NULL,
  proposed_actions JSONB NOT NULL DEFAULT '[]',
  urgency TEXT NOT NULL DEFAULT 'medium' CHECK (urgency IN ('low', 'medium', 'high')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '24 hours',
  decided_at TIMESTAMPTZ,
  decision_note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_approvals_user_id_status_idx ON agent_approvals(user_id, status);
CREATE INDEX IF NOT EXISTS agent_approvals_created_at_idx ON agent_approvals(created_at DESC);
ALTER TABLE agent_approvals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users manage own approvals" ON agent_approvals FOR ALL USING (auth.uid()::text = user_id);
