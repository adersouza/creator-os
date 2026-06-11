-- Add last_triggered_at to auto_reply_rules
ALTER TABLE auto_reply_rules ADD COLUMN IF NOT EXISTS last_triggered_at TIMESTAMPTZ;

-- Create auto_reply_logs table for cooldown tracking and audit
CREATE TABLE IF NOT EXISTS auto_reply_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id UUID NOT NULL REFERENCES auto_reply_rules(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  target_user_id TEXT NOT NULL,
  target_username TEXT,
  reply_to_id TEXT NOT NULL,
  reply_text TEXT NOT NULL,
  event_type TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auto_reply_logs_rule_user ON auto_reply_logs(rule_id, target_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_auto_reply_logs_account ON auto_reply_logs(account_id, created_at);

-- Enable RLS
ALTER TABLE auto_reply_logs ENABLE ROW LEVEL SECURITY;
