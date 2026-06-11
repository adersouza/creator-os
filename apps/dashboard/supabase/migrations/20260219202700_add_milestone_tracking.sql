ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_milestone_celebrated integer DEFAULT 0;
ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS last_milestone_celebrated integer DEFAULT 0;
