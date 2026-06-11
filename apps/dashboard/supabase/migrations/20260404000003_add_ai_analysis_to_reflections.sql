-- Add AI analysis column to post_reflections for "why this worked/failed" feature
ALTER TABLE post_reflections ADD COLUMN IF NOT EXISTS ai_analysis TEXT;
