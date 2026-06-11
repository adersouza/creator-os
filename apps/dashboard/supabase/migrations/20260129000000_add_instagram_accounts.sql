-- Instagram Accounts table
-- Mirrors the Threads `accounts` table structure with IG-specific columns
CREATE TABLE IF NOT EXISTS instagram_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  instagram_user_id TEXT NOT NULL,
  username TEXT,
  display_name TEXT,
  avatar_url TEXT,
  account_type TEXT, -- 'PERSONAL', 'BUSINESS', 'CREATOR'
  follower_count INTEGER DEFAULT 0,
  following_count INTEGER DEFAULT 0,
  media_count INTEGER DEFAULT 0,
  instagram_access_token_encrypted TEXT,
  token_expires_at TIMESTAMPTZ,
  is_active BOOLEAN DEFAULT TRUE,
  status TEXT DEFAULT 'active',
  baseline_follower_count INTEGER DEFAULT 0,
  baseline_following_count INTEGER DEFAULT 0,
  baseline_media_count INTEGER DEFAULT 0,
  last_synced_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(instagram_user_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_instagram_accounts_user_id ON instagram_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_instagram_accounts_status ON instagram_accounts(status);
CREATE INDEX IF NOT EXISTS idx_instagram_accounts_token_expires ON instagram_accounts(token_expires_at);

-- RLS
ALTER TABLE instagram_accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own instagram accounts"
  ON instagram_accounts FOR SELECT
  USING (auth.uid()::text = user_id);

CREATE POLICY "Users can insert own instagram accounts"
  ON instagram_accounts FOR INSERT
  WITH CHECK (auth.uid()::text = user_id);

CREATE POLICY "Users can update own instagram accounts"
  ON instagram_accounts FOR UPDATE
  USING (auth.uid()::text = user_id);

CREATE POLICY "Users can delete own instagram accounts"
  ON instagram_accounts FOR DELETE
  USING (auth.uid()::text = user_id);

CREATE POLICY "Service role full access to instagram accounts"
  ON instagram_accounts FOR ALL
  USING (auth.jwt()->>'role' = 'service_role');

-- Instagram rate limit tracking (50 posts per 24 hours)
CREATE TABLE IF NOT EXISTS ig_rate_limit_tracking (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  daily_count INTEGER DEFAULT 0,
  daily_reset_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '24 hours',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(account_id)
);

ALTER TABLE ig_rate_limit_tracking ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access to ig rate limits"
  ON ig_rate_limit_tracking FOR ALL
  USING (auth.jwt()->>'role' = 'service_role');
