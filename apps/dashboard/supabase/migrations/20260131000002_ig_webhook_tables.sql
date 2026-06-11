-- Instagram Webhook Processing Tables
-- Tables used by ig-webhook-processor.ts to store processed webhook events
-- No RLS - server-side only access via service role

-- ============================================================================
-- 1. ig_comments - Stores comments from webhook events
-- ============================================================================

CREATE TABLE IF NOT EXISTS ig_comments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  comment_id TEXT NOT NULL UNIQUE,
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  media_id TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT 'unknown',
  ig_user_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ig_comments_post_id
  ON ig_comments(post_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ig_comments_media_id
  ON ig_comments(media_id);

-- No RLS - accessed only by service role in cron jobs
ALTER TABLE ig_comments DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- 2. ig_mentions - Stores mention events from webhooks
-- ============================================================================

CREATE TABLE IF NOT EXISTS ig_mentions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  media_id TEXT NOT NULL UNIQUE,
  ig_account_id TEXT NOT NULL,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  ig_user_id TEXT NOT NULL,
  username TEXT NOT NULL DEFAULT 'unknown',
  caption TEXT DEFAULT '',
  permalink TEXT,
  media_type TEXT,
  mentioned_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ig_mentions_user_id
  ON ig_mentions(user_id, mentioned_at DESC);

CREATE INDEX IF NOT EXISTS idx_ig_mentions_ig_account
  ON ig_mentions(ig_account_id, mentioned_at DESC);

-- No RLS - accessed only by service role in cron jobs
ALTER TABLE ig_mentions DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- 3. ig_story_insights - Stores story metrics from webhooks
-- ============================================================================

CREATE TABLE IF NOT EXISTS ig_story_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  media_id TEXT NOT NULL UNIQUE,
  ig_user_id TEXT NOT NULL,
  impressions INTEGER NOT NULL DEFAULT 0,
  reach INTEGER NOT NULL DEFAULT 0,
  replies INTEGER NOT NULL DEFAULT 0,
  taps_forward INTEGER NOT NULL DEFAULT 0,
  taps_back INTEGER NOT NULL DEFAULT 0,
  exits INTEGER NOT NULL DEFAULT 0,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ig_story_insights_user
  ON ig_story_insights(ig_user_id, recorded_at DESC);

-- No RLS - accessed only by service role in cron jobs
ALTER TABLE ig_story_insights DISABLE ROW LEVEL SECURITY;

-- ============================================================================
-- 4. Add ig_comment_count column to posts table
-- ============================================================================

ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_comment_count INTEGER DEFAULT 0;

-- ============================================================================
-- 5. Add retry_count column to ig_webhook_events table
-- ============================================================================

ALTER TABLE ig_webhook_events ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;

-- ============================================================================
-- Grant service_role access
-- ============================================================================

GRANT ALL ON ig_comments TO service_role;
GRANT ALL ON ig_mentions TO service_role;
GRANT ALL ON ig_story_insights TO service_role;
