-- ============================================================================
-- New feature tables (2026-02-18)
-- Tables referenced in code but missing CREATE TABLE migrations
-- ============================================================================

-- ── Inspiration Engine ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS inspiration_ideas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  workspace_id UUID,
  original_post JSONB,
  competitor_id UUID,
  competitor_username TEXT DEFAULT 'unknown',
  competitor_avatar_url TEXT,
  adapted_content TEXT DEFAULT '',
  viral_score INTEGER DEFAULT 0,
  ai_insight TEXT DEFAULT '',
  topic_tags TEXT[] DEFAULT '{}',
  adaptation_style TEXT DEFAULT 'casual',
  adaptation_angle TEXT,
  viral_formula TEXT,
  status TEXT DEFAULT 'pending',
  saved BOOLEAN DEFAULT FALSE,
  queued BOOLEAN DEFAULT FALSE,
  queued_at TIMESTAMPTZ,
  posted_at TIMESTAMPTZ,
  generated_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);




CREATE TABLE IF NOT EXISTS inspiration_config (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
  enabled BOOLEAN DEFAULT TRUE,
  ideas_per_competitor INTEGER DEFAULT 10,
  adaptation_style TEXT DEFAULT 'casual',
  topic_filters TEXT[] DEFAULT '{}',
  notify_new_ideas BOOLEAN DEFAULT TRUE,
  daily_digest_enabled BOOLEAN DEFAULT FALSE,
  last_scan_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);



-- ── Trend Tracking ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS trend_keywords (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  workspace_id UUID,
  keyword TEXT NOT NULL,
  category TEXT DEFAULT 'general',
  is_active BOOLEAN DEFAULT TRUE,
  volume INTEGER DEFAULT 0,
  change NUMERIC DEFAULT 0,
  mention_count INTEGER DEFAULT 0,
  last_seen TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);




CREATE TABLE IF NOT EXISTS trend_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  keyword_id UUID NOT NULL REFERENCES trend_keywords(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  threads_post_id TEXT,
  content TEXT,
  username TEXT,
  like_count INTEGER DEFAULT 0,
  reply_count INTEGER DEFAULT 0,
  repost_count INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0,
  media_url TEXT,
  media_type TEXT,
  permalink TEXT,
  posted_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);




CREATE TABLE IF NOT EXISTS trend_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  keyword_id UUID NOT NULL REFERENCES trend_keywords(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  post_count INTEGER DEFAULT 0,
  total_engagement INTEGER DEFAULT 0,
  avg_engagement NUMERIC DEFAULT 0,
  top_hashtags JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT NOW()
);




-- ── Saved Searches (Discover) ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS saved_searches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  workspace_id UUID,
  name TEXT NOT NULL,
  query TEXT NOT NULL,
  search_mode TEXT DEFAULT 'KEYWORD',
  search_type TEXT DEFAULT 'RECENT',
  media_type TEXT,
  last_run_at TIMESTAMPTZ,
  total_results INTEGER DEFAULT 0,
  avg_engagement NUMERIC DEFAULT 0,
  is_pinned BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);




CREATE TABLE IF NOT EXISTS saved_search_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  search_id UUID NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  result_count INTEGER DEFAULT 0,
  total_engagement INTEGER DEFAULT 0,
  avg_engagement NUMERIC DEFAULT 0,
  top_posts JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT NOW()
);




-- ── IG DM Templates ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ig_dm_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  workspace_id UUID,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  category TEXT DEFAULT 'general',
  shortcut TEXT,
  use_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);




-- ── IG Auto-Responders ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ig_auto_responders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  instagram_account_id TEXT NOT NULL,
  name TEXT NOT NULL,
  trigger_type TEXT NOT NULL DEFAULT 'keyword',
  trigger_value TEXT,
  response_template TEXT NOT NULL,
  use_ai_response BOOLEAN DEFAULT false,
  ai_response_intent TEXT DEFAULT 'engage',
  ai_conversation_depth INT DEFAULT 5,
  ai_system_prompt TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  match_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);




-- ── Saved Competitor Posts ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS saved_competitor_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  competitor_id UUID,
  post_id TEXT NOT NULL,
  content TEXT,
  engagement_score INTEGER DEFAULT 0,
  saved_at TIMESTAMPTZ DEFAULT NOW()
);




-- ── Account Analytics ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS account_analytics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  followers INTEGER DEFAULT 0,
  following INTEGER DEFAULT 0,
  posts_count INTEGER DEFAULT 0,
  total_likes INTEGER DEFAULT 0,
  total_replies INTEGER DEFAULT 0,
  total_reposts INTEGER DEFAULT 0,
  total_views INTEGER DEFAULT 0,
  engagement_rate NUMERIC DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);




-- ── Competitor Top Posts ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS competitor_top_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  competitor_id UUID NOT NULL,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  threads_post_id TEXT,
  content TEXT,
  like_count INTEGER DEFAULT 0,
  reply_count INTEGER DEFAULT 0,
  repost_count INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0,
  media_url TEXT,
  media_type TEXT,
  permalink TEXT,
  engagement_score INTEGER DEFAULT 0,
  posted_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);




-- ── Competitor Snapshots ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS competitor_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  competitor_id UUID NOT NULL,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  followers INTEGER DEFAULT 0,
  post_count INTEGER DEFAULT 0,
  avg_engagement NUMERIC DEFAULT 0,
  top_post_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);




-- ── Account Groups ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS account_groups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  workspace_id UUID,
  name TEXT NOT NULL,
  description TEXT,
  account_ids TEXT[] DEFAULT '{}',
  color TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

