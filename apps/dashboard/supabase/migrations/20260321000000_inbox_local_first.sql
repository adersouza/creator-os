-- Local-first inbox: store DM messages for conversation thread view
-- Webhook stores messages on arrival, frontend reads from DB only

CREATE TABLE IF NOT EXISTS inbox_dm_messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  ig_account_id UUID NOT NULL REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  sender_id TEXT,
  sender_username TEXT,
  message_text TEXT,
  attachment_type TEXT,
  attachment_url TEXT,
  is_echo BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL,
  synced_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dm_msgs_convo ON inbox_dm_messages(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dm_msgs_user ON inbox_dm_messages(user_id, ig_account_id);

-- RLS: users can only read their own messages
ALTER TABLE inbox_dm_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own DM messages"
  ON inbox_dm_messages FOR SELECT
  USING (auth.uid()::text = user_id);

-- Cursor tracking for incremental sync
ALTER TABLE instagram_accounts
  ADD COLUMN IF NOT EXISTS last_dm_sync_cursor TEXT,
  ADD COLUMN IF NOT EXISTS last_dm_sync_at TIMESTAMPTZ;

-- Threads reply sync tracking
ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS last_reply_sync_at TIMESTAMPTZ;
