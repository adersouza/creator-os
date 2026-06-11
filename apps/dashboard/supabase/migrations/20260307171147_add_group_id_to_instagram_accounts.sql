-- Backfilled from DB: applied via Supabase dashboard on 2026-03-07
-- Adds group_id FK to instagram_accounts for account grouping

ALTER TABLE instagram_accounts
  ADD COLUMN IF NOT EXISTS group_id TEXT REFERENCES account_groups(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS instagram_accounts_group_id_idx ON instagram_accounts(group_id);
