-- Add ig_profile_visits column to posts table for story metrics
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_profile_visits integer DEFAULT 0;
