-- ============================================================
-- Thompson Sampling Bandit Variants + Strikethrough Pricing
-- Link Page Conversion 2026, Sections 7 & 9
-- ============================================================

-- 1. Link page A/B test variants with Thompson Sampling state
CREATE TABLE IF NOT EXISTS link_page_variants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id UUID NOT NULL REFERENCES link_pages(id) ON DELETE CASCADE,

  -- Variant identity
  variant_label TEXT NOT NULL,            -- "A", "B", "C"
  variant_type TEXT NOT NULL DEFAULT 'full',  -- "cta_text", "button_color", "layout", "full"
  config JSONB NOT NULL DEFAULT '{}',     -- Override config: cta_text, brand_color, bio_text, promo_text, link_order, max_links

  -- Thompson Sampling: Beta(alpha, beta) distribution
  -- On page view: beta++ (assume non-conversion)
  -- On click: alpha++, beta-- (convert failure to success)
  alpha INT NOT NULL DEFAULT 1,           -- successes + prior
  beta INT NOT NULL DEFAULT 1,            -- failures + prior

  -- Reporting metrics (mirrors alpha/beta but cleaner for dashboards)
  impressions INT NOT NULL DEFAULT 0,
  conversions INT NOT NULL DEFAULT 0,

  -- Three-level hierarchy: global → persona → account
  level TEXT NOT NULL DEFAULT 'global' CHECK (level IN ('global', 'persona', 'account')),
  group_id TEXT,                           -- persona level: references account_groups(id)
  account_id TEXT,                         -- account level: references accounts(id)

  -- Winner state
  is_active BOOLEAN NOT NULL DEFAULT true,
  is_winner BOOLEAN NOT NULL DEFAULT false,
  declared_at TIMESTAMPTZ,
  confidence DECIMAL(5,4),

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lpv_page_active ON link_page_variants(page_id) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_lpv_level ON link_page_variants(level, group_id, account_id);
CREATE INDEX IF NOT EXISTS idx_lpv_winner ON link_page_variants(page_id) WHERE is_winner = true;

-- RLS: public read (variants affect public page rendering), service-role write
ALTER TABLE link_page_variants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "link_page_variants_public_read"
  ON link_page_variants FOR SELECT
  USING (true);

CREATE POLICY "link_page_variants_service_insert"
  ON link_page_variants FOR INSERT
  WITH CHECK (true);

CREATE POLICY "link_page_variants_service_update"
  ON link_page_variants FOR UPDATE
  USING (true);

-- 2. Atomic RPCs for variant tracking (SECURITY DEFINER = bypass RLS)

-- Record a page view for a variant: beta++ (assume non-conversion), impressions++
CREATE OR REPLACE FUNCTION record_variant_impression(p_variant_id UUID)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE link_page_variants
  SET beta = beta + 1,
      impressions = impressions + 1,
      updated_at = now()
  WHERE id = p_variant_id AND is_active = true;
$$;

-- Record a click/conversion: alpha++ (success), beta-- (undo the failure), conversions++
CREATE OR REPLACE FUNCTION record_variant_click(p_variant_id UUID)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE link_page_variants
  SET alpha = alpha + 1,
      beta = GREATEST(beta - 1, 1),
      conversions = conversions + 1,
      updated_at = now()
  WHERE id = p_variant_id AND is_active = true;
$$;

-- 3. Add variant tracking to link_clicks
ALTER TABLE link_clicks ADD COLUMN IF NOT EXISTS variant_id UUID REFERENCES link_page_variants(id);

-- 4. Strikethrough pricing config on link items
-- JSONB: { original_price, sale_price, currency, period, pennies_per_day, discount_badge, show_strikethrough }
ALTER TABLE link_items ADD COLUMN IF NOT EXISTS pricing_config JSONB;

-- Index for pricing-enabled items
CREATE INDEX IF NOT EXISTS idx_link_items_pricing ON link_items(page_id) WHERE pricing_config IS NOT NULL;
