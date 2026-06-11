-- Influencer Collaboration Manager
-- Track partnerships, measure ROI, manage outreach pipeline

CREATE TABLE IF NOT EXISTS influencer_collabs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  workspace_id TEXT,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  partner_handle TEXT NOT NULL,
  partner_platform TEXT NOT NULL DEFAULT 'instagram',
  partner_avatar_url TEXT,
  partner_follower_count INTEGER,
  collab_type TEXT NOT NULL DEFAULT 'post',
  status TEXT NOT NULL DEFAULT 'contacted',
  cost_cents INTEGER DEFAULT 0,
  cost_type TEXT DEFAULT 'flat',
  revenue_share_pct NUMERIC,
  notes TEXT,
  outreach_template TEXT,
  start_date DATE,
  end_date DATE,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_influencer_collabs_workspace ON influencer_collabs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_influencer_collabs_user ON influencer_collabs(user_id);
CREATE INDEX IF NOT EXISTS idx_influencer_collabs_status ON influencer_collabs(status);

ALTER TABLE influencer_collabs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users manage own collabs" ON influencer_collabs
  FOR ALL USING (auth.uid() = user_id);

-- Link table: which posts are part of which collab
CREATE TABLE IF NOT EXISTS influencer_collab_posts (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  collab_id UUID NOT NULL REFERENCES influencer_collabs(id) ON DELETE CASCADE,
  post_id TEXT NOT NULL,
  is_partner_post BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(collab_id, post_id)
);

ALTER TABLE influencer_collab_posts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users manage own collab posts" ON influencer_collab_posts
  FOR ALL USING (
    EXISTS (SELECT 1 FROM influencer_collabs ic WHERE ic.id = collab_id AND ic.user_id = auth.uid())
  );
