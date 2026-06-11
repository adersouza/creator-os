-- Migration: Instagram Posts Support
-- Date: 2026-01-30
-- Purpose: Add Instagram platform support to the posts table, Facebook Login
--          fields to instagram_accounts, and IG rate limiting DB function.

-- ============================================================================
-- 1. Posts table: add platform + Instagram-specific columns
-- ============================================================================

-- Platform discriminator (defaults to 'threads' for all existing rows)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS platform TEXT DEFAULT 'threads'
  CHECK (platform IN ('threads', 'instagram'));

-- Instagram post ID (nullable - only set for published IG posts)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS instagram_post_id TEXT;

-- Reference to instagram_accounts (nullable)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS instagram_account_id UUID
  REFERENCES instagram_accounts(id) ON DELETE SET NULL;

-- Instagram media type
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_media_type TEXT
  CHECK (ig_media_type IS NULL OR ig_media_type IN ('IMAGE', 'VIDEO', 'REELS', 'CAROUSEL', 'STORIES'));

-- Alt text for Instagram images (accessibility)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS alt_text TEXT;

-- Instagram-specific metrics
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_impressions INTEGER DEFAULT 0;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_reach INTEGER DEFAULT 0;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_saved INTEGER DEFAULT 0;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ig_shares INTEGER DEFAULT 0;

-- Indexes for platform filtering and Instagram account lookups
CREATE INDEX IF NOT EXISTS idx_posts_platform ON posts(platform);
CREATE INDEX IF NOT EXISTS idx_posts_instagram_account_id ON posts(instagram_account_id);
CREATE INDEX IF NOT EXISTS idx_posts_instagram_post_id ON posts(instagram_post_id);

-- ============================================================================
-- 2. Instagram accounts: add Facebook Login / Stories columns
-- ============================================================================

ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS facebook_page_id TEXT;
ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS facebook_page_access_token_encrypted TEXT;
ALTER TABLE instagram_accounts ADD COLUMN IF NOT EXISTS login_type TEXT DEFAULT 'instagram'
  CHECK (login_type IN ('instagram', 'facebook'));

-- ============================================================================
-- 3. Instagram rate limit function (mirrors check_and_increment_rate_limit)
-- ============================================================================

CREATE OR REPLACE FUNCTION ig_check_and_increment_rate_limit(
  p_account_id UUID,
  p_daily_limit INTEGER DEFAULT 25
)
RETURNS TABLE (
  allowed BOOLEAN,
  reason TEXT,
  daily_count INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_record ig_rate_limit_tracking%ROWTYPE;
  v_now TIMESTAMPTZ := NOW();
BEGIN
  -- Get or create record with row-level lock
  INSERT INTO ig_rate_limit_tracking (account_id, daily_count, daily_reset_at)
  VALUES (p_account_id, 0, v_now + INTERVAL '24 hours')
  ON CONFLICT (account_id) DO UPDATE
  SET updated_at = v_now
  RETURNING * INTO v_record;

  -- Lock the row for update
  SELECT * INTO v_record
  FROM ig_rate_limit_tracking
  WHERE account_id = p_account_id
  FOR UPDATE;

  -- Reset daily counter if window expired
  IF v_record.daily_reset_at < v_now THEN
    v_record.daily_count := 0;
    v_record.daily_reset_at := v_now + INTERVAL '24 hours';
  END IF;

  -- Check limit
  IF v_record.daily_count >= p_daily_limit THEN
    RETURN QUERY SELECT
      FALSE,
      FORMAT('Daily IG limit reached (%s/%s)', v_record.daily_count, p_daily_limit),
      v_record.daily_count;
    RETURN;
  END IF;

  -- Increment counter
  UPDATE ig_rate_limit_tracking
  SET
    daily_count = v_record.daily_count + 1,
    daily_reset_at = v_record.daily_reset_at,
    updated_at = v_now
  WHERE account_id = p_account_id;

  -- Return success
  RETURN QUERY SELECT
    TRUE,
    NULL::TEXT,
    v_record.daily_count + 1;
END;
$$;

-- ============================================================================
-- 4. Permissions
-- ============================================================================

GRANT EXECUTE ON FUNCTION ig_check_and_increment_rate_limit TO service_role;
