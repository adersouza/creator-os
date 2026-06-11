-- Track which AI provider generated each post (gemini, xai, etc.)
-- Enables A/B testing providers with real engagement data
ALTER TABLE auto_post_queue ADD COLUMN IF NOT EXISTS ai_provider TEXT DEFAULT NULL;
