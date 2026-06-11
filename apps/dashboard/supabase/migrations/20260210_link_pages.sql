-- Link-in-bio pages (source of truth in Supabase)
CREATE TABLE IF NOT EXISTS link_pages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT REFERENCES profiles(id) ON DELETE CASCADE,
  slug TEXT UNIQUE NOT NULL,
  title TEXT,
  bio TEXT,
  avatar_url TEXT,
  background_color TEXT DEFAULT '#0a0a0b',
  brand_color TEXT DEFAULT '#ff6b9d',
  show_online_badge BOOLEAN DEFAULT true,
  promo_text TEXT,
  is_published BOOLEAN DEFAULT true,
  view_count INT DEFAULT 0,
  enable_deeplink_escape BOOLEAN DEFAULT true,
  default_destination TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Links on the page
CREATE TABLE IF NOT EXISTS link_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id UUID REFERENCES link_pages(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  icon TEXT,
  thumbnail_url TEXT,
  position INT NOT NULL,
  is_visible BOOLEAN DEFAULT true,
  is_primary BOOLEAN DEFAULT false,
  click_count INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Click analytics
CREATE TABLE IF NOT EXISTS link_clicks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  link_id UUID REFERENCES link_items(id) ON DELETE SET NULL,
  page_id UUID REFERENCES link_pages(id) ON DELETE CASCADE,
  is_crawler BOOLEAN DEFAULT false,
  referrer TEXT,
  user_agent TEXT,
  country TEXT,
  device_type TEXT,
  source_app TEXT,
  clicked_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_link_pages_slug ON link_pages(slug);
CREATE INDEX IF NOT EXISTS idx_link_pages_user ON link_pages(user_id);
CREATE INDEX IF NOT EXISTS idx_link_items_page ON link_items(page_id, position);
CREATE INDEX IF NOT EXISTS idx_link_clicks_link ON link_clicks(link_id, clicked_at DESC);
CREATE INDEX IF NOT EXISTS idx_link_clicks_page ON link_clicks(page_id, clicked_at DESC);
CREATE INDEX IF NOT EXISTS idx_link_clicks_source ON link_clicks(source_app, clicked_at DESC);

-- RLS
ALTER TABLE link_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE link_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE link_clicks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own pages" ON link_pages
  FOR ALL USING (auth.uid()::text = user_id);

CREATE POLICY "Users can manage their own links" ON link_items
  FOR ALL USING (
    EXISTS (SELECT 1 FROM link_pages WHERE link_pages.id = page_id AND link_pages.user_id = auth.uid()::text)
  );

CREATE POLICY "Anyone can insert clicks" ON link_clicks
  FOR INSERT WITH CHECK (true);

CREATE POLICY "Users can view their own clicks" ON link_clicks
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM link_pages WHERE link_pages.id = page_id AND link_pages.user_id = auth.uid()::text)
  );
