-- #67 + #69: Add needs_reauth flag and consecutive_refresh_failures to both account tables
-- #81: Partial index for token-refresh queries on accounts (aligns with is_active filter)
-- #82: Partial index for token-refresh queries on instagram_accounts

-- Threads accounts
ALTER TABLE accounts
  ADD COLUMN IF NOT EXISTS needs_reauth BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS consecutive_refresh_failures INTEGER NOT NULL DEFAULT 0;

-- Instagram accounts
ALTER TABLE instagram_accounts
  ADD COLUMN IF NOT EXISTS needs_reauth BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS consecutive_refresh_failures INTEGER NOT NULL DEFAULT 0;

-- #82: Composite partial index for instagram_accounts token refresh queries
-- Matches the accounts table pattern: idx_accounts_token_expires_at ON accounts(token_expires_at) WHERE is_active = true
CREATE INDEX IF NOT EXISTS idx_ig_accounts_token_expires_active
  ON instagram_accounts(token_expires_at)
  WHERE is_active = true;

-- Index for excluding needs_reauth accounts efficiently
CREATE INDEX IF NOT EXISTS idx_accounts_needs_reauth
  ON accounts(needs_reauth)
  WHERE needs_reauth = true;

CREATE INDEX IF NOT EXISTS idx_ig_accounts_needs_reauth
  ON instagram_accounts(needs_reauth)
  WHERE needs_reauth = true;
