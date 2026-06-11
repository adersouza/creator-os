-- Spotlight staging: auto-flag videos for Snap Spotlight reposting
ALTER TABLE media ADD COLUMN IF NOT EXISTS spotlight_eligible BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_media_spotlight ON media (spotlight_eligible, group_id) WHERE spotlight_eligible = true;
