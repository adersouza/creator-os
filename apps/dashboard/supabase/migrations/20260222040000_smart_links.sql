-- Smart Links engine: tables, RPC, RLS, indexes

-- ══════════════════════════════════════════════
-- 1. smart_links
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS smart_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id text NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  code varchar(20) UNIQUE NOT NULL,
  target_url text NOT NULL,
  title varchar(255),
  -- Deep link overrides (optional)
  ig_deep_link text,
  threads_deep_link text,
  -- Conditional redirects
  ig_redirect_url text,
  threads_redirect_url text,
  mobile_redirect_url text,
  -- Settings
  is_active boolean DEFAULT true,
  enable_deep_links boolean DEFAULT true,
  -- Analytics
  click_count integer DEFAULT 0,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_smart_links_code ON smart_links(code);
CREATE INDEX IF NOT EXISTS idx_smart_links_user ON smart_links(user_id);

ALTER TABLE smart_links ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own smart_links"
  ON smart_links FOR ALL TO authenticated
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Service role smart_links"
  ON smart_links FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ══════════════════════════════════════════════
-- 2. smart_link_clicks
-- ══════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS smart_link_clicks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  smart_link_id uuid NOT NULL REFERENCES smart_links(id) ON DELETE CASCADE,
  source_platform varchar(50),
  device_type varchar(20),
  country varchar(10),
  referrer text,
  user_agent text,
  fingerprint varchar(16),
  utm_source varchar(100),
  utm_medium varchar(100),
  utm_campaign varchar(100),
  deep_link_attempted boolean DEFAULT false,
  clicked_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_smart_link_clicks_link ON smart_link_clicks(smart_link_id);
CREATE INDEX IF NOT EXISTS idx_smart_link_clicks_platform ON smart_link_clicks(source_platform);
CREATE INDEX IF NOT EXISTS idx_smart_link_clicks_time ON smart_link_clicks(clicked_at);

ALTER TABLE smart_link_clicks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role smart_link_clicks"
  ON smart_link_clicks FOR ALL TO service_role
  USING (true) WITH CHECK (true);

-- ══════════════════════════════════════════════
-- 3. Atomic click counter RPC
-- ══════════════════════════════════════════════
CREATE OR REPLACE FUNCTION increment_smart_link_click(p_link_id uuid)
RETURNS void AS $$
  UPDATE smart_links
  SET click_count = click_count + 1, updated_at = now()
  WHERE id = p_link_id;
$$ LANGUAGE sql;
