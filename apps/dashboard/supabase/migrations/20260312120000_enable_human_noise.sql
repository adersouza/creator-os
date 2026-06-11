-- Add enable_human_noise to auto_post_group_config
-- Controls whether AI-generated content gets human noise injection before publishing
ALTER TABLE auto_post_group_config
  ADD COLUMN IF NOT EXISTS enable_human_noise BOOLEAN DEFAULT true;
