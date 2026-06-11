-- ThreadsDashboard Supabase Schema
-- IMPORTANT: This file reflects PRODUCTION column types.
-- Core table IDs (profiles, accounts, posts, workspaces, account_groups) are TEXT.
-- All user_id foreign keys are TEXT REFERENCES profiles(id) ON DELETE CASCADE.
-- RLS policies use auth.uid()::text for TEXT-typed user_id columns.
-- instagram_accounts.id is UUID (exception).

-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- USERS & PROFILES
-- ============================================
-- Supabase Auth handles auth.users automatically
-- This profiles table extends it with app-specific data
-- NOTE: profiles.id is TEXT in production (not UUID)

CREATE TABLE public.profiles (
  id TEXT PRIMARY KEY, -- matches auth.users.id cast to text
  email TEXT,
  display_name TEXT,
  avatar_url TEXT,
  subscription_tier TEXT DEFAULT 'free' CHECK (subscription_tier IN ('free', 'pro', 'empire')),
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

-- ============================================
-- THREADS ACCOUNTS
-- ============================================
CREATE TABLE public.accounts (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  workspace_id TEXT, -- nullable, set if belongs to workspace
  group_id TEXT, -- denormalized reference to account_groups.id
  threads_user_id TEXT NOT NULL,
  username TEXT NOT NULL,
  handle TEXT,
  display_name TEXT,
  avatar_url TEXT,
  bio TEXT,
  follower_count INTEGER DEFAULT 0,
  following_count INTEGER DEFAULT 0,
  is_verified BOOLEAN DEFAULT FALSE,
  threads_access_token_encrypted TEXT, -- encrypted token
  refresh_token_encrypted TEXT,
  token_expires_at TIMESTAMPTZ,
  is_active BOOLEAN DEFAULT TRUE,
  last_synced_at TIMESTAMPTZ,
  ai_config JSONB, -- voice profile, style, warmup settings
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(threads_user_id)
);

CREATE INDEX idx_accounts_user_id ON public.accounts(user_id);
CREATE INDEX idx_accounts_workspace_id ON public.accounts(workspace_id);

-- ============================================
-- INSTAGRAM ACCOUNTS
-- ============================================
-- NOTE: instagram_accounts.id is UUID (exception to TEXT convention)
CREATE TABLE public.instagram_accounts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  instagram_user_id TEXT NOT NULL,
  username TEXT NOT NULL,
  display_name TEXT,
  avatar_url TEXT,
  bio TEXT,
  follower_count INTEGER DEFAULT 0,
  following_count INTEGER DEFAULT 0,
  media_count INTEGER DEFAULT 0,
  is_business BOOLEAN DEFAULT FALSE,
  is_verified BOOLEAN DEFAULT FALSE,
  instagram_access_token_encrypted TEXT,
  token_expires_at TIMESTAMPTZ,
  facebook_page_id TEXT,
  facebook_page_name TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  last_synced_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(instagram_user_id)
);

CREATE INDEX idx_instagram_accounts_user_id ON public.instagram_accounts(user_id);

-- ============================================
-- POSTS
-- ============================================
CREATE TABLE public.posts (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id) ON DELETE SET NULL,
  threads_post_id TEXT, -- ID from Threads API after publishing
  instagram_post_id TEXT, -- ID from Instagram API after publishing
  platform TEXT DEFAULT 'threads' CHECK (platform IN ('threads', 'instagram')),
  content TEXT NOT NULL,
  media_urls TEXT[], -- array of media URLs
  media_type TEXT CHECK (media_type IN ('text', 'image', 'video', 'carousel')),
  media_audio_type TEXT CHECK (media_audio_type IS NULL OR media_audio_type IN ('MUSIC', 'ORIGINAL_SOUND')),
  status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'scheduled', 'publishing', 'published', 'failed')),
  scheduled_for TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  permalink TEXT,
  -- Performance metrics
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
  -- Threads-specific depth metrics
  reply_rate DECIMAL(8,4) DEFAULT 0,
  virality_score DECIMAL(8,4) DEFAULT 0,
  content_category TEXT,
  -- Retry / error tracking
  retry_count INTEGER DEFAULT 0,
  -- Metadata
  hashtags TEXT[],
  source TEXT DEFAULT 'manual' CHECK (source IN ('manual', 'scheduled', 'auto-poster', 'ai-generated')),
  source_competitor_id TEXT,
  error_message TEXT,
  approved_by TEXT REFERENCES public.profiles(id),
  rejected_by TEXT REFERENCES public.profiles(id),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_posts_user_id ON public.posts(user_id);
CREATE INDEX idx_posts_account_id ON public.posts(account_id);
CREATE INDEX idx_posts_status ON public.posts(status);
CREATE INDEX idx_posts_scheduled_for ON public.posts(scheduled_for);
CREATE INDEX idx_posts_published_at ON public.posts(published_at);
CREATE INDEX idx_posts_platform ON public.posts(platform);

-- ============================================
-- POST REPLIES (received from others)
-- ============================================
CREATE TABLE public.post_replies (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  post_id TEXT NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
  threads_reply_id TEXT NOT NULL,
  username TEXT NOT NULL,
  display_name TEXT,
  avatar_url TEXT,
  content TEXT,
  likes INTEGER DEFAULT 0,
  replied_at TIMESTAMPTZ,
  is_read BOOLEAN DEFAULT FALSE,
  response_time_minutes INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(threads_reply_id)
);

CREATE INDEX idx_post_replies_post_id ON public.post_replies(post_id);

-- ============================================
-- SENT REPLIES (replies user sent)
-- ============================================
CREATE TABLE public.sent_replies (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id) ON DELETE SET NULL,
  account_handle TEXT,
  threads_reply_id TEXT,
  reply_to_post_id TEXT NOT NULL,
  reply_to_username TEXT,
  content TEXT NOT NULL,
  likes INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0,
  reposts INTEGER DEFAULT 0,
  sent_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sent_replies_user_id ON public.sent_replies(user_id);

-- ============================================
-- COMPETITORS
-- ============================================
CREATE TABLE public.competitors (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  threads_user_id TEXT NOT NULL,
  threads_numeric_id TEXT,
  username TEXT NOT NULL,
  display_name TEXT,
  avatar_url TEXT,
  bio TEXT,
  follower_count INTEGER DEFAULT 0,
  is_verified BOOLEAN DEFAULT FALSE,
  platform TEXT DEFAULT 'threads',
  -- 7-day engagement metrics
  likes_count_7d INTEGER DEFAULT 0,
  replies_count_7d INTEGER DEFAULT 0,
  reposts_count_7d INTEGER DEFAULT 0,
  quotes_count_7d INTEGER DEFAULT 0,
  views_count_7d INTEGER DEFAULT 0,
  last_synced_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, threads_user_id)
);

CREATE INDEX idx_competitors_user_id ON public.competitors(user_id);

-- ============================================
-- COMPETITOR SNAPSHOTS (historical data)
-- ============================================
CREATE TABLE public.competitor_snapshots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  competitor_id TEXT NOT NULL REFERENCES public.competitors(id) ON DELETE CASCADE,
  snapshot_date DATE NOT NULL,
  follower_count INTEGER,
  likes_count_7d INTEGER,
  replies_count_7d INTEGER,
  reposts_count_7d INTEGER,
  views_count_7d INTEGER,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(competitor_id, snapshot_date)
);

CREATE INDEX idx_competitor_snapshots_competitor_id ON public.competitor_snapshots(competitor_id);

-- ============================================
-- COMPETITOR POSTS
-- ============================================
CREATE TABLE public.competitor_posts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  competitor_id TEXT NOT NULL REFERENCES public.competitors(id) ON DELETE CASCADE,
  threads_post_id TEXT NOT NULL,
  content TEXT,
  media_urls TEXT[],
  media_type TEXT,
  permalink TEXT,
  likes INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0,
  reposts INTEGER DEFAULT 0,
  views INTEGER DEFAULT 0,
  posted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(threads_post_id)
);

CREATE INDEX idx_competitor_posts_competitor_id ON public.competitor_posts(competitor_id);

-- ============================================
-- COMPETITOR TOP POSTS (high-engagement posts for adaptation)
-- ============================================
CREATE TABLE public.competitor_top_posts (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  competitor_id TEXT NOT NULL REFERENCES public.competitors(id) ON DELETE CASCADE,
  threads_post_id TEXT NOT NULL UNIQUE,
  content TEXT,
  media_url TEXT,
  media_type TEXT,
  permalink TEXT,
  like_count INTEGER DEFAULT 0,
  reply_count INTEGER DEFAULT 0,
  repost_count INTEGER DEFAULT 0,
  view_count INTEGER DEFAULT 0,
  engagement_score DECIMAL(10, 2) DEFAULT 0,
  published_at TIMESTAMPTZ,
  competitor_username TEXT,
  competitor_avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_competitor_top_posts_competitor_id ON public.competitor_top_posts(competitor_id);
CREATE INDEX idx_competitor_top_posts_engagement ON public.competitor_top_posts(engagement_score DESC);

-- ============================================
-- MEDIA LIBRARY
-- ============================================
CREATE TABLE public.media_folders (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  parent_id UUID REFERENCES public.media_folders(id) ON DELETE CASCADE,
  cover_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE public.media (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  folder_id UUID REFERENCES public.media_folders(id) ON DELETE SET NULL,
  group_id TEXT REFERENCES public.account_groups(id) ON DELETE SET NULL,
  file_name TEXT NOT NULL,
  url TEXT,
  storage_url TEXT NOT NULL,
  storage_path TEXT,
  file_type TEXT NOT NULL, -- 'image', 'video'
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

CREATE INDEX idx_media_user_id ON public.media(user_id);
CREATE INDEX idx_media_folder_id ON public.media(folder_id);
CREATE INDEX idx_media_group_id ON public.media(group_id);

-- ============================================
-- FAVORITES / INSPIRATION
-- ============================================
CREATE TABLE public.favorites (
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

CREATE INDEX idx_favorites_user_id ON public.favorites(user_id);

-- ============================================
-- ACCOUNT GROUPS
-- ============================================
CREATE TABLE public.account_groups (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT,
  category TEXT DEFAULT 'uncategorized',
  voice_profile JSONB, -- group-level voice profile
  account_ids TEXT[], -- array of account IDs in this group
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_account_groups_user_id ON public.account_groups(user_id);

-- ============================================
-- QUEUE SLOTS (posting schedule)
-- ============================================
CREATE TABLE public.queue_slots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
  time_of_day TIME NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_queue_slots_user_id ON public.queue_slots(user_id);

-- ============================================
-- NOTIFICATIONS
-- ============================================
CREATE TABLE public.notifications (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  data JSONB,
  is_read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notifications_user_id ON public.notifications(user_id);
CREATE INDEX idx_notifications_is_read ON public.notifications(is_read);

-- ============================================
-- USER SETTINGS
-- ============================================
CREATE TABLE public.user_settings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  setting_key TEXT NOT NULL,
  setting_value JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id, setting_key)
);

CREATE INDEX idx_user_settings_user_id ON public.user_settings(user_id);

-- ============================================
-- ANALYTICS (daily snapshots)
-- ============================================
CREATE TABLE public.account_analytics (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id TEXT NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  followers_count INTEGER,
  following_count INTEGER,
  follower_growth INTEGER DEFAULT 0,
  total_views INTEGER,
  total_likes INTEGER,
  total_replies INTEGER,
  total_reposts INTEGER,
  posts_count INTEGER,
  engagement_rate DECIMAL(8,4),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(account_id, date)
);

CREATE INDEX idx_account_analytics_account_id ON public.account_analytics(account_id);
CREATE INDEX idx_account_analytics_date ON public.account_analytics(date);

-- ============================================
-- WORKSPACES (teams)
-- ============================================
CREATE TABLE public.workspaces (
  id TEXT PRIMARY KEY DEFAULT uuid_generate_v4()::text,
  name TEXT NOT NULL,
  owner_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  tier TEXT DEFAULT 'pro' CHECK (tier IN ('pro', 'empire')),
  settings JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_workspaces_owner_id ON public.workspaces(owner_id);

-- ============================================
-- WORKSPACE MEMBERS
-- ============================================
CREATE TABLE public.workspace_members (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  invited_by TEXT REFERENCES public.profiles(id),
  joined_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(workspace_id, user_id)
);

CREATE INDEX idx_workspace_members_workspace_id ON public.workspace_members(workspace_id);
CREATE INDEX idx_workspace_members_user_id ON public.workspace_members(user_id);

-- ============================================
-- WORKSPACE INVITES
-- ============================================
CREATE TABLE public.workspace_invites (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  role TEXT DEFAULT 'member',
  invited_by TEXT REFERENCES public.profiles(id),
  expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- AUTO-POSTER CONFIG
-- ============================================
CREATE TABLE public.auto_post_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  enabled BOOLEAN DEFAULT FALSE,
  posts_per_day INTEGER DEFAULT 8,
  min_interval_minutes INTEGER DEFAULT 20,
  max_interval_minutes INTEGER DEFAULT 45,
  media_attachment_chance INTEGER DEFAULT 50,
  media_source TEXT DEFAULT 'global' CHECK (media_source IN ('global', 'group-specific', 'mixed')),
  active_hours_start INTEGER DEFAULT 8,
  active_hours_end INTEGER DEFAULT 22,
  enable_weekends BOOLEAN DEFAULT TRUE,
  round_robin_enabled BOOLEAN DEFAULT TRUE,
  selected_groups TEXT[],
  platform TEXT DEFAULT 'threads',
  -- Smart Performance Controls
  pause_on_low_performance BOOLEAN DEFAULT FALSE,
  performance_threshold DECIMAL(5,2) DEFAULT 2.0,
  performance_check_window INTEGER DEFAULT 10,
  -- Smart Timing
  smart_timing_enabled BOOLEAN DEFAULT FALSE,
  -- Approval
  require_approval BOOLEAN DEFAULT FALSE,
  -- Competitor Adaptation
  enable_competitor_adaptation BOOLEAN DEFAULT FALSE,
  competitor_adapt_ratio INTEGER DEFAULT 20,
  -- Legacy/compatibility fields
  daily_limit INTEGER DEFAULT 10,
  content_sources JSONB DEFAULT '{"queue": true, "aiGenerated": false, "competitorAdapted": false}',
  last_post_at TIMESTAMPTZ,
  paused_at TIMESTAMPTZ,
  pause_reason TEXT,
  last_updated TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(workspace_id)
);

-- ============================================
-- AUTO-POSTER QUEUE
-- ============================================
CREATE TABLE public.auto_post_queue (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  account_id TEXT, -- nullable, assigned at post time
  post_id TEXT,
  content TEXT NOT NULL,
  group_id TEXT,
  media_urls TEXT[],
  source TEXT DEFAULT 'queue',
  source_content TEXT,
  priority INTEGER DEFAULT 0,
  times_used INTEGER DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  added_at TIMESTAMPTZ DEFAULT NOW(),
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'posted', 'failed', 'dead_letter')),
  scheduled_for TIMESTAMPTZ,
  posted_at TIMESTAMPTZ,
  error_message TEXT,
  retry_count INTEGER DEFAULT 0,
  next_retry_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_auto_post_queue_workspace_id ON public.auto_post_queue(workspace_id);
CREATE INDEX idx_auto_post_queue_status ON public.auto_post_queue(status);

-- ============================================
-- AUTO-POSTER ACTIVITY LOG
-- ============================================
CREATE TABLE public.auto_post_activity (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id),
  action TEXT NOT NULL,
  details JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_auto_post_activity_workspace_id ON public.auto_post_activity(workspace_id);

-- ============================================
-- AUTO POST STATE
-- ============================================
CREATE TABLE public.auto_post_state (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  last_post_at TIMESTAMPTZ,
  posts_today INTEGER DEFAULT 0,
  posts_this_hour INTEGER DEFAULT 0,
  consecutive_failures INTEGER DEFAULT 0,
  is_paused BOOLEAN DEFAULT FALSE,
  pause_reason TEXT,
  paused_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(workspace_id)
);

-- ============================================
-- RATE LIMIT TRACKING (Threads)
-- ============================================
CREATE TABLE public.rate_limit_tracking (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id TEXT NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
  hourly_count INTEGER DEFAULT 0,
  daily_count INTEGER DEFAULT 0,
  hourly_reset_at TIMESTAMPTZ,
  daily_reset_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(account_id)
);

-- ============================================
-- INSTAGRAM RATE LIMIT TRACKING
-- ============================================
CREATE TABLE public.ig_rate_limit_tracking (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES public.instagram_accounts(id) ON DELETE CASCADE,
  daily_count INTEGER DEFAULT 0,
  daily_reset_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(account_id)
);

-- ============================================
-- INSTAGRAM ENDPOINT RATE LIMITS
-- ============================================
CREATE TABLE public.ig_endpoint_rate_limits (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES public.instagram_accounts(id) ON DELETE CASCADE,
  endpoint TEXT NOT NULL, -- 'comments', 'messages', 'hashtags'
  hourly_count INTEGER DEFAULT 0,
  daily_count INTEGER DEFAULT 0,
  hourly_reset_at TIMESTAMPTZ,
  daily_reset_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(account_id, endpoint)
);

-- ============================================
-- INSTAGRAM WEBHOOK EVENTS
-- ============================================
CREATE TABLE public.ig_webhook_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'processed', 'failed', 'dead_letter')),
  retry_count INTEGER DEFAULT 0,
  next_retry_at TIMESTAMPTZ,
  error_message TEXT,
  processed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- THREADS WEBHOOK EVENTS
-- ============================================
CREATE TABLE public.threads_webhook_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'processed', 'failed', 'dead_letter')),
  retry_count INTEGER DEFAULT 0,
  next_retry_at TIMESTAMPTZ,
  error_message TEXT,
  processed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- INSTAGRAM COMMENTS (from webhooks)
-- ============================================
CREATE TABLE public.ig_comments (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES public.instagram_accounts(id) ON DELETE CASCADE,
  media_id TEXT NOT NULL,
  comment_id TEXT NOT NULL UNIQUE,
  username TEXT,
  text TEXT,
  timestamp TIMESTAMPTZ,
  parent_id TEXT,
  is_hidden BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- INSTAGRAM MENTIONS (from webhooks)
-- ============================================
CREATE TABLE public.ig_mentions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES public.instagram_accounts(id) ON DELETE CASCADE,
  media_id TEXT NOT NULL,
  comment_id TEXT,
  username TEXT,
  text TEXT,
  timestamp TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- INSTAGRAM STORY INSIGHTS
-- ============================================
CREATE TABLE public.ig_story_insights (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES public.instagram_accounts(id) ON DELETE CASCADE,
  media_id TEXT NOT NULL,
  impressions INTEGER DEFAULT 0,
  reach INTEGER DEFAULT 0,
  replies INTEGER DEFAULT 0,
  taps_forward INTEGER DEFAULT 0,
  taps_back INTEGER DEFAULT 0,
  exits INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(media_id)
);

-- ============================================
-- INSTAGRAM PENDING CONTAINERS
-- ============================================
CREATE TABLE public.ig_pending_containers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES public.instagram_accounts(id) ON DELETE CASCADE,
  container_id TEXT NOT NULL,
  post_id TEXT REFERENCES public.posts(id) ON DELETE SET NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'published', 'failed', 'dead_letter')),
  retry_count INTEGER DEFAULT 0,
  next_retry_at TIMESTAMPTZ,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- INSTAGRAM DM TEMPLATES
-- ============================================
CREATE TABLE public.ig_dm_templates (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  category TEXT,
  use_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- INSTAGRAM AUTO RESPONDERS
-- ============================================
CREATE TABLE public.ig_auto_responders (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id UUID REFERENCES public.instagram_accounts(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  trigger_type TEXT NOT NULL, -- 'keyword', 'mention', 'first_message'
  trigger_value TEXT,
  response_template TEXT NOT NULL,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- CRON LOCKS (distributed locking)
-- ============================================
CREATE TABLE public.cron_locks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  lock_name TEXT NOT NULL UNIQUE,
  locked_by TEXT,
  locked_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- CRON RUNS (execution history)
-- ============================================
CREATE TABLE public.cron_runs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  job_name TEXT NOT NULL,
  status TEXT DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
  started_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  duration_ms INTEGER,
  items_processed INTEGER DEFAULT 0,
  error_message TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cron_runs_job_name ON public.cron_runs(job_name);

-- ============================================
-- SYNC JOBS (real-time progress tracking)
-- ============================================
CREATE TABLE public.sync_jobs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id TEXT,
  job_type TEXT NOT NULL DEFAULT 'full_sync',
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
  progress INTEGER DEFAULT 0,
  total INTEGER DEFAULT 100,
  message TEXT,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sync_jobs_user_id ON public.sync_jobs(user_id);

-- ============================================
-- GROUP ANALYTICS (pre-computed)
-- ============================================
CREATE TABLE public.group_analytics (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  group_id TEXT NOT NULL REFERENCES public.account_groups(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  total_followers INTEGER DEFAULT 0,
  total_views INTEGER DEFAULT 0,
  total_likes INTEGER DEFAULT 0,
  total_replies INTEGER DEFAULT 0,
  total_reposts INTEGER DEFAULT 0,
  post_count INTEGER DEFAULT 0,
  engagement_rate DECIMAL(8,4) DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(group_id, date)
);

CREATE INDEX idx_group_analytics_group_id ON public.group_analytics(group_id);

-- ============================================
-- LINK PAGES (link-in-bio)
-- ============================================
CREATE TABLE public.link_pages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  bio TEXT,
  avatar_url TEXT,
  theme JSONB DEFAULT '{}',
  is_published BOOLEAN DEFAULT TRUE,
  view_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_link_pages_slug ON public.link_pages(slug);

-- ============================================
-- LINK ITEMS
-- ============================================
CREATE TABLE public.link_items (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  page_id UUID NOT NULL REFERENCES public.link_pages(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  icon TEXT,
  position INTEGER DEFAULT 0,
  click_count INTEGER DEFAULT 0,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_link_items_page_id ON public.link_items(page_id);

-- ============================================
-- LINK CLICKS
-- ============================================
CREATE TABLE public.link_clicks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  link_id UUID NOT NULL REFERENCES public.link_items(id) ON DELETE CASCADE,
  page_id UUID NOT NULL REFERENCES public.link_pages(id) ON DELETE CASCADE,
  referrer TEXT,
  user_agent TEXT,
  country TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_link_clicks_link_id ON public.link_clicks(link_id);
CREATE INDEX idx_link_clicks_page_id ON public.link_clicks(page_id);

-- ============================================
-- CROSS POST SETTINGS
-- ============================================
CREATE TABLE public.cross_post_settings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  source_account_id TEXT,
  target_account_id TEXT,
  auto_cross_post BOOLEAN DEFAULT FALSE,
  delay_minutes INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(source_account_id, target_account_id)
);

-- ============================================
-- AI FEEDBACK (learning loop)
-- ============================================
CREATE TABLE public.ai_feedback (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  suggestion_type TEXT NOT NULL,
  suggestion_content TEXT,
  action TEXT NOT NULL, -- 'used', 'edited', 'dismissed'
  edited_content TEXT,
  context JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ai_feedback_user_id ON public.ai_feedback(user_id);

-- ============================================
-- REFERRALS
-- ============================================
CREATE TABLE public.referrals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  referrer_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  referred_id TEXT REFERENCES public.profiles(id) ON DELETE SET NULL,
  referral_code TEXT NOT NULL UNIQUE,
  status TEXT DEFAULT 'pending',
  reward_granted BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_referrals_referrer_id ON public.referrals(referrer_id);
CREATE INDEX idx_referrals_referral_code ON public.referrals(referral_code);

-- ============================================
-- MENTIONS
-- ============================================
CREATE TABLE public.mentions (
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
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(threads_post_id)
);

CREATE INDEX idx_mentions_user_id ON public.mentions(user_id);
CREATE INDEX idx_mentions_account_id ON public.mentions(account_id);

-- ============================================
-- SAVED COMPETITOR POSTS (inspiration)
-- ============================================
CREATE TABLE public.saved_competitor_posts (
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

CREATE INDEX idx_saved_competitor_posts_user_id ON public.saved_competitor_posts(user_id);

-- ============================================
-- INSPIRATION IDEAS (AI-generated content variants)
-- ============================================
CREATE TABLE public.inspiration_ideas (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  workspace_id TEXT REFERENCES public.workspaces(id) ON DELETE CASCADE,
  original_post JSONB NOT NULL,
  competitor_id TEXT REFERENCES public.competitors(id) ON DELETE SET NULL,
  competitor_username TEXT NOT NULL,
  competitor_avatar_url TEXT,
  adapted_content TEXT NOT NULL,
  viral_score INTEGER DEFAULT 50 CHECK (viral_score >= 0 AND viral_score <= 100),
  ai_insight TEXT,
  topic_tags TEXT[],
  adaptation_style TEXT DEFAULT 'casual',
  adaptation_angle TEXT DEFAULT 'direct',
  viral_formula TEXT,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'saved', 'queued', 'posted', 'dismissed')),
  saved BOOLEAN DEFAULT FALSE,
  queued BOOLEAN DEFAULT FALSE,
  queued_at TIMESTAMPTZ,
  posted_at TIMESTAMPTZ,
  generated_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_inspiration_ideas_user_id ON public.inspiration_ideas(user_id);
CREATE INDEX idx_inspiration_ideas_status ON public.inspiration_ideas(status);

-- ============================================
-- INSPIRATION CONFIG (per-user settings)
-- ============================================
CREATE TABLE public.inspiration_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  workspace_id TEXT REFERENCES public.workspaces(id) ON DELETE CASCADE,
  enabled BOOLEAN DEFAULT TRUE,
  ideas_per_competitor INTEGER DEFAULT 10,
  adaptation_style TEXT DEFAULT 'casual',
  topic_filters TEXT[],
  notify_new_ideas BOOLEAN DEFAULT TRUE,
  daily_digest_enabled BOOLEAN DEFAULT FALSE,
  last_scan_at TIMESTAMPTZ,
  ideas_generated_today INTEGER DEFAULT 0,
  last_generation_reset DATE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id)
);

-- ============================================
-- WORKSPACE ACTIVITY
-- ============================================
CREATE TABLE public.workspace_activity (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id TEXT NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES public.profiles(id),
  action_type TEXT NOT NULL,
  action_details JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_workspace_activity_workspace_id ON public.workspace_activity(workspace_id);

-- ============================================
-- TRIAL TRACKING (abuse prevention)
-- ============================================
CREATE TABLE public.trial_emails (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email_hash TEXT NOT NULL UNIQUE,
  used_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trial_emails_hash ON public.trial_emails(email_hash);

-- ============================================
-- AI CONFIG
-- ============================================
CREATE TABLE public.ai_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  provider TEXT DEFAULT 'gemini',
  api_key TEXT,
  base_url TEXT,
  model TEXT,
  last_validated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id)
);

-- ============================================
-- USER PREFERENCES
-- ============================================
CREATE TABLE public.user_preferences (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  onboarding_completed BOOLEAN DEFAULT FALSE,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id)
);

-- ============================================
-- VIEWS
-- ============================================
CREATE OR REPLACE VIEW public.groups AS
SELECT * FROM public.account_groups;

CREATE OR REPLACE VIEW public.user_workspaces AS
SELECT
  w.id,
  w.name,
  w.tier,
  w.settings,
  w.owner_id,
  w.created_at,
  wm.user_id,
  wm.role
FROM public.workspaces w
INNER JOIN public.workspace_members wm ON w.id = wm.workspace_id;

-- ============================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================

-- Enable RLS on all tables
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.instagram_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_replies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sent_replies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.competitors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.competitor_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.competitor_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.competitor_top_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.media_folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.media ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.favorites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.account_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.queue_slots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.account_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auto_post_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auto_post_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auto_post_activity ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auto_post_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rate_limit_tracking ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ig_rate_limit_tracking ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ig_endpoint_rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ig_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.threads_webhook_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ig_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ig_mentions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ig_story_insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ig_pending_containers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ig_dm_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ig_auto_responders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cron_locks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cron_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sync_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.group_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.link_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.link_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.link_clicks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cross_post_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referrals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trial_emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saved_competitor_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inspiration_ideas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inspiration_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mentions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_activity ENABLE ROW LEVEL SECURITY;

-- RLS Policies (using auth.uid()::text for TEXT user_id columns)

-- Profiles
CREATE POLICY "Users can view own profile" ON public.profiles FOR SELECT USING (auth.uid()::text = id);
CREATE POLICY "Users can update own profile" ON public.profiles FOR UPDATE USING (auth.uid()::text = id);
CREATE POLICY "Users can insert own profile" ON public.profiles FOR INSERT WITH CHECK (auth.uid()::text = id);

-- Accounts
CREATE POLICY "Users can manage own accounts" ON public.accounts FOR ALL USING (auth.uid()::text = user_id);

-- Instagram accounts
CREATE POLICY "Users can manage own instagram accounts" ON public.instagram_accounts FOR ALL USING (auth.uid()::text = user_id);

-- Posts
CREATE POLICY "Users can manage own posts" ON public.posts FOR ALL USING (auth.uid()::text = user_id);

-- Post replies
CREATE POLICY "Users can view replies on own posts" ON public.post_replies FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.posts WHERE posts.id = post_replies.post_id AND posts.user_id = auth.uid()::text));

-- Sent replies
CREATE POLICY "Users can manage own sent replies" ON public.sent_replies FOR ALL USING (auth.uid()::text = user_id);

-- Competitors
CREATE POLICY "Users can manage own competitors" ON public.competitors FOR ALL USING (auth.uid()::text = user_id);

-- Competitor snapshots
CREATE POLICY "Users can view own competitor snapshots" ON public.competitor_snapshots FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.competitors WHERE competitors.id = competitor_snapshots.competitor_id AND competitors.user_id = auth.uid()::text));

-- Competitor posts
CREATE POLICY "Users can view own competitor posts" ON public.competitor_posts FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.competitors WHERE competitors.id = competitor_posts.competitor_id AND competitors.user_id = auth.uid()::text));

-- Competitor top posts
CREATE POLICY "Users can view competitor top posts" ON public.competitor_top_posts FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.competitors WHERE competitors.id = competitor_top_posts.competitor_id AND competitors.user_id = auth.uid()::text));
CREATE POLICY "Users can insert competitor top posts" ON public.competitor_top_posts FOR INSERT
  WITH CHECK (EXISTS (SELECT 1 FROM public.competitors WHERE competitors.id = competitor_top_posts.competitor_id AND competitors.user_id = auth.uid()::text));

-- Media
CREATE POLICY "Users can manage own media folders" ON public.media_folders FOR ALL USING (auth.uid()::text = user_id);
CREATE POLICY "Users can manage own media" ON public.media FOR ALL USING (auth.uid()::text = user_id);

-- Favorites
CREATE POLICY "Users can manage own favorites" ON public.favorites FOR ALL USING (auth.uid()::text = user_id);

-- Account groups
CREATE POLICY "Users can manage own account groups" ON public.account_groups FOR ALL USING (auth.uid()::text = user_id);

-- Queue slots
CREATE POLICY "Users can manage own queue slots" ON public.queue_slots FOR ALL USING (auth.uid()::text = user_id);

-- Notifications
CREATE POLICY "Users can manage own notifications" ON public.notifications FOR ALL USING (auth.uid()::text = user_id);

-- User settings
CREATE POLICY "Users can manage own settings" ON public.user_settings FOR ALL USING (auth.uid()::text = user_id);

-- Account analytics
CREATE POLICY "Users can view own account analytics" ON public.account_analytics FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.accounts WHERE accounts.id = account_analytics.account_id AND accounts.user_id = auth.uid()::text));

-- Workspaces (uses SECURITY DEFINER helpers to avoid circular RLS recursion)
CREATE OR REPLACE FUNCTION is_workspace_member(p_workspace_id TEXT, p_user_id TEXT)
RETURNS BOOLEAN AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.workspace_members
    WHERE workspace_id = p_workspace_id AND user_id = p_user_id
  );
$$ LANGUAGE sql SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION is_workspace_owner(p_workspace_id TEXT, p_user_id TEXT)
RETURNS BOOLEAN AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.workspaces
    WHERE id = p_workspace_id AND owner_id = p_user_id
  );
$$ LANGUAGE sql SECURITY DEFINER SET search_path = public;

CREATE POLICY "Workspace access for members" ON public.workspaces FOR SELECT
  USING (owner_id = auth.uid()::text OR is_workspace_member(id, auth.uid()::text));
CREATE POLICY "Workspace owners can update" ON public.workspaces FOR UPDATE USING (owner_id = auth.uid()::text);
CREATE POLICY "Users can create workspaces" ON public.workspaces FOR INSERT WITH CHECK (owner_id = auth.uid()::text);

-- Workspace members
CREATE POLICY "Workspace members can view" ON public.workspace_members FOR SELECT
  USING (user_id = auth.uid()::text OR is_workspace_owner(workspace_id, auth.uid()::text));

-- Workspace activity
CREATE POLICY "Workspace activity access" ON public.workspace_activity FOR SELECT
  USING (is_workspace_member(workspace_id, auth.uid()::text));
CREATE POLICY "Workspace members can log activity" ON public.workspace_activity FOR INSERT
  WITH CHECK (is_workspace_member(workspace_id, auth.uid()::text));

-- Auto-post (workspace-scoped)
CREATE POLICY "Auto-post config access" ON public.auto_post_config FOR ALL
  USING (is_workspace_member(workspace_id, auth.uid()::text));
CREATE POLICY "Auto-post queue access" ON public.auto_post_queue FOR ALL
  USING (is_workspace_member(workspace_id, auth.uid()::text));
CREATE POLICY "Auto-post activity access" ON public.auto_post_activity FOR SELECT
  USING (is_workspace_member(workspace_id, auth.uid()::text));
CREATE POLICY "Auto-post state access" ON public.auto_post_state FOR ALL
  USING (is_workspace_member(workspace_id, auth.uid()::text));

-- Sync jobs
CREATE POLICY "Users can manage own sync jobs" ON public.sync_jobs FOR ALL USING (auth.uid()::text = user_id);

-- Group analytics
CREATE POLICY "Users can view own group analytics" ON public.group_analytics FOR ALL USING (auth.uid()::text = user_id);

-- Link pages
CREATE POLICY "Users can manage own link pages" ON public.link_pages FOR ALL USING (auth.uid()::text = user_id);
CREATE POLICY "Public can view published link pages" ON public.link_pages FOR SELECT USING (is_published = TRUE);

-- Link items
CREATE POLICY "Users can manage own link items" ON public.link_items FOR ALL
  USING (EXISTS (SELECT 1 FROM public.link_pages WHERE link_pages.id = link_items.page_id AND link_pages.user_id = auth.uid()::text));

-- Link clicks (public insert for tracking)
CREATE POLICY "Anyone can insert link clicks" ON public.link_clicks FOR INSERT WITH CHECK (TRUE);
CREATE POLICY "Users can view own link clicks" ON public.link_clicks FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.link_pages WHERE link_pages.id = link_clicks.page_id AND link_pages.user_id = auth.uid()::text));

-- Cross post settings
CREATE POLICY "Users can manage own cross post settings" ON public.cross_post_settings FOR ALL USING (auth.uid()::text = user_id);

-- AI feedback
CREATE POLICY "Users can manage own ai feedback" ON public.ai_feedback FOR ALL USING (auth.uid()::text = user_id);

-- Referrals
CREATE POLICY "Users can manage own referrals" ON public.referrals FOR ALL USING (auth.uid()::text = referrer_id);

-- AI config
CREATE POLICY "Users can manage own AI config" ON public.ai_config FOR ALL USING (auth.uid()::text = user_id);

-- User preferences
CREATE POLICY "Users can manage own preferences" ON public.user_preferences FOR ALL USING (auth.uid()::text = user_id);

-- Saved competitor posts
CREATE POLICY "Users can manage saved competitor posts" ON public.saved_competitor_posts FOR ALL USING (auth.uid()::text = user_id);

-- Inspiration
CREATE POLICY "Users can manage own inspiration ideas" ON public.inspiration_ideas FOR ALL USING (auth.uid()::text = user_id);
CREATE POLICY "Users can manage own inspiration config" ON public.inspiration_config FOR ALL USING (auth.uid()::text = user_id);

-- Mentions
CREATE POLICY "Users can manage own mentions" ON public.mentions FOR ALL USING (auth.uid()::text = user_id);

-- DM templates
CREATE POLICY "Users can manage own dm templates" ON public.ig_dm_templates FOR ALL USING (auth.uid()::text = user_id);

-- Auto responders
CREATE POLICY "Users can manage own auto responders" ON public.ig_auto_responders FOR ALL USING (auth.uid()::text = user_id);

-- ============================================
-- FUNCTIONS & TRIGGERS
-- ============================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at trigger to relevant tables
CREATE TRIGGER update_profiles_updated_at BEFORE UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_accounts_updated_at BEFORE UPDATE ON public.accounts FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_posts_updated_at BEFORE UPDATE ON public.posts FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_competitors_updated_at BEFORE UPDATE ON public.competitors FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_account_groups_updated_at BEFORE UPDATE ON public.account_groups FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_user_settings_updated_at BEFORE UPDATE ON public.user_settings FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_workspaces_updated_at BEFORE UPDATE ON public.workspaces FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER update_auto_post_config_updated_at BEFORE UPDATE ON public.auto_post_config FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Function to create profile on user signup
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, email)
  VALUES (NEW.id::text, NEW.email);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- Trigger to auto-create profile when user signs up
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ============================================
-- SQL FUNCTIONS (RPC)
-- ============================================

-- Threads rate limit (atomic, row-locked)
CREATE OR REPLACE FUNCTION check_and_increment_rate_limit(
  p_account_id TEXT,
  p_hourly_limit INTEGER DEFAULT 3,
  p_daily_limit INTEGER DEFAULT 20
) RETURNS JSONB AS $$
DECLARE
  v_result JSONB;
  v_row rate_limit_tracking%ROWTYPE;
BEGIN
  -- Upsert and lock the row
  INSERT INTO rate_limit_tracking (account_id, hourly_count, daily_count, hourly_reset_at, daily_reset_at)
  VALUES (p_account_id, 0, 0, NOW() + INTERVAL '1 hour', NOW() + INTERVAL '1 day')
  ON CONFLICT (account_id) DO NOTHING;

  SELECT * INTO v_row FROM rate_limit_tracking WHERE account_id = p_account_id FOR UPDATE;

  -- Reset counters if windows expired
  IF v_row.hourly_reset_at <= NOW() THEN
    v_row.hourly_count := 0;
    v_row.hourly_reset_at := NOW() + INTERVAL '1 hour';
  END IF;
  IF v_row.daily_reset_at <= NOW() THEN
    v_row.daily_count := 0;
    v_row.daily_reset_at := NOW() + INTERVAL '1 day';
  END IF;

  -- Check limits
  IF v_row.hourly_count >= p_hourly_limit THEN
    RETURN jsonb_build_object('allowed', FALSE, 'reason', 'Hourly limit reached');
  END IF;
  IF v_row.daily_count >= p_daily_limit THEN
    RETURN jsonb_build_object('allowed', FALSE, 'reason', 'Daily limit reached');
  END IF;

  -- Increment
  UPDATE rate_limit_tracking
  SET hourly_count = v_row.hourly_count + 1,
      daily_count = v_row.daily_count + 1,
      hourly_reset_at = v_row.hourly_reset_at,
      daily_reset_at = v_row.daily_reset_at,
      updated_at = NOW()
  WHERE account_id = p_account_id;

  RETURN jsonb_build_object('allowed', TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- Instagram daily rate limit (100 posts/24h enforced by callers)
CREATE OR REPLACE FUNCTION ig_check_and_increment_rate_limit(
  p_account_id UUID,
  p_daily_limit INTEGER DEFAULT 50
)
RETURNS TABLE(allowed BOOLEAN, reason TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_daily_count INTEGER;
BEGIN
  -- Lock the row for this account to prevent race conditions
  PERFORM 1 FROM ig_rate_limit_tracking
  WHERE account_id = p_account_id
  FOR UPDATE;

  -- Get or create tracking record
  INSERT INTO ig_rate_limit_tracking (account_id, daily_count, last_reset_at)
  VALUES (p_account_id, 0, NOW())
  ON CONFLICT (account_id) DO NOTHING;

  -- Reset daily counter if last reset was more than 24 hours ago
  UPDATE ig_rate_limit_tracking
  SET daily_count = 0, last_reset_at = NOW()
  WHERE account_id = p_account_id
    AND last_reset_at < NOW() - INTERVAL '24 hours';

  -- Get current count
  SELECT daily_count INTO v_daily_count
  FROM ig_rate_limit_tracking
  WHERE account_id = p_account_id;

  -- Check limit
  IF v_daily_count >= p_daily_limit THEN
    RETURN QUERY SELECT FALSE, FORMAT('Daily limit reached (%s/%s)', v_daily_count, p_daily_limit);
    RETURN;
  END IF;

  -- Increment counter
  UPDATE ig_rate_limit_tracking
  SET daily_count = daily_count + 1
  WHERE account_id = p_account_id;

  RETURN QUERY SELECT TRUE, NULL::TEXT;
END;
$$;

-- Per-endpoint IG API limits
CREATE OR REPLACE FUNCTION check_ig_endpoint_limit(
  p_account_id UUID,
  p_endpoint TEXT,
  p_hourly_limit INTEGER,
  p_daily_limit INTEGER
) RETURNS JSONB AS $$
DECLARE
  v_row ig_endpoint_rate_limits%ROWTYPE;
BEGIN
  INSERT INTO ig_endpoint_rate_limits (account_id, endpoint, hourly_count, daily_count, hourly_reset_at, daily_reset_at)
  VALUES (p_account_id, p_endpoint, 0, 0, NOW() + INTERVAL '1 hour', NOW() + INTERVAL '1 day')
  ON CONFLICT (account_id, endpoint) DO NOTHING;

  SELECT * INTO v_row FROM ig_endpoint_rate_limits
  WHERE account_id = p_account_id AND endpoint = p_endpoint FOR UPDATE;

  IF v_row.hourly_reset_at <= NOW() THEN
    v_row.hourly_count := 0;
    v_row.hourly_reset_at := NOW() + INTERVAL '1 hour';
  END IF;
  IF v_row.daily_reset_at <= NOW() THEN
    v_row.daily_count := 0;
    v_row.daily_reset_at := NOW() + INTERVAL '1 day';
  END IF;

  IF v_row.hourly_count >= p_hourly_limit THEN
    RETURN jsonb_build_object('allowed', FALSE, 'reason', 'Hourly endpoint limit reached');
  END IF;
  IF v_row.daily_count >= p_daily_limit THEN
    RETURN jsonb_build_object('allowed', FALSE, 'reason', 'Daily endpoint limit reached');
  END IF;

  UPDATE ig_endpoint_rate_limits
  SET hourly_count = v_row.hourly_count + 1,
      daily_count = v_row.daily_count + 1,
      hourly_reset_at = v_row.hourly_reset_at,
      daily_reset_at = v_row.daily_reset_at,
      updated_at = NOW()
  WHERE account_id = p_account_id AND endpoint = p_endpoint;

  RETURN jsonb_build_object('allowed', TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- Distributed cron locking
CREATE OR REPLACE FUNCTION acquire_cron_lock(
  p_lock_name TEXT,
  p_locked_by TEXT DEFAULT 'cron',
  p_ttl_minutes INTEGER DEFAULT 10
) RETURNS BOOLEAN AS $$
DECLARE
  v_acquired BOOLEAN := FALSE;
BEGIN
  -- Try to insert or update expired lock
  INSERT INTO cron_locks (lock_name, locked_by, locked_at, expires_at)
  VALUES (p_lock_name, p_locked_by, NOW(), NOW() + (p_ttl_minutes || ' minutes')::interval)
  ON CONFLICT (lock_name) DO UPDATE
  SET locked_by = p_locked_by,
      locked_at = NOW(),
      expires_at = NOW() + (p_ttl_minutes || ' minutes')::interval
  WHERE cron_locks.expires_at < NOW();

  GET DIAGNOSTICS v_acquired = ROW_COUNT;
  RETURN v_acquired > 0;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

CREATE OR REPLACE FUNCTION release_cron_lock(p_lock_name TEXT)
RETURNS void AS $$
BEGIN
  DELETE FROM cron_locks WHERE lock_name = p_lock_name;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- Atomic DM template counter
CREATE OR REPLACE FUNCTION increment_dm_template_use(p_template_id UUID)
RETURNS void AS $$
BEGIN
  UPDATE ig_dm_templates SET use_count = use_count + 1, updated_at = NOW()
  WHERE id = p_template_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- Read-only rate limit status
CREATE OR REPLACE FUNCTION get_rate_limit_status(p_account_id TEXT)
RETURNS JSONB AS $$
DECLARE
  v_row rate_limit_tracking%ROWTYPE;
BEGIN
  SELECT * INTO v_row FROM rate_limit_tracking WHERE account_id = p_account_id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('hourly_count', 0, 'daily_count', 0);
  END IF;
  RETURN jsonb_build_object(
    'hourly_count', v_row.hourly_count,
    'daily_count', v_row.daily_count,
    'hourly_reset_at', v_row.hourly_reset_at,
    'daily_reset_at', v_row.daily_reset_at
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- Pre-compute group-level analytics
CREATE OR REPLACE FUNCTION refresh_group_analytics()
RETURNS void AS $$
BEGIN
  INSERT INTO group_analytics (group_id, user_id, date, total_followers, total_views, total_likes, total_replies, total_reposts, post_count)
  SELECT
    ag.id AS group_id,
    ag.user_id,
    CURRENT_DATE AS date,
    COALESCE(SUM(a.follower_count), 0) AS total_followers,
    COALESCE(SUM(aa.total_views), 0) AS total_views,
    COALESCE(SUM(aa.total_likes), 0) AS total_likes,
    COALESCE(SUM(aa.total_replies), 0) AS total_replies,
    COALESCE(SUM(aa.total_reposts), 0) AS total_reposts,
    COALESCE(SUM(aa.posts_count), 0) AS post_count
  FROM account_groups ag
  CROSS JOIN LATERAL unnest(ag.account_ids) AS aid(account_id)
  LEFT JOIN accounts a ON a.id = aid.account_id
  LEFT JOIN account_analytics aa ON aa.account_id = aid.account_id AND aa.date = CURRENT_DATE
  GROUP BY ag.id, ag.user_id
  ON CONFLICT (group_id, date) DO UPDATE SET
    total_followers = EXCLUDED.total_followers,
    total_views = EXCLUDED.total_views,
    total_likes = EXCLUDED.total_likes,
    total_replies = EXCLUDED.total_replies,
    total_reposts = EXCLUDED.total_reposts,
    post_count = EXCLUDED.post_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- Atomic link click counter
CREATE OR REPLACE FUNCTION increment_link_click(p_link_id UUID)
RETURNS void AS $$
BEGIN
  UPDATE link_items SET click_count = click_count + 1 WHERE id = p_link_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- Atomic account-to-group assignment (eliminates fetch-modify-write race condition)
CREATE OR REPLACE FUNCTION assign_account_to_group(
  p_account_id TEXT,
  p_target_group_id TEXT,
  p_user_id TEXT
) RETURNS void AS $$
BEGIN
  UPDATE account_groups
  SET account_ids = array_remove(account_ids, p_account_id),
      updated_at = NOW()
  WHERE user_id = p_user_id
    AND p_account_id = ANY(account_ids);

  IF p_target_group_id IS NOT NULL THEN
    UPDATE account_groups
    SET account_ids = array_append(account_ids, p_account_id),
        updated_at = NOW()
    WHERE id = p_target_group_id
      AND user_id = p_user_id;
  END IF;

  UPDATE accounts
  SET group_id = p_target_group_id,
      updated_at = NOW()
  WHERE id = p_account_id
    AND user_id = p_user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

-- ============================================
-- STORAGE BUCKETS
-- ============================================
-- Create storage bucket for media files via Supabase Dashboard
-- After creating 'media' bucket, apply these policies:
-- INSERT: bucket_id = 'media' AND auth.uid()::text = (storage.foldername(name))[1]
-- SELECT: bucket_id = 'media' AND auth.uid()::text = (storage.foldername(name))[1]
-- DELETE: bucket_id = 'media' AND auth.uid()::text = (storage.foldername(name))[1]
-- Public read: bucket_id = 'media' (anon role)

-- ============================================
-- DONE!
-- ============================================
