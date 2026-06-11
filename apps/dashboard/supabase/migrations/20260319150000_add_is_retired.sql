-- Account retirement: permanently flag dead accounts (0 views after 10+ posts)
-- Retired accounts are removed from all autoposter groups and skipped in rotation.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_retired BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_accounts_retired ON accounts (is_retired) WHERE is_retired = true;
