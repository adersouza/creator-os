-- Platform Parity: online followers, carousel insights, tagged media tracking

-- 1. Online followers JSONB on account_analytics
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_online_followers JSONB;

-- 2. Carousel per-item insights
CREATE TABLE IF NOT EXISTS ig_carousel_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  child_media_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  media_type TEXT,
  media_url TEXT,
  impressions INTEGER DEFAULT 0,
  reach INTEGER DEFAULT 0,
  likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  shares INTEGER DEFAULT 0,
  saved INTEGER DEFAULT 0,
  fetched_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(post_id, child_media_id)
);
CREATE INDEX IF NOT EXISTS idx_carousel_insights_post ON ig_carousel_insights(post_id);
ALTER TABLE ig_carousel_insights ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own carousel insights" ON ig_carousel_insights FOR ALL
  USING (EXISTS (SELECT 1 FROM posts WHERE posts.id = ig_carousel_insights.post_id AND posts.user_id = (SELECT auth.uid())::text));

-- 3. Tagged media count tracking
ALTER TABLE account_analytics ADD COLUMN IF NOT EXISTS ig_tagged_media_count INTEGER DEFAULT 0;
