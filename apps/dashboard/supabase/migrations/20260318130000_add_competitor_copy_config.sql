-- Add competitor copy configuration to workspace-level auto_post_config
-- Supports automated copying of short, proven viral competitor posts into the AI queue fill pipeline.

ALTER TABLE auto_post_config
  ADD COLUMN IF NOT EXISTS competitor_copy_ratio NUMERIC DEFAULT 0.2
    CHECK (competitor_copy_ratio >= 0 AND competitor_copy_ratio <= 1),
  ADD COLUMN IF NOT EXISTS competitor_copy_max_words INTEGER DEFAULT 10
    CHECK (competitor_copy_max_words >= 1 AND competitor_copy_max_words <= 50);

COMMENT ON COLUMN auto_post_config.competitor_copy_ratio IS 'Fraction of AI queue fill that should be direct competitor post copies (0-1, default 0.2 = 20%)';
COMMENT ON COLUMN auto_post_config.competitor_copy_max_words IS 'Max word count for eligible competitor copy posts (default 10)';
