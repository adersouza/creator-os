-- Content repurposing tracking
CREATE TABLE IF NOT EXISTS content_repurposing (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE,
  source_post_id TEXT REFERENCES posts(id) ON DELETE CASCADE,
  target_format TEXT NOT NULL, -- 'threads', 'instagram_caption', 'carousel', 'story', 'reel_script'
  target_post_id TEXT REFERENCES posts(id) ON DELETE SET NULL,
  adapted_content TEXT NOT NULL,
  status TEXT DEFAULT 'draft', -- 'draft', 'scheduled', 'published'
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_repurposing_source ON content_repurposing(source_post_id);
CREATE INDEX IF NOT EXISTS idx_repurposing_user ON content_repurposing(user_id);

-- RLS
ALTER TABLE content_repurposing ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own repurposed content" ON content_repurposing
  FOR ALL USING (auth.uid()::text = user_id);
