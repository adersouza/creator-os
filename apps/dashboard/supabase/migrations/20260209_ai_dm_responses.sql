-- Extend auto_responders for AI mode
DO $$
BEGIN
  IF to_regclass('public.ig_auto_responders') IS NOT NULL THEN
    ALTER TABLE public.ig_auto_responders
      ADD COLUMN IF NOT EXISTS use_ai_response BOOLEAN DEFAULT false,
      ADD COLUMN IF NOT EXISTS ai_response_intent TEXT DEFAULT 'engage',
      ADD COLUMN IF NOT EXISTS ai_conversation_depth INT DEFAULT 5,
      ADD COLUMN IF NOT EXISTS ai_system_prompt TEXT;
  END IF;
END $$;

-- Track AI DM performance
CREATE TABLE IF NOT EXISTS ig_dm_ai_responses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  conversation_id TEXT NOT NULL,
  incoming_message TEXT NOT NULL,
  ai_response TEXT NOT NULL,
  response_intent TEXT NOT NULL,
  voice_profile_used BOOLEAN DEFAULT false,
  tokens_used INT,
  response_time_ms INT,
  user_replied_after BOOLEAN,
  converted_to_link BOOLEAN,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Rate limiting for AI DMs
CREATE TABLE IF NOT EXISTS ig_dm_ai_rate_limits (
  account_id UUID PRIMARY KEY REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  responses_this_hour INT DEFAULT 0,
  responses_today INT DEFAULT 0,
  hour_reset_at TIMESTAMPTZ DEFAULT NOW(),
  day_reset_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_dm_ai_responses_account ON ig_dm_ai_responses(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dm_ai_responses_conversion ON ig_dm_ai_responses(converted_to_link) WHERE converted_to_link = true;

-- RLS
ALTER TABLE ig_dm_ai_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE ig_dm_ai_rate_limits ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view AI DM responses for their accounts" ON ig_dm_ai_responses
  FOR ALL USING (
    EXISTS (SELECT 1 FROM instagram_accounts WHERE instagram_accounts.id = account_id AND instagram_accounts.user_id = auth.uid()::text)
  );

CREATE POLICY "Users can manage AI DM rate limits for their accounts" ON ig_dm_ai_rate_limits
  FOR ALL USING (
    EXISTS (SELECT 1 FROM instagram_accounts WHERE instagram_accounts.id = account_id AND instagram_accounts.user_id = auth.uid()::text)
  );
