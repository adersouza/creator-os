-- Smart Link Revenue Attribution
-- Adds post association + revenue estimation to smart_links,
-- conversion tracking table, and revenue summary RPC.

-- ============================================================================
-- 1. ALTER smart_links: add post association + revenue estimation columns
-- ============================================================================

ALTER TABLE smart_links
  ADD COLUMN IF NOT EXISTS post_id TEXT REFERENCES posts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS est_conversion_rate NUMERIC(5,4) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS est_conversion_value NUMERIC(10,2) DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_smart_links_post ON smart_links(post_id) WHERE post_id IS NOT NULL;

-- ============================================================================
-- 2. smart_link_conversions table
-- ============================================================================

CREATE TABLE IF NOT EXISTS smart_link_conversions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  smart_link_id UUID NOT NULL REFERENCES smart_links(id) ON DELETE CASCADE,
  click_id UUID REFERENCES smart_link_clicks(id) ON DELETE SET NULL,
  order_id VARCHAR(255) NOT NULL,
  conversion_value NUMERIC(10,2) NOT NULL DEFAULT 0,
  currency VARCHAR(3) NOT NULL DEFAULT 'USD',
  source VARCHAR(50) DEFAULT NULL,
  ip_address VARCHAR(45) DEFAULT NULL,
  converted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT uq_smart_link_conversions_order UNIQUE (smart_link_id, order_id)
);

CREATE INDEX IF NOT EXISTS idx_smart_link_conversions_link ON smart_link_conversions(smart_link_id);
CREATE INDEX IF NOT EXISTS idx_smart_link_conversions_time ON smart_link_conversions(converted_at);

-- ============================================================================
-- 3. RLS on smart_link_conversions
-- ============================================================================

ALTER TABLE smart_link_conversions ENABLE ROW LEVEL SECURITY;

-- Service role: full access
CREATE POLICY "service_role_smart_link_conversions"
  ON smart_link_conversions
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- Authenticated users: read own conversions (via smart_links join)
CREATE POLICY "users_read_own_conversions"
  ON smart_link_conversions
  FOR SELECT
  TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM smart_links sl
      WHERE sl.id = smart_link_conversions.smart_link_id
        AND sl.user_id = auth.uid()::text
    )
  );

-- ============================================================================
-- 4. RPC: get_smart_link_revenue_summary
-- ============================================================================

CREATE OR REPLACE FUNCTION get_smart_link_revenue_summary(
  p_user_id TEXT,
  p_days INT DEFAULT 30
)
RETURNS TABLE (
  total_clicks BIGINT,
  total_conversions BIGINT,
  total_actual_revenue NUMERIC,
  total_estimated_revenue NUMERIC,
  conversion_rate NUMERIC
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_since TIMESTAMPTZ := now() - (p_days || ' days')::INTERVAL;
BEGIN
  RETURN QUERY
  WITH user_links AS (
    SELECT sl.id, sl.click_count, sl.est_conversion_rate, sl.est_conversion_value
    FROM smart_links sl
    WHERE sl.user_id = p_user_id
      AND sl.is_active = true
  ),
  period_clicks AS (
    SELECT COUNT(*) AS cnt
    FROM smart_link_clicks c
    JOIN user_links ul ON ul.id = c.smart_link_id
    WHERE c.clicked_at >= v_since
  ),
  period_conversions AS (
    SELECT
      COUNT(*) AS cnt,
      COALESCE(SUM(cv.conversion_value), 0) AS revenue
    FROM smart_link_conversions cv
    JOIN user_links ul ON ul.id = cv.smart_link_id
    WHERE cv.converted_at >= v_since
  ),
  estimated AS (
    SELECT COALESCE(SUM(
      ul.click_count * COALESCE(ul.est_conversion_rate, 0) * COALESCE(ul.est_conversion_value, 0)
    ), 0) AS est_rev
    FROM user_links ul
  )
  SELECT
    pc.cnt AS total_clicks,
    pcv.cnt AS total_conversions,
    pcv.revenue AS total_actual_revenue,
    e.est_rev AS total_estimated_revenue,
    CASE WHEN pc.cnt > 0
      THEN ROUND((pcv.cnt::NUMERIC / pc.cnt::NUMERIC) * 100, 2)
      ELSE 0
    END AS conversion_rate
  FROM period_clicks pc, period_conversions pcv, estimated e;
END;
$$;
