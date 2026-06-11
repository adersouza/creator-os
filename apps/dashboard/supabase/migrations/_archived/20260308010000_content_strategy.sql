-- Content Strategy
-- Adds content_strategy JSONB to account_groups, alongside voice_profile.
-- Schema: { pillars, weekly_target, tone_notes, topics_to_avoid, cta_rotation, peak_windows }

ALTER TABLE account_groups
  ADD COLUMN IF NOT EXISTS content_strategy JSONB;

COMMENT ON COLUMN account_groups.content_strategy IS
  'Agent content strategy doc: pillars, weekly_target, tone_notes, topics_to_avoid, cta_rotation, peak_windows';
