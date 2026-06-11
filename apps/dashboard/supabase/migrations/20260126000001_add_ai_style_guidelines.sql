-- Migration: Add AI Style Guidelines
-- Allows users to define custom style rules for AI-generated content

ALTER TABLE public.auto_post_config
ADD COLUMN IF NOT EXISTS ai_style_guidelines TEXT;

COMMENT ON COLUMN public.auto_post_config.ai_style_guidelines IS 'User-defined style guidelines that AI follows when generating content (e.g., avoid emojis, keep under 100 words, use casual tone)';
