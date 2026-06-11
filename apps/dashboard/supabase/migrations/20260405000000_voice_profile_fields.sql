-- Voice Profile Engineering 2026: per-group voice calibration fields
-- vulnerability_ratio: target % of vulnerability/confession posts (default 0.25 = 25%)
-- sentence_length_target: { avg, variance, min, max } per persona
-- time_of_day_modifiers: { morning, afternoon, evening, latenight } energy overrides

ALTER TABLE account_groups
  ADD COLUMN IF NOT EXISTS vulnerability_ratio NUMERIC DEFAULT 0.25,
  ADD COLUMN IF NOT EXISTS sentence_length_target JSONB,
  ADD COLUMN IF NOT EXISTS time_of_day_modifiers JSONB;

COMMENT ON COLUMN account_groups.vulnerability_ratio IS 'Target % of vulnerability/confession posts (0-1). Research: 0.25-0.30 optimal for parasocial bond building.';
COMMENT ON COLUMN account_groups.sentence_length_target IS 'JSON: { avg: number, variance: "low"|"moderate"|"high"|"very_high", min: number, max: number }';
COMMENT ON COLUMN account_groups.time_of_day_modifiers IS 'JSON: { morning: string, afternoon: string, evening: string, latenight: string } — energy overrides per time block';
