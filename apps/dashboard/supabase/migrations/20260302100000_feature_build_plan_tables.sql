-- Migration: Feature Build Plan tables
-- Creates all tables needed for: Draft Folders, Post Templates, Watermark Configs,
-- Product Catalogs, Engagement Pods, and extends Posts/Media for new features.

-- ============================================================================
-- 1. Draft Folders
-- ============================================================================

CREATE TABLE IF NOT EXISTS draft_folders (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  account_group_id TEXT REFERENCES account_groups(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT DEFAULT '#6366f1',
  icon TEXT DEFAULT 'folder',
  sort_order INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE draft_folders ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users manage own folders" ON draft_folders
  FOR ALL USING (auth.uid()::text = user_id);

-- Add folder_id to posts
ALTER TABLE posts ADD COLUMN IF NOT EXISTS draft_folder_id TEXT REFERENCES draft_folders(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_posts_draft_folder ON posts(draft_folder_id) WHERE status = 'draft';

-- ============================================================================
-- 2. Threads Polls (column on posts)
-- ============================================================================

ALTER TABLE posts ADD COLUMN IF NOT EXISTS poll_options JSONB DEFAULT NULL;

-- ============================================================================
-- 3. Post Templates
-- ============================================================================

CREATE TABLE IF NOT EXISTS post_templates (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  account_group_id TEXT REFERENCES account_groups(id) ON DELETE CASCADE,
  workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  category TEXT DEFAULT 'general',
  platform TEXT DEFAULT 'threads' CHECK (platform IN ('threads', 'instagram', 'both')),
  text_template TEXT NOT NULL,
  media_urls TEXT[] DEFAULT '{}',
  hashtags TEXT[] DEFAULT '{}',
  poll_options JSONB,
  times_used INTEGER DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  is_shared BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE post_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users manage own templates" ON post_templates
  FOR ALL USING (auth.uid()::text = user_id);
CREATE POLICY "Team sees shared templates" ON post_templates
  FOR SELECT USING (
    is_shared = true AND workspace_id IN (
      SELECT workspace_id FROM workspace_members WHERE user_id = auth.uid()::text
    )
  );

-- ============================================================================
-- 4. Watermark Configs
-- ============================================================================

CREATE TABLE IF NOT EXISTS watermark_configs (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  account_group_id TEXT REFERENCES account_groups(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT 'Default',
  type TEXT NOT NULL CHECK (type IN ('image', 'text')),
  image_url TEXT,
  text TEXT,
  font_size INTEGER DEFAULT 16,
  font_color TEXT DEFAULT '#ffffff',
  position TEXT DEFAULT 'bottom-right' CHECK (position IN (
    'top-left','top-center','top-right',
    'center',
    'bottom-left','bottom-center','bottom-right'
  )),
  opacity FLOAT DEFAULT 0.5 CHECK (opacity BETWEEN 0 AND 1),
  scale FLOAT DEFAULT 0.15 CHECK (scale BETWEEN 0.05 AND 0.5),
  padding INTEGER DEFAULT 16,
  auto_apply BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE watermark_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users manage own watermarks" ON watermark_configs
  FOR ALL USING (auth.uid()::text = user_id);

-- ============================================================================
-- 5. Product Catalogs (IG Product Tagging)
-- ============================================================================

CREATE TABLE IF NOT EXISTS product_catalogs (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  ig_account_id UUID REFERENCES instagram_accounts(id) ON DELETE CASCADE NOT NULL,
  catalog_id TEXT NOT NULL,
  catalog_name TEXT,
  synced_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS product_tags (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  post_id TEXT REFERENCES posts(id) ON DELETE CASCADE NOT NULL,
  product_id TEXT NOT NULL,
  product_name TEXT,
  x_position FLOAT,
  y_position FLOAT
);

-- ============================================================================
-- 6. Shared Team Media Library (extend existing tables if they exist)
-- ============================================================================

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'media_assets' AND table_schema = 'public') THEN
    ALTER TABLE media_assets ADD COLUMN IF NOT EXISTS workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'media_folders' AND table_schema = 'public') THEN
    ALTER TABLE media_folders ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT false;
    ALTER TABLE media_folders ADD COLUMN IF NOT EXISTS workspace_id TEXT REFERENCES workspaces(id) ON DELETE CASCADE;
  END IF;
END $$;

-- ============================================================================
-- 7. Engagement Pods
-- ============================================================================

CREATE TABLE IF NOT EXISTS engagement_pods (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  name TEXT NOT NULL,
  description TEXT,
  owner_id TEXT REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  platform TEXT DEFAULT 'threads' CHECK (platform IN ('threads', 'instagram', 'both')),
  max_members INTEGER DEFAULT 10,
  rules JSONB DEFAULT '{}',
  invite_code TEXT UNIQUE DEFAULT upper(substr(gen_random_uuid()::text, 1, 8)),
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pod_members (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  pod_id TEXT REFERENCES engagement_pods(id) ON DELETE CASCADE NOT NULL,
  user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
  account_id TEXT NOT NULL,
  username TEXT,
  role TEXT DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  joined_at TIMESTAMPTZ DEFAULT now(),
  karma_score INTEGER DEFAULT 0,
  UNIQUE (pod_id, user_id)
);

CREATE TABLE IF NOT EXISTS pod_posts (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  pod_id TEXT REFERENCES engagement_pods(id) ON DELETE CASCADE NOT NULL,
  member_id TEXT REFERENCES pod_members(id) ON DELETE CASCADE NOT NULL,
  post_url TEXT NOT NULL,
  platform TEXT NOT NULL,
  posted_at TIMESTAMPTZ DEFAULT now(),
  engagement_deadline TIMESTAMPTZ,
  is_active BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS pod_engagements (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  pod_post_id TEXT REFERENCES pod_posts(id) ON DELETE CASCADE NOT NULL,
  member_id TEXT REFERENCES pod_members(id) ON DELETE CASCADE NOT NULL,
  engagement_type TEXT CHECK (engagement_type IN ('like', 'comment', 'repost', 'share')),
  verified BOOLEAN DEFAULT false,
  engaged_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (pod_post_id, member_id, engagement_type)
);

ALTER TABLE engagement_pods ENABLE ROW LEVEL SECURITY;
ALTER TABLE pod_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE pod_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE pod_engagements ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Pod members see pods" ON engagement_pods
  FOR SELECT USING (id IN (SELECT pod_id FROM pod_members WHERE user_id = auth.uid()::text));
CREATE POLICY "Owners manage pods" ON engagement_pods
  FOR ALL USING (owner_id = auth.uid()::text);

CREATE POLICY "Pod members see members" ON pod_members
  FOR SELECT USING (pod_id IN (SELECT pod_id FROM pod_members WHERE user_id = auth.uid()::text));
CREATE POLICY "Users manage own membership" ON pod_members
  FOR ALL USING (user_id = auth.uid()::text);

CREATE POLICY "Pod members see posts" ON pod_posts
  FOR SELECT USING (pod_id IN (SELECT pod_id FROM pod_members WHERE user_id = auth.uid()::text));
CREATE POLICY "Members submit posts" ON pod_posts
  FOR INSERT WITH CHECK (member_id IN (SELECT id FROM pod_members WHERE user_id = auth.uid()::text));

CREATE POLICY "Pod members see engagements" ON pod_engagements
  FOR SELECT USING (pod_post_id IN (
    SELECT pp.id FROM pod_posts pp
    JOIN pod_members pm ON pm.pod_id = pp.pod_id
    WHERE pm.user_id = auth.uid()::text
  ));
CREATE POLICY "Members record engagements" ON pod_engagements
  FOR INSERT WITH CHECK (member_id IN (SELECT id FROM pod_members WHERE user_id = auth.uid()::text));
