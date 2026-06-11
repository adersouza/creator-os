-- Add shadowban flag to accounts table
-- Used by autoposter round-robin to skip dead accounts (0 views after 3+ days of posting)
-- Set by daily-orchestrator Phase 13 (shadowban-scanner), auto-cleared when views recover
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS is_shadowbanned BOOLEAN NOT NULL DEFAULT false;

-- Index for quick filtering in autoposter queries
CREATE INDEX IF NOT EXISTS idx_accounts_shadowbanned ON accounts (is_shadowbanned) WHERE is_shadowbanned = true;
