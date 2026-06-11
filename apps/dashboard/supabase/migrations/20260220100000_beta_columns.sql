-- Add beta user columns to profiles table
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS is_beta_user BOOLEAN DEFAULT false;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS beta_invite_code TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS beta_joined_at TIMESTAMPTZ;
