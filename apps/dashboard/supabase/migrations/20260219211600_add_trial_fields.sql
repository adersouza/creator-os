ALTER TABLE profiles ADD COLUMN IF NOT EXISTS trial_started_at timestamptz;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS trial_ends_at timestamptz;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS trial_used boolean DEFAULT false;
