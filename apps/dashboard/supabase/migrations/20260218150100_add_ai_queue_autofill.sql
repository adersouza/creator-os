-- Migration: Add AI Queue Auto-Fill Feature
-- Enables auto-poster to automatically generate posts using AI when queue runs low

-- Add new columns to auto_post_config for AI auto-fill settings
ALTER TABLE public.auto_post_config
ADD COLUMN IF NOT EXISTS enable_ai_queue_fill BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS ai_queue_min_threshold INTEGER DEFAULT 3,
ADD COLUMN IF NOT EXISTS ai_posts_per_fill INTEGER DEFAULT 2,
ADD COLUMN IF NOT EXISTS ai_content_style TEXT DEFAULT 'punchy' CHECK (ai_content_style IN ('punchy', 'controversial', 'story', 'question', 'mixed')),
ADD COLUMN IF NOT EXISTS ai_daily_generation_limit INTEGER DEFAULT 10,
ADD COLUMN IF NOT EXISTS ai_generations_today INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS ai_last_generation_date DATE;

-- Add predicted_viral_score to queue items for AI-generated posts
ALTER TABLE public.auto_post_queue
ADD COLUMN IF NOT EXISTS predicted_viral_score INTEGER,
ADD COLUMN IF NOT EXISTS ai_style TEXT;

-- Add index for efficient queue count queries
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_pending
ON public.auto_post_queue(workspace_id, status)
WHERE status = 'pending';

-- Comment explaining the feature
COMMENT ON COLUMN public.auto_post_config.enable_ai_queue_fill IS 'When enabled, AI will auto-generate posts when queue runs low';
COMMENT ON COLUMN public.auto_post_config.ai_queue_min_threshold IS 'Minimum posts in queue before triggering AI generation';
COMMENT ON COLUMN public.auto_post_config.ai_posts_per_fill IS 'Number of posts to generate per fill cycle';
COMMENT ON COLUMN public.auto_post_config.ai_content_style IS 'Preferred content style: punchy, controversial, story, question, or mixed';
COMMENT ON COLUMN public.auto_post_config.ai_daily_generation_limit IS 'Max AI-generated posts per day (cost control)';
