-- Add ai_provider column to auto_post_config for workspace-level AI provider override.
-- Allows switching between 'gemini' (default) and 'xai' (Grok) via MCP.
-- NULL = use user-level ai_config provider (backwards compatible).

ALTER TABLE auto_post_config
ADD COLUMN IF NOT EXISTS ai_provider TEXT DEFAULT NULL;

COMMENT ON COLUMN auto_post_config.ai_provider IS 'AI provider override: gemini | xai | openai | anthropic. NULL = use user ai_config.';
