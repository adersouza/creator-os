-- Migration: Add Voice Profile / AI Config per Account
-- Allows per-account AI customization for different personas (e.g., different models)

-- Add ai_config JSONB column to accounts table
ALTER TABLE public.accounts
ADD COLUMN IF NOT EXISTS ai_config JSONB DEFAULT '{}'::jsonb;

-- Example ai_config structure:
-- {
--   "voice_profile": "Write as a flirty, playful 20-something. Use emojis, slang like 'omg' and 'lol'. Tease about exclusive content.",
--   "focus_topics": ["flirty teases", "trend hooks", "daily life", "sports reactions"],
--   "avoid_topics": ["politics", "religion", "controversial opinions"],
--   "avoid_words": ["family", "kids", "wholesome"],
--   "example_post_ids": ["post-id-1", "post-id-2"],
--   "emoji_usage": "heavy",
--   "hashtag_style": "minimal",
--   "cta_style": "link_in_bio"
-- }

-- Add index for efficient JSONB queries
CREATE INDEX IF NOT EXISTS idx_accounts_ai_config ON public.accounts USING gin (ai_config);

-- Comment explaining the feature
COMMENT ON COLUMN public.accounts.ai_config IS 'Per-account AI configuration: voice profile, topics, avoidances for personalized content generation';
