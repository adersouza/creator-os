-- Cache table for Instagram collaboration invites
-- Meta doesn't send collab webhooks, so we cache API results + daily refresh

CREATE TABLE IF NOT EXISTS ig_collab_invites (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_id UUID NOT NULL REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  caption TEXT,
  media_type TEXT,
  media_url TEXT,
  permalink TEXT,
  owner_id TEXT,
  owner_username TEXT,
  status TEXT DEFAULT 'pending',
  discovered_at TIMESTAMPTZ DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_collab_invites_user ON ig_collab_invites(user_id, status);
ALTER TABLE ig_collab_invites ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own collab invites" ON ig_collab_invites FOR SELECT USING (auth.uid()::text = user_id);
