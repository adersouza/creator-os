-- ThreadsDashboard Safe Migration
-- Only creates tables/columns that don't exist
-- Run this in Supabase SQL Editor

-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- ADD MISSING COLUMNS TO EXISTING TABLES
-- ============================================

-- Profiles table - add missing columns
DO $$
BEGIN
  -- Add subscription columns if missing
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'subscription_tier') THEN
    ALTER TABLE public.profiles ADD COLUMN subscription_tier TEXT DEFAULT 'free';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'subscription_status') THEN
    ALTER TABLE public.profiles ADD COLUMN subscription_status TEXT DEFAULT 'none';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'stripe_customer_id') THEN
    ALTER TABLE public.profiles ADD COLUMN stripe_customer_id TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'stripe_subscription_id') THEN
    ALTER TABLE public.profiles ADD COLUMN stripe_subscription_id TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'has_used_trial') THEN
    ALTER TABLE public.profiles ADD COLUMN has_used_trial BOOLEAN DEFAULT FALSE;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'trial_started_at') THEN
    ALTER TABLE public.profiles ADD COLUMN trial_started_at TIMESTAMPTZ;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'trial_ends_at') THEN
    ALTER TABLE public.profiles ADD COLUMN trial_ends_at TIMESTAMPTZ;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'timezone') THEN
    ALTER TABLE public.profiles ADD COLUMN timezone TEXT DEFAULT 'America/New_York';
  END IF;
END $$;

-- Accounts table - add missing columns
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'accounts' AND column_name = 'workspace_id') THEN
    ALTER TABLE public.accounts ADD COLUMN workspace_id UUID;
  END IF;
END $$;

-- Media table - add missing columns
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'media' AND column_name = 'group_id') THEN
    ALTER TABLE public.media ADD COLUMN group_id UUID;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'media' AND column_name = 'storage_url') THEN
    ALTER TABLE public.media ADD COLUMN storage_url TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'media' AND column_name = 'storage_path') THEN
    ALTER TABLE public.media ADD COLUMN storage_path TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'media' AND column_name = 'mime_type') THEN
    ALTER TABLE public.media ADD COLUMN mime_type TEXT;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'media' AND column_name = 'url') THEN
    ALTER TABLE public.media ADD COLUMN url TEXT;
  END IF;
END $$;

-- Workspaces table - add missing columns
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'workspaces' AND column_name = 'extra_accounts') THEN
    ALTER TABLE public.workspaces ADD COLUMN extra_accounts INTEGER DEFAULT 0;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'workspaces' AND column_name = 'extra_team_members') THEN
    ALTER TABLE public.workspaces ADD COLUMN extra_team_members INTEGER DEFAULT 0;
  END IF;
END $$;

-- ============================================
-- CREATE MISSING TABLES
-- ============================================

-- Trial tracking (abuse prevention)
CREATE TABLE IF NOT EXISTS public.trial_emails (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email_hash TEXT NOT NULL UNIQUE,
  used_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- AI Config
CREATE TABLE IF NOT EXISTS public.ai_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  provider TEXT DEFAULT 'gemini',
  api_key TEXT,
  base_url TEXT,
  model TEXT,
  last_validated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id)
);

-- User Preferences
CREATE TABLE IF NOT EXISTS public.user_preferences (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  onboarding_completed BOOLEAN DEFAULT FALSE,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id)
);

-- Auto Post State
CREATE TABLE IF NOT EXISTS public.auto_post_state (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL,
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

-- Competitor Posts
CREATE TABLE IF NOT EXISTS public.competitor_posts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  competitor_id UUID NOT NULL,
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

-- Saved Competitor Posts (inspiration)
CREATE TABLE IF NOT EXISTS public.saved_competitor_posts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  competitor_post_id UUID,
  threads_post_id TEXT,
  content TEXT,
  username TEXT,
  avatar_url TEXT,
  media_urls TEXT[],
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Mentions
CREATE TABLE IF NOT EXISTS public.mentions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id UUID,
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

-- Workspace Activity
CREATE TABLE IF NOT EXISTS public.workspace_activity (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  workspace_id UUID NOT NULL,
  user_id UUID,
  action_type TEXT NOT NULL,
  action_details JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- CREATE INDEXES (IF NOT EXISTS)
-- ============================================

CREATE INDEX IF NOT EXISTS idx_trial_emails_hash ON public.trial_emails(email_hash);
CREATE INDEX IF NOT EXISTS idx_ai_config_user_id ON public.ai_config(user_id);
CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON public.user_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_auto_post_state_workspace_id ON public.auto_post_state(workspace_id);
CREATE INDEX IF NOT EXISTS idx_competitor_posts_competitor_id ON public.competitor_posts(competitor_id);
CREATE INDEX IF NOT EXISTS idx_saved_competitor_posts_user_id ON public.saved_competitor_posts(user_id);
CREATE INDEX IF NOT EXISTS idx_mentions_user_id ON public.mentions(user_id);
CREATE INDEX IF NOT EXISTS idx_mentions_account_id ON public.mentions(account_id);
CREATE INDEX IF NOT EXISTS idx_workspace_activity_workspace_id ON public.workspace_activity(workspace_id);
CREATE INDEX IF NOT EXISTS idx_media_group_id ON public.media(group_id);

-- ============================================
-- ENABLE RLS ON NEW TABLES
-- ============================================

ALTER TABLE public.trial_emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.auto_post_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.competitor_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.saved_competitor_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mentions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.workspace_activity ENABLE ROW LEVEL SECURITY;

-- ============================================
-- CREATE RLS POLICIES (DROP IF EXISTS FIRST)
-- ============================================

-- AI Config policies
DROP POLICY IF EXISTS "Users can manage own AI config" ON public.ai_config;
CREATE POLICY "Users can manage own AI config" ON public.ai_config FOR ALL USING (auth.uid() = user_id);

-- User Preferences policies
DROP POLICY IF EXISTS "Users can manage own preferences" ON public.user_preferences;
CREATE POLICY "Users can manage own preferences" ON public.user_preferences FOR ALL USING (auth.uid() = user_id);

-- Saved Competitor Posts policies
DROP POLICY IF EXISTS "Users can manage saved competitor posts" ON public.saved_competitor_posts;
CREATE POLICY "Users can manage saved competitor posts" ON public.saved_competitor_posts FOR ALL USING (auth.uid() = user_id);

-- Mentions policies
DROP POLICY IF EXISTS "Users can manage own mentions" ON public.mentions;
CREATE POLICY "Users can manage own mentions" ON public.mentions FOR ALL USING (auth.uid() = user_id);

-- ============================================
-- CREATE OR REPLACE FUNCTIONS
-- ============================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers to new tables (drop first to avoid duplicates)
DROP TRIGGER IF EXISTS update_ai_config_updated_at ON public.ai_config;
CREATE TRIGGER update_ai_config_updated_at BEFORE UPDATE ON public.ai_config FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS update_user_preferences_updated_at ON public.user_preferences;
CREATE TRIGGER update_user_preferences_updated_at BEFORE UPDATE ON public.user_preferences FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS update_auto_post_state_updated_at ON public.auto_post_state;
CREATE TRIGGER update_auto_post_state_updated_at BEFORE UPDATE ON public.auto_post_state FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================
-- CREATE VIEWS (OR REPLACE)
-- ============================================

-- Groups view (alias for account_groups if it exists)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'account_groups') THEN
    CREATE OR REPLACE VIEW public.groups AS SELECT * FROM public.account_groups;
  END IF;
END $$;

-- ============================================
-- DONE! Migration complete.
-- ============================================
SELECT 'Migration completed successfully!' as status;
