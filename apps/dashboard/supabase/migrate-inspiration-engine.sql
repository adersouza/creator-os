-- ============================================
-- INSPIRATION ENGINE MIGRATION
-- Run this in Supabase SQL Editor
-- ============================================

-- ============================================
-- INSPIRATION IDEAS (AI-generated content variants)
-- ============================================
CREATE TABLE IF NOT EXISTS public.inspiration_ideas (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  workspace_id TEXT REFERENCES public.workspaces(id) ON DELETE CASCADE,

  -- Source post data (from competitor_top_posts)
  original_post JSONB NOT NULL,  -- {id, content, media_url, permalink, engagement_score}
  competitor_id TEXT REFERENCES public.competitors(id) ON DELETE SET NULL,
  competitor_username TEXT NOT NULL,
  competitor_avatar_url TEXT,

  -- AI-generated content
  adapted_content TEXT NOT NULL,
  viral_score INTEGER DEFAULT 50 CHECK (viral_score >= 0 AND viral_score <= 100),
  ai_insight TEXT,
  topic_tags TEXT[],
  adaptation_style TEXT DEFAULT 'casual' CHECK (adaptation_style IN ('casual', 'professional', 'witty', 'inspirational', 'edgy')),

  -- Status tracking
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'saved', 'queued', 'posted', 'dismissed')),
  saved BOOLEAN DEFAULT FALSE,
  queued BOOLEAN DEFAULT FALSE,
  queued_at TIMESTAMPTZ,
  posted_at TIMESTAMPTZ,

  -- Metadata
  generated_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for inspiration_ideas
CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_user_id ON public.inspiration_ideas(user_id);
CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_workspace_id ON public.inspiration_ideas(workspace_id);
CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_competitor_id ON public.inspiration_ideas(competitor_id);
CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_status ON public.inspiration_ideas(status);
CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_generated_at ON public.inspiration_ideas(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_viral_score ON public.inspiration_ideas(viral_score DESC);

-- Enable RLS
ALTER TABLE public.inspiration_ideas ENABLE ROW LEVEL SECURITY;

-- Drop existing policy if exists (for re-running migration)
DROP POLICY IF EXISTS "Users can manage own inspiration ideas" ON public.inspiration_ideas;

-- Create RLS policy
CREATE POLICY "Users can manage own inspiration ideas" ON public.inspiration_ideas
  FOR ALL USING (auth.uid()::text = user_id);

-- ============================================
-- INSPIRATION CONFIG (per-user settings)
-- ============================================
CREATE TABLE IF NOT EXISTS public.inspiration_config (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  workspace_id TEXT REFERENCES public.workspaces(id) ON DELETE CASCADE,

  -- Generation settings
  enabled BOOLEAN DEFAULT TRUE,
  ideas_per_competitor INTEGER DEFAULT 10,
  adaptation_style TEXT DEFAULT 'casual' CHECK (adaptation_style IN ('casual', 'professional', 'witty', 'inspirational', 'edgy')),
  topic_filters TEXT[],

  -- Notification preferences
  notify_new_ideas BOOLEAN DEFAULT TRUE,
  daily_digest_enabled BOOLEAN DEFAULT FALSE,

  -- Rate limiting
  last_scan_at TIMESTAMPTZ,
  ideas_generated_today INTEGER DEFAULT 0,
  last_generation_reset DATE,

  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(user_id)
);

-- Create index for inspiration_config
CREATE INDEX IF NOT EXISTS idx_inspiration_config_user_id ON public.inspiration_config(user_id);

-- Enable RLS
ALTER TABLE public.inspiration_config ENABLE ROW LEVEL SECURITY;

-- Drop existing policy if exists (for re-running migration)
DROP POLICY IF EXISTS "Users can manage own inspiration config" ON public.inspiration_config;

-- Create RLS policy
CREATE POLICY "Users can manage own inspiration config" ON public.inspiration_config
  FOR ALL USING (auth.uid()::text = user_id);

-- ============================================
-- TRIGGER FOR updated_at
-- ============================================
-- Create trigger function if it doesn't exist
CREATE OR REPLACE FUNCTION update_inspiration_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop existing triggers if they exist
DROP TRIGGER IF EXISTS update_inspiration_ideas_updated_at ON public.inspiration_ideas;
DROP TRIGGER IF EXISTS update_inspiration_config_updated_at ON public.inspiration_config;

-- Create triggers for updated_at
CREATE TRIGGER update_inspiration_ideas_updated_at
  BEFORE UPDATE ON public.inspiration_ideas
  FOR EACH ROW EXECUTE FUNCTION update_inspiration_updated_at();

CREATE TRIGGER update_inspiration_config_updated_at
  BEFORE UPDATE ON public.inspiration_config
  FOR EACH ROW EXECUTE FUNCTION update_inspiration_updated_at();

-- ============================================
-- DONE!
-- ============================================
-- To verify, run:
-- SELECT * FROM information_schema.tables WHERE table_name LIKE 'inspiration%';
