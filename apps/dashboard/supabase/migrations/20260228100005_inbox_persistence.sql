-- Inbox Persistence Migration
-- Adds is_read columns to ig_comments/ig_mentions and creates inbox_dm_cache table

-- ============================================================================
-- 1. Add is_read column to ig_comments
-- ============================================================================

ALTER TABLE ig_comments ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE;

-- ============================================================================
-- 2. Add is_read column to ig_mentions
-- ============================================================================

ALTER TABLE ig_mentions ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE;

-- ============================================================================
-- 3. Create inbox_dm_cache table for IG DM persistence
-- ============================================================================

CREATE TABLE IF NOT EXISTS inbox_dm_cache (
  id TEXT PRIMARY KEY,                  -- Conversation ID from IG API
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL,             -- IG account UUID as text
  participant_id TEXT,
  participant_username TEXT,
  last_message_text TEXT,
  last_message_at TIMESTAMPTZ,
  conversation_name TEXT,
  raw_data JSONB,                       -- Full conversation payload for offline access
  is_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inbox_dm_cache_user_id
  ON inbox_dm_cache(user_id, last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_inbox_dm_cache_account_id
  ON inbox_dm_cache(account_id);

-- RLS: users can only see their own DM cache
ALTER TABLE inbox_dm_cache ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE policyname = 'Users manage own DM cache' AND tablename = 'inbox_dm_cache'
  ) THEN
    CREATE POLICY "Users manage own DM cache"
      ON inbox_dm_cache FOR ALL TO public
      USING ((SELECT auth.uid())::text = user_id);
  END IF;
END $$;

-- Grant service role full access
GRANT ALL ON inbox_dm_cache TO service_role;
