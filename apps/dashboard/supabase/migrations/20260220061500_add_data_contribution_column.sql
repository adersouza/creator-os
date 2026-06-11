-- Add data_contribution_opted_in column to user_preferences
ALTER TABLE user_preferences
ADD COLUMN IF NOT EXISTS data_contribution_opted_in boolean DEFAULT false;
