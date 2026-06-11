-- Add addon tracking columns to profiles (used by subscription addon management)
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS extra_accounts integer DEFAULT 0;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS extra_team_members integer DEFAULT 0;
