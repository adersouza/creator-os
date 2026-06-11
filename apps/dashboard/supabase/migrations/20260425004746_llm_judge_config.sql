-- LLM Judge for autoposter quality — opt-in per group.
--
-- Adds two columns to auto_post_group_config:
--   llm_judge_enabled  BOOLEAN  default false  — kill switch per group
--   llm_judge_min_score NUMERIC(3,1) default 3.0 — composite reject threshold (1.0–5.0)
--
-- Rationale: prior regex-only scorer rejected 58/73 good posts with floor=2.0,
-- so the floor was lowered to 1.0 (functionally inert). The LLM judge is a
-- richer 5-dim Gemini call (hook / voice / safety / quality / novelty) that
-- can replace the dropped floor without the regex's false-reject rate. We ship
-- it disabled-by-default until the eval harness exists to calibrate
-- thresholds against ground-truth labels — see memory/ai_widget_audit_2026.md.
--
-- Per-post judge output is written to auto_post_queue.metadata.judge so a
-- future eval harness can replay decisions against hand-labeled outcomes
-- without a schema change.

ALTER TABLE auto_post_group_config
  ADD COLUMN IF NOT EXISTS llm_judge_enabled BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS llm_judge_min_score NUMERIC(3,1) NOT NULL DEFAULT 3.0
    CHECK (llm_judge_min_score >= 1.0 AND llm_judge_min_score <= 5.0);

COMMENT ON COLUMN auto_post_group_config.llm_judge_enabled IS
  'Opt-in flag for the Gemini-backed LLM quality judge. Default false. When true, posts surviving the regex scorer are batch-judged on hook/voice/safety/quality/novelty and rejected if composite < llm_judge_min_score. Fail-open: judge errors do not block the pipeline.';

COMMENT ON COLUMN auto_post_group_config.llm_judge_min_score IS
  'Composite (1.0–5.0) threshold below which the LLM judge rejects a post. Uncalibrated until eval harness exists; tune cautiously.';
