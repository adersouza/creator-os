-- Core schema baseline for Supabase branch replay.
--
-- Production already contains these legacy tables, but fresh Supabase preview
-- branches rebuild from migration history only. This idempotent baseline
-- recreates the tables that older migrations assumed were already present.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS public.profiles (
  id TEXT PRIMARY KEY,
  email TEXT,
  display_name TEXT,
  avatar_url TEXT,
  subscription_tier TEXT DEFAULT 'free',
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  has_used_trial BOOLEAN DEFAULT FALSE,
  trial_started_at TIMESTAMPTZ,
  trial_ends_at TIMESTAMPTZ,
  billing_interval TEXT DEFAULT 'monthly',
  timezone TEXT DEFAULT 'America/New_York',
  power_user_score INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.workspaces (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  name TEXT NOT NULL,
  owner_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  tier TEXT DEFAULT 'pro',
  settings JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.account_groups (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT,
  category TEXT DEFAULT 'uncategorized',
  voice_profile JSONB,
  account_ids TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.accounts (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  workspace_id TEXT REFERENCES public.workspaces(id) ON DELETE SET NULL,
  group_id TEXT REFERENCES public.account_groups(id) ON DELETE SET NULL,
  threads_user_id TEXT,
  username TEXT,
  handle TEXT,
  display_name TEXT,
  avatar_url TEXT,
  bio TEXT,
  follower_count INTEGER DEFAULT 0,
  following_count INTEGER DEFAULT 0,
  is_verified BOOLEAN DEFAULT FALSE,
  threads_access_token_encrypted TEXT,
  refresh_token_encrypted TEXT,
  token_expires_at TIMESTAMPTZ,
  is_active BOOLEAN DEFAULT TRUE,
  last_synced_at TIMESTAMPTZ,
  ai_config JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.posts (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id) ON DELETE SET NULL,
  threads_post_id TEXT,
  instagram_post_id TEXT,
  instagram_account_id UUID,
  platform TEXT DEFAULT 'threads',
  content TEXT NOT NULL DEFAULT '',
  media_urls TEXT[],
  media_type TEXT,
  status TEXT DEFAULT 'draft',
  scheduled_for TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  permalink TEXT,
  views INTEGER DEFAULT 0,
  likes INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0,
  reposts INTEGER DEFAULT 0,
  quotes INTEGER DEFAULT 0,
  shares INTEGER DEFAULT 0,
  saves INTEGER DEFAULT 0,
  reach INTEGER DEFAULT 0,
  impressions INTEGER DEFAULT 0,
  engagement_rate DECIMAL(8,4) DEFAULT 0,
  reply_rate DECIMAL(8,4) DEFAULT 0,
  virality_score DECIMAL(8,4) DEFAULT 0,
  content_category TEXT,
  retry_count INTEGER DEFAULT 0,
  hashtags TEXT[],
  source TEXT DEFAULT 'manual',
  source_competitor_id TEXT,
  error_message TEXT,
  approved_by TEXT REFERENCES public.profiles(id),
  rejected_by TEXT REFERENCES public.profiles(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.post_replies (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  post_id TEXT NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
  threads_reply_id TEXT,
  username TEXT NOT NULL DEFAULT '',
  display_name TEXT,
  avatar_url TEXT,
  content TEXT,
  likes INTEGER DEFAULT 0,
  replied_at TIMESTAMPTZ,
  is_read BOOLEAN DEFAULT FALSE,
  response_time_minutes INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.sent_replies (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id) ON DELETE SET NULL,
  account_handle TEXT,
  avatar_url TEXT,
  threads_reply_id TEXT,
  reply_to_post_id TEXT NOT NULL DEFAULT '',
  reply_to_username TEXT,
  content TEXT NOT NULL DEFAULT '',
  likes INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0,
  reposts INTEGER DEFAULT 0,
  sent_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.competitors (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  threads_user_id TEXT,
  threads_numeric_id TEXT,
  username TEXT NOT NULL DEFAULT '',
  display_name TEXT,
  avatar_url TEXT,
  bio TEXT,
  follower_count INTEGER DEFAULT 0,
  is_verified BOOLEAN DEFAULT FALSE,
  platform TEXT DEFAULT 'threads',
  likes_count_7d INTEGER DEFAULT 0,
  replies_count_7d INTEGER DEFAULT 0,
  reposts_count_7d INTEGER DEFAULT 0,
  quotes_count_7d INTEGER DEFAULT 0,
  views_count_7d INTEGER DEFAULT 0,
  last_synced_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.competitor_snapshots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  competitor_id TEXT NOT NULL REFERENCES public.competitors(id) ON DELETE CASCADE,
  snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
  follower_count INTEGER,
  likes_count_7d INTEGER,
  replies_count_7d INTEGER,
  reposts_count_7d INTEGER,
  views_count_7d INTEGER,
  engagement_rate NUMERIC,
  avg_likes NUMERIC,
  avg_comments NUMERIC,
  media_count INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.competitor_posts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  competitor_id TEXT NOT NULL REFERENCES public.competitors(id) ON DELETE CASCADE,
  threads_post_id TEXT,
  content TEXT,
  media_urls TEXT[],
  media_type TEXT,
  permalink TEXT,
  likes INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0,
  reposts INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0,
  posted_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.media_folders (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  parent_id UUID REFERENCES public.media_folders(id) ON DELETE CASCADE,
  cover_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.media (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  folder_id UUID REFERENCES public.media_folders(id) ON DELETE SET NULL,
  group_id TEXT REFERENCES public.account_groups(id) ON DELETE SET NULL,
  file_name TEXT NOT NULL DEFAULT '',
  url TEXT,
  storage_url TEXT,
  storage_path TEXT,
  file_type TEXT,
  mime_type TEXT,
  size TEXT,
  file_size INTEGER,
  width INTEGER,
  height INTEGER,
  duration INTEGER,
  thumbnail_url TEXT,
  tags TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.favorites (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  threads_post_id TEXT,
  content TEXT,
  username TEXT,
  avatar_url TEXT,
  media_urls TEXT[],
  notes TEXT,
  tags TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.queue_slots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  day_of_week INTEGER,
  time_of_day TIME,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.user_settings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  setting_key TEXT NOT NULL,
  setting_value JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.account_analytics (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id TEXT NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
  date DATE NOT NULL DEFAULT CURRENT_DATE,
  followers_count INTEGER,
  following_count INTEGER,
  follower_growth INTEGER DEFAULT 0,
  total_views INTEGER,
  total_likes INTEGER,
  total_replies INTEGER,
  total_reposts INTEGER,
  posts_count INTEGER,
  engagement_rate DECIMAL(8,4),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.workspace_members (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'member',
  invited_by TEXT REFERENCES public.profiles(id),
  joined_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.workspace_invites (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  role TEXT DEFAULT 'member',
  invited_by TEXT REFERENCES public.profiles(id),
  expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.auto_post_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  enabled BOOLEAN DEFAULT FALSE,
  posts_per_day INTEGER DEFAULT 8,
  min_interval_minutes INTEGER DEFAULT 20,
  max_interval_minutes INTEGER DEFAULT 45,
  media_attachment_chance INTEGER DEFAULT 50,
  media_source TEXT DEFAULT 'global',
  active_hours_start INTEGER DEFAULT 8,
  active_hours_end INTEGER DEFAULT 22,
  enable_weekends BOOLEAN DEFAULT TRUE,
  round_robin_enabled BOOLEAN DEFAULT TRUE,
  selected_groups TEXT[],
  platform TEXT DEFAULT 'threads',
  pause_on_low_performance BOOLEAN DEFAULT FALSE,
  performance_threshold DECIMAL(5,2) DEFAULT 2.0,
  performance_check_window INTEGER DEFAULT 10,
  smart_timing_enabled BOOLEAN DEFAULT FALSE,
  require_approval BOOLEAN DEFAULT FALSE,
  enable_competitor_adaptation BOOLEAN DEFAULT FALSE,
  competitor_adapt_ratio INTEGER DEFAULT 20,
  daily_limit INTEGER DEFAULT 10,
  content_sources JSONB DEFAULT '{"queue": true, "aiGenerated": false, "competitorAdapted": false}',
  ai_style_guidelines TEXT,
  group_mode_enabled BOOLEAN NOT NULL DEFAULT false,
  last_post_at TIMESTAMPTZ,
  paused_at TIMESTAMPTZ,
  pause_reason TEXT,
  last_updated TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.auto_post_queue (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id) ON DELETE SET NULL,
  post_id TEXT,
  content TEXT NOT NULL DEFAULT '',
  group_id TEXT REFERENCES public.account_groups(id) ON DELETE SET NULL,
  media_urls TEXT[],
  source TEXT DEFAULT 'queue',
  source_content TEXT,
  source_media_type TEXT,
  priority INTEGER DEFAULT 0,
  times_used INTEGER DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  added_at TIMESTAMPTZ DEFAULT NOW(),
  status TEXT DEFAULT 'pending',
  platform TEXT NOT NULL DEFAULT 'threads',
  scheduled_for TIMESTAMPTZ,
  posted_at TIMESTAMPTZ,
  error_message TEXT,
  retry_count INTEGER DEFAULT 0,
  next_retry_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.auto_post_activity (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id),
  group_id TEXT REFERENCES public.account_groups(id) ON DELETE SET NULL,
  group_name TEXT,
  action TEXT NOT NULL,
  details JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.auto_post_state (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  last_post_at TIMESTAMPTZ,
  last_cron_run_at TIMESTAMPTZ,
  posts_today INTEGER DEFAULT 0,
  posts_this_hour INTEGER DEFAULT 0,
  consecutive_failures INTEGER DEFAULT 0,
  is_paused BOOLEAN DEFAULT FALSE,
  pause_reason TEXT,
  paused_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.auto_post_group_state (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  group_id TEXT NOT NULL REFERENCES public.account_groups(id) ON DELETE CASCADE,
  current_account_index INTEGER NOT NULL DEFAULT 0,
  current_queue_index INTEGER NOT NULL DEFAULT 0,
  posts_today INTEGER NOT NULL DEFAULT 0,
  last_post_at TIMESTAMPTZ,
  last_cron_run_at TIMESTAMPTZ,
  last_reset_date DATE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.auto_reply_rules (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id) ON DELETE CASCADE,
  trigger_type TEXT NOT NULL,
  trigger_pattern TEXT NOT NULL,
  reply_text TEXT NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.listening_alerts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  keyword TEXT NOT NULL,
  alert_type TEXT NOT NULL,
  threshold_value INTEGER DEFAULT 10,
  is_active BOOLEAN DEFAULT TRUE,
  last_triggered_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.creator_links (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  label TEXT NOT NULL,
  click_count INTEGER DEFAULT 0,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.mentions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id) ON DELETE SET NULL,
  threads_post_id TEXT,
  mentioned_by_username TEXT,
  mentioned_by_avatar TEXT,
  content TEXT,
  media_urls TEXT[],
  likes INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0,
  permalink TEXT,
  mentioned_at TIMESTAMPTZ,
  is_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.saved_competitor_posts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  competitor_post_id UUID REFERENCES public.competitor_posts(id),
  threads_post_id TEXT,
  content TEXT,
  username TEXT,
  avatar_url TEXT,
  media_urls TEXT[],
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.ai_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  provider TEXT DEFAULT 'gemini',
  api_key TEXT,
  base_url TEXT,
  model TEXT,
  last_validated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.user_preferences (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  onboarding_completed BOOLEAN DEFAULT FALSE,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.workspace_activity (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES public.profiles(id),
  action_type TEXT NOT NULL DEFAULT 'event',
  action_details JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.trial_emails (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email_hash TEXT NOT NULL,
  used_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION public.is_workspace_member(p_workspace_id TEXT, p_user_id TEXT)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.workspace_members
    WHERE workspace_id = p_workspace_id
      AND user_id = p_user_id
  );
$$;

CREATE OR REPLACE FUNCTION public.is_workspace_owner(p_workspace_id TEXT, p_user_id TEXT)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.workspaces
    WHERE id = p_workspace_id
      AND owner_id = p_user_id
  );
$$;

CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON public.accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_workspace_id ON public.accounts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_posts_user_id ON public.posts(user_id);
CREATE INDEX IF NOT EXISTS idx_posts_account_id ON public.posts(account_id);
CREATE INDEX IF NOT EXISTS idx_posts_status ON public.posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_scheduled_for ON public.posts(scheduled_for);
CREATE INDEX IF NOT EXISTS idx_sent_replies_user_id ON public.sent_replies(user_id);
CREATE INDEX IF NOT EXISTS idx_mentions_account_id ON public.mentions(account_id);
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_workspace_id ON public.auto_post_queue(workspace_id);
CREATE INDEX IF NOT EXISTS idx_auto_post_queue_status ON public.auto_post_queue(status);
CREATE INDEX IF NOT EXISTS idx_account_analytics_account_id ON public.account_analytics(account_id);
CREATE INDEX IF NOT EXISTS idx_workspaces_owner_id ON public.workspaces(owner_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_workspace_id ON public.workspace_members(workspace_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_user_id ON public.workspace_members(user_id);
