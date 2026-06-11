-- Auto Self-Reply Chains — accounts reply to their own posts to boost algo signal
-- Populated by self-reply-worker cron (runs as Phase 4 inside publish-worker).
-- Self-replies are the #1 Threads algorithmic signal for reach amplification.

CREATE TABLE IF NOT EXISTS auto_self_replies (
  id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id text REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  workspace_id text NOT NULL DEFAULT '',
  group_id text,
  post_id text NOT NULL,
  account_id text NOT NULL,
  threads_post_id text,  -- Threads' media ID of the ORIGINAL post

  -- Reply content
  content text NOT NULL,
  reply_number integer NOT NULL DEFAULT 1,  -- 1 or 2 (max 2 self-replies per post)

  -- Status tracking
  status text NOT NULL DEFAULT 'pending',  -- pending | published | failed | skipped
  scheduled_for timestamptz NOT NULL,
  published_at timestamptz,
  threads_reply_id text,  -- Threads' media ID of the published reply
  error_message text,
  retry_count integer DEFAULT 0,

  -- Eligibility snapshot (why this post was chosen)
  views_at_check integer DEFAULT 0,
  replies_at_check integer DEFAULT 0,
  eligible_reason text,  -- 'organic_replies' | 'high_views' | 'forced'

  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),

  -- One reply_number per post
  UNIQUE(post_id, reply_number)
);

-- Cron worker: find pending replies ready to publish
CREATE INDEX IF NOT EXISTS idx_self_replies_pending
  ON auto_self_replies(status, scheduled_for)
  WHERE status = 'pending';

-- Dashboard: all self-replies for a user
CREATE INDEX IF NOT EXISTS idx_self_replies_user
  ON auto_self_replies(user_id, created_at DESC);

-- Analytics: track self-reply performance per group
CREATE INDEX IF NOT EXISTS idx_self_replies_group
  ON auto_self_replies(group_id, status, created_at DESC);

-- Dedup: check if a post already has self-replies scheduled
CREATE INDEX IF NOT EXISTS idx_self_replies_post
  ON auto_self_replies(post_id, status);

-- Enable RLS
ALTER TABLE auto_self_replies ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own self-replies"
  ON auto_self_replies FOR SELECT
  USING (auth.uid()::text = user_id);

CREATE POLICY "Service role can manage self-replies"
  ON auto_self_replies FOR ALL
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- Cross-Account Reply Chains — accounts in same group reply to each other
-- ============================================================================

CREATE TABLE IF NOT EXISTS auto_cross_replies (
  id text PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id text REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  workspace_id text NOT NULL DEFAULT '',
  group_id text NOT NULL,

  -- The post being replied to
  target_post_id text NOT NULL,
  target_account_id text NOT NULL,
  target_threads_post_id text,

  -- The account replying
  replier_account_id text NOT NULL,
  replier_threads_post_id text,  -- Threads' media ID of the published reply

  -- Reply content
  content text NOT NULL,
  chain_position integer NOT NULL DEFAULT 1,  -- 1 = first reply, 2 = reply to reply

  -- Status tracking
  status text NOT NULL DEFAULT 'pending',
  scheduled_for timestamptz NOT NULL,
  published_at timestamptz,
  error_message text,
  retry_count integer DEFAULT 0,

  -- Parent in chain (for reply-to-reply)
  parent_reply_id text REFERENCES auto_cross_replies(id),

  created_at timestamptz DEFAULT now(),

  -- Prevent duplicate cross-replies
  UNIQUE(target_post_id, replier_account_id, chain_position)
);

-- Cron worker: find pending cross-replies
CREATE INDEX IF NOT EXISTS idx_cross_replies_pending
  ON auto_cross_replies(status, scheduled_for)
  WHERE status = 'pending';

-- Dashboard queries
CREATE INDEX IF NOT EXISTS idx_cross_replies_user
  ON auto_cross_replies(user_id, created_at DESC);

-- Rate limiting: count recent cross-replies per group
CREATE INDEX IF NOT EXISTS idx_cross_replies_group_recent
  ON auto_cross_replies(group_id, created_at DESC)
  WHERE status = 'published';

-- Enable RLS
ALTER TABLE auto_cross_replies ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own cross-replies"
  ON auto_cross_replies FOR SELECT
  USING (auth.uid()::text = user_id);

CREATE POLICY "Service role can manage cross-replies"
  ON auto_cross_replies FOR ALL
  USING (true)
  WITH CHECK (true);
