-- Add modern story insight fields (v25.0 API compliance)
-- Keep deprecated columns (impressions, taps_forward, taps_back, exits) for backwards compat

ALTER TABLE ig_story_insights ADD COLUMN IF NOT EXISTS views INTEGER DEFAULT 0;
ALTER TABLE ig_story_insights ADD COLUMN IF NOT EXISTS navigation JSONB;
ALTER TABLE ig_story_insights ADD COLUMN IF NOT EXISTS follows INTEGER DEFAULT 0;
ALTER TABLE ig_story_insights ADD COLUMN IF NOT EXISTS shares INTEGER DEFAULT 0;
ALTER TABLE ig_story_insights ADD COLUMN IF NOT EXISTS total_interactions INTEGER DEFAULT 0;
