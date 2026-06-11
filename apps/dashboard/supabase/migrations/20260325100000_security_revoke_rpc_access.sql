-- ============================================================================
-- Wave 1: Security Audit Remediation — Lock Down SECURITY DEFINER RPC Functions
-- ============================================================================
-- Date: 2026-03-25
-- Findings addressed: C1, C2, H1, H2, H4 (partial — RPC layer only)
--
-- Problem: Multiple SECURITY DEFINER functions were callable by PUBLIC/anon/
-- authenticated via PostgREST RPC. These functions bypass RLS entirely,
-- allowing IDOR (C1, C2), metric manipulation (H1), and count inflation (H2).
--
-- Fix strategy:
--   1a. REVOKE EXECUTE FROM PUBLIC, anon, authenticated on all vulnerable functions
--   1b. Rewrite get_aggregated_analytics with auth.uid() guard + SET search_path
--   1c. Rewrite smart_link_analytics with ownership check
--   1d. Restrict increment_dm_template_use to service_role only
--   1e. Add SET search_path = public where still missing
--
-- All REVOKE/GRANT statements are idempotent (no-op if already in desired state).
-- CREATE OR REPLACE preserves existing function behavior while adding guards.
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1a. REVOKE EXECUTE FROM PUBLIC on all vulnerable SECURITY DEFINER functions
-- ============================================================================

-- C1: smart_link_analytics(UUID, TIMESTAMPTZ)
REVOKE EXECUTE ON FUNCTION public.smart_link_analytics(UUID, TIMESTAMPTZ) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.smart_link_analytics(UUID, TIMESTAMPTZ) FROM anon;
REVOKE EXECUTE ON FUNCTION public.smart_link_analytics(UUID, TIMESTAMPTZ) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.smart_link_analytics(UUID, TIMESTAMPTZ) TO service_role;

-- C2: get_aggregated_analytics(TEXT, INTEGER, TEXT, TEXT[])
REVOKE EXECUTE ON FUNCTION public.get_aggregated_analytics(TEXT, INTEGER, TEXT, TEXT[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_aggregated_analytics(TEXT, INTEGER, TEXT, TEXT[]) FROM anon;
REVOKE EXECUTE ON FUNCTION public.get_aggregated_analytics(TEXT, INTEGER, TEXT, TEXT[]) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.get_aggregated_analytics(TEXT, INTEGER, TEXT, TEXT[]) TO service_role;

-- H1: update_post_metrics_if_newer(TEXT, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT)
REVOKE EXECUTE ON FUNCTION public.update_post_metrics_if_newer(TEXT, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.update_post_metrics_if_newer(TEXT, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT) FROM anon;
REVOKE EXECUTE ON FUNCTION public.update_post_metrics_if_newer(TEXT, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.update_post_metrics_if_newer(TEXT, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT) TO service_role;

-- H1: update_ig_post_metrics_if_newer(TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT, DOUBLE PRECISION, BIGINT, BIGINT, BIGINT, INTEGER, BIGINT)
REVOKE EXECUTE ON FUNCTION public.update_ig_post_metrics_if_newer(TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT, DOUBLE PRECISION, BIGINT, BIGINT, BIGINT, INTEGER, BIGINT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.update_ig_post_metrics_if_newer(TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT, DOUBLE PRECISION, BIGINT, BIGINT, BIGINT, INTEGER, BIGINT) FROM anon;
REVOKE EXECUTE ON FUNCTION public.update_ig_post_metrics_if_newer(TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT, DOUBLE PRECISION, BIGINT, BIGINT, BIGINT, INTEGER, BIGINT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.update_ig_post_metrics_if_newer(TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, DOUBLE PRECISION, BIGINT, DOUBLE PRECISION, BIGINT, BIGINT, BIGINT, INTEGER, BIGINT) TO service_role;

-- H2: increment_view_count(UUID)
REVOKE EXECUTE ON FUNCTION public.increment_view_count(UUID) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.increment_view_count(UUID) FROM anon;
REVOKE EXECUTE ON FUNCTION public.increment_view_count(UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.increment_view_count(UUID) TO service_role;

-- H2: increment_link_click(UUID)
REVOKE EXECUTE ON FUNCTION public.increment_link_click(UUID) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.increment_link_click(UUID) FROM anon;
REVOKE EXECUTE ON FUNCTION public.increment_link_click(UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.increment_link_click(UUID) TO service_role;

-- increment_ai_generations — two overloads exist:
-- Overload 1: 4 params (original, from 20260307200914)
REVOKE EXECUTE ON FUNCTION public.increment_ai_generations(TEXT, INT, DATE, BOOLEAN) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.increment_ai_generations(TEXT, INT, DATE, BOOLEAN) FROM anon;
REVOKE EXECUTE ON FUNCTION public.increment_ai_generations(TEXT, INT, DATE, BOOLEAN) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.increment_ai_generations(TEXT, INT, DATE, BOOLEAN) TO service_role;

-- Overload 2: 5 params (atomic version, from 20260319160000)
REVOKE EXECUTE ON FUNCTION public.increment_ai_generations(TEXT, INT, DATE, BOOLEAN, INT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.increment_ai_generations(TEXT, INT, DATE, BOOLEAN, INT) FROM anon;
REVOKE EXECUTE ON FUNCTION public.increment_ai_generations(TEXT, INT, DATE, BOOLEAN, INT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.increment_ai_generations(TEXT, INT, DATE, BOOLEAN, INT) TO service_role;

-- increment_referral_uses — only TEXT overload exists in production
REVOKE EXECUTE ON FUNCTION public.increment_referral_uses(TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.increment_referral_uses(TEXT) FROM anon;
REVOKE EXECUTE ON FUNCTION public.increment_referral_uses(TEXT) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.increment_referral_uses(TEXT) TO service_role;

-- 1d. increment_dm_template_use(UUID, UUID) — was granted to authenticated, restrict to service_role
REVOKE EXECUTE ON FUNCTION public.increment_dm_template_use(UUID, UUID) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.increment_dm_template_use(UUID, UUID) FROM anon;
REVOKE EXECUTE ON FUNCTION public.increment_dm_template_use(UUID, UUID) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.increment_dm_template_use(UUID, UUID) TO service_role;


-- ============================================================================
-- 1b. Rewrite get_aggregated_analytics with auth guard + SET search_path
-- ============================================================================
-- C2 fix: validate p_user_id matches auth.uid() to prevent IDOR.
-- Also adds SET search_path = public (was missing).
-- NOTE: We keep the p_user_id parameter for signature compatibility but
-- enforce it must match the caller's auth.uid().

CREATE OR REPLACE FUNCTION get_aggregated_analytics(
  p_user_id TEXT, p_days INTEGER DEFAULT 90, p_platform TEXT DEFAULT 'threads', p_account_ids TEXT[] DEFAULT NULL
) RETURNS TABLE (
  date DATE, followers_count BIGINT, total_views BIGINT, total_likes BIGINT, total_replies BIGINT,
  total_reposts BIGINT, total_quotes BIGINT, total_shares BIGINT, total_clicks BIGINT, engagement_rate NUMERIC
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- Security guard: caller must own the data they are requesting
  IF auth.uid()::text != p_user_id THEN
    RAISE EXCEPTION 'Unauthorized';
  END IF;

  IF p_platform = 'instagram' THEN
    RETURN QUERY SELECT aa.date,
      SUM(COALESCE(aa.followers_count,0))::BIGINT, SUM(COALESCE(aa.total_views,0))::BIGINT,
      SUM(COALESCE(aa.total_likes,0))::BIGINT, SUM(COALESCE(aa.total_replies,0))::BIGINT,
      SUM(COALESCE(aa.total_reposts,0))::BIGINT, SUM(COALESCE(aa.total_quotes,0))::BIGINT,
      SUM(COALESCE(aa.total_shares,0))::BIGINT, SUM(COALESCE(aa.total_clicks,0))::BIGINT,
      CASE WHEN SUM(COALESCE(aa.total_views,0)) > 0 THEN
        (SUM(COALESCE(aa.total_likes,0))+SUM(COALESCE(aa.total_replies,0))+SUM(COALESCE(aa.total_reposts,0))+SUM(COALESCE(aa.total_shares,0)))::NUMERIC / SUM(COALESCE(aa.total_views,0))
        ELSE 0 END
    FROM account_analytics aa JOIN instagram_accounts ia ON ia.id::text = aa.account_id AND ia.user_id = p_user_id
    WHERE aa.date >= CURRENT_DATE - p_days AND (p_account_ids IS NULL OR aa.account_id = ANY(p_account_ids))
    GROUP BY aa.date ORDER BY aa.date ASC;
  ELSE
    RETURN QUERY SELECT aa.date,
      SUM(COALESCE(aa.followers_count,0))::BIGINT, SUM(COALESCE(aa.total_views,0))::BIGINT,
      SUM(COALESCE(aa.total_likes,0))::BIGINT, SUM(COALESCE(aa.total_replies,0))::BIGINT,
      SUM(COALESCE(aa.total_reposts,0))::BIGINT, SUM(COALESCE(aa.total_quotes,0))::BIGINT,
      SUM(COALESCE(aa.total_shares,0))::BIGINT, SUM(COALESCE(aa.total_clicks,0))::BIGINT,
      CASE WHEN SUM(COALESCE(aa.total_views,0)) > 0 THEN
        (SUM(COALESCE(aa.total_likes,0))+SUM(COALESCE(aa.total_replies,0))+SUM(COALESCE(aa.total_reposts,0))+SUM(COALESCE(aa.total_shares,0)))::NUMERIC / SUM(COALESCE(aa.total_views,0))
        ELSE 0 END
    FROM account_analytics aa JOIN accounts a ON a.id = aa.account_id AND a.user_id = p_user_id
    WHERE aa.date >= CURRENT_DATE - p_days AND (p_account_ids IS NULL OR aa.account_id = ANY(p_account_ids))
    GROUP BY aa.date ORDER BY aa.date ASC;
  END IF;
END;
$$;


-- ============================================================================
-- 1c. Rewrite smart_link_analytics with ownership check
-- ============================================================================
-- C1 fix: verify caller owns the smart link before returning analytics.
-- search_path was already set in 20260318100000 — preserved here.

CREATE OR REPLACE FUNCTION public.smart_link_analytics(
  p_link_id uuid,
  p_since timestamp with time zone
)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path = public
AS $function$
DECLARE
  v_result JSONB;
BEGIN
  -- Security guard: caller must own the smart link
  IF NOT EXISTS (
    SELECT 1 FROM smart_links WHERE id = p_link_id AND user_id = auth.uid()::text
  ) THEN
    RAISE EXCEPTION 'Unauthorized: smart link not found or not owned by caller';
  END IF;

  SELECT jsonb_build_object(
    'clicks_by_day', COALESCE((
      SELECT jsonb_agg(row_to_json(t) ORDER BY t.day)
      FROM (
        SELECT (clicked_at AT TIME ZONE 'UTC')::date::text AS day, COUNT(*)::int AS count
        FROM smart_link_clicks
        WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        GROUP BY 1
        ORDER BY 1
      ) t
    ), '[]'::jsonb),
    'by_platform', COALESCE((
      SELECT jsonb_agg(row_to_json(t))
      FROM (
        SELECT COALESCE(source_platform, 'unknown') AS name, COUNT(*)::int AS count
        FROM smart_link_clicks
        WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        GROUP BY 1
        ORDER BY count DESC
      ) t
    ), '[]'::jsonb),
    'by_device', COALESCE((
      SELECT jsonb_agg(row_to_json(t))
      FROM (
        SELECT COALESCE(device_type, 'unknown') AS name, COUNT(*)::int AS count
        FROM smart_link_clicks
        WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        GROUP BY 1
        ORDER BY count DESC
      ) t
    ), '[]'::jsonb),
    'by_country', COALESCE((
      SELECT jsonb_agg(row_to_json(t))
      FROM (
        SELECT COALESCE(country, 'Unknown') AS name, COUNT(*)::int AS count
        FROM smart_link_clicks
        WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        GROUP BY 1
        ORDER BY count DESC
        LIMIT 10
      ) t
    ), '[]'::jsonb),
    'unique_visitors', (
      SELECT COUNT(DISTINCT fingerprint)::int
      FROM smart_link_clicks
      WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        AND fingerprint IS NOT NULL
    ),
    'total_clicks', (
      SELECT COUNT(*)::int
      FROM smart_link_clicks
      WHERE smart_link_id = p_link_id AND clicked_at >= p_since
    ),
    'deep_link_attempts', (
      SELECT COUNT(*)::int
      FROM smart_link_clicks
      WHERE smart_link_id = p_link_id AND clicked_at >= p_since
        AND deep_link_attempted = true
    ),
    'conversions', COALESCE((
      SELECT jsonb_build_object(
        'count', COUNT(*)::int,
        'total_value', COALESCE(SUM(conversion_value), 0)
      )
      FROM smart_link_conversions
      WHERE smart_link_id = p_link_id AND converted_at >= p_since
    ), '{"count": 0, "total_value": 0}'::jsonb)
  ) INTO v_result;

  RETURN v_result;
END;
$function$;


-- ============================================================================
-- 1e. Add SET search_path = public where still missing
-- ============================================================================

-- increment_view_count — missing search_path (from 20260219050000)
CREATE OR REPLACE FUNCTION public.increment_view_count(p_page_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE link_pages
  SET view_count = COALESCE(view_count, 0) + 1
  WHERE id = p_page_id;
END;
$$;

-- increment_link_click — missing search_path (from 20260214000002)
CREATE OR REPLACE FUNCTION public.increment_link_click(p_link_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE link_items
  SET click_count = click_count + 1
  WHERE id = p_link_id;
END;
$$;

-- increment_ai_generations (5-param atomic version) — missing search_path (from 20260319160000)
CREATE OR REPLACE FUNCTION public.increment_ai_generations(
  p_workspace_id TEXT,
  p_count INT,
  p_today DATE,
  p_reset BOOLEAN DEFAULT FALSE,
  p_limit INT DEFAULT 0
) RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_current INT;
  v_allowed INT;
BEGIN
  -- Lock the row to prevent concurrent reads
  SELECT COALESCE(ai_generations_today, 0), ai_last_generation_date
  INTO v_current
  FROM auto_post_config
  WHERE workspace_id = p_workspace_id
  FOR UPDATE;

  -- Reset counter on new day
  IF p_reset OR (SELECT ai_last_generation_date FROM auto_post_config WHERE workspace_id = p_workspace_id) IS DISTINCT FROM p_today THEN
    v_current := 0;
  END IF;

  -- Cap at limit if provided
  IF p_limit > 0 THEN
    v_allowed := LEAST(p_count, GREATEST(p_limit - v_current, 0));
  ELSE
    v_allowed := p_count;
  END IF;

  UPDATE auto_post_config SET
    ai_generations_today = v_current + v_allowed,
    ai_last_generation_date = p_today
  WHERE workspace_id = p_workspace_id;

  RETURN v_allowed;
END;
$$;

-- increment_dm_template_use — missing search_path (from 20260206000004)
CREATE OR REPLACE FUNCTION public.increment_dm_template_use(
  p_template_id UUID,
  p_user_id UUID
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE ig_dm_templates
  SET
    use_count = COALESCE(use_count, 0) + 1,
    updated_at = now()
  WHERE
    id = p_template_id
    AND user_id = p_user_id;
END;
$$;

COMMIT;
