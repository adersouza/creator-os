-- Add beta_feedback JSONB array column to profiles for storing beta user feedback
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS beta_feedback JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN profiles.beta_feedback IS 'Array of {text, category, submitted_at} feedback entries from beta users';
