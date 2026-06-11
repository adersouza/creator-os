-- Add custom-domain support for smart links while preserving link-page domains.

BEGIN;

ALTER TABLE public.smart_links
  ADD COLUMN IF NOT EXISTS custom_domain TEXT,
  ADD COLUMN IF NOT EXISTS domain_verified BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS domain_verified_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_smart_links_custom_domain_unique
  ON public.smart_links(custom_domain)
  WHERE custom_domain IS NOT NULL;

ALTER TABLE public.domain_verifications
  ADD COLUMN IF NOT EXISTS smart_link_id UUID REFERENCES public.smart_links(id) ON DELETE CASCADE;

ALTER TABLE public.domain_verifications
  ALTER COLUMN page_id DROP NOT NULL;

ALTER TABLE public.domain_verifications
  DROP CONSTRAINT IF EXISTS domain_verifications_exactly_one_target;

ALTER TABLE public.domain_verifications
  ADD CONSTRAINT domain_verifications_exactly_one_target
  CHECK (
    ((page_id IS NOT NULL)::int + (smart_link_id IS NOT NULL)::int) = 1
  );

CREATE INDEX IF NOT EXISTS idx_domain_verifications_smart_link_id
  ON public.domain_verifications(smart_link_id)
  WHERE smart_link_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.smart_link_analytics(
  p_link_id uuid,
  p_since timestamp with time zone,
  p_user_id text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE SECURITY DEFINER
SET search_path = public
AS $function$
DECLARE
  v_result jsonb;
  v_interstitial_views int;
  v_destination_clicks int;
  v_direct_redirects int;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.smart_links
    WHERE id = p_link_id AND user_id = p_user_id
  ) THEN
    RAISE EXCEPTION 'Unauthorized: smart link not found or not owned by caller';
  END IF;

  SELECT COUNT(*)::int INTO v_interstitial_views
  FROM public.smart_link_clicks
  WHERE smart_link_id = p_link_id
    AND clicked_at >= p_since
    AND event_name = 'interstitial_view';

  SELECT COUNT(*)::int INTO v_destination_clicks
  FROM public.smart_link_clicks
  WHERE smart_link_id = p_link_id
    AND clicked_at >= p_since
    AND event_name = 'destination_click';

  SELECT COUNT(*)::int INTO v_direct_redirects
  FROM public.smart_link_clicks
  WHERE smart_link_id = p_link_id
    AND clicked_at >= p_since
    AND (event_name IS NULL OR event_name IN ('click', 'redirect'));

  SELECT jsonb_build_object(
    'clicks_by_day', COALESCE((
      SELECT jsonb_agg(row_to_json(t) ORDER BY t.day)
      FROM (
        SELECT (clicked_at AT TIME ZONE 'UTC')::date::text AS day, COUNT(*)::int AS count
        FROM public.smart_link_clicks
        WHERE smart_link_id = p_link_id
          AND clicked_at >= p_since
          AND (event_name IS NULL OR event_name IN ('click', 'redirect', 'destination_click'))
        GROUP BY 1
        ORDER BY 1
      ) t
    ), '[]'::jsonb),
    'by_platform', COALESCE((
      SELECT jsonb_agg(row_to_json(t))
      FROM (
        SELECT COALESCE(source_platform, 'unknown') AS name, COUNT(*)::int AS count
        FROM public.smart_link_clicks
        WHERE smart_link_id = p_link_id
          AND clicked_at >= p_since
          AND (event_name IS NULL OR event_name IN ('click', 'redirect', 'destination_click'))
        GROUP BY 1
        ORDER BY count DESC
      ) t
    ), '[]'::jsonb),
    'by_device', COALESCE((
      SELECT jsonb_agg(row_to_json(t))
      FROM (
        SELECT COALESCE(device_type, 'unknown') AS name, COUNT(*)::int AS count
        FROM public.smart_link_clicks
        WHERE smart_link_id = p_link_id
          AND clicked_at >= p_since
          AND (event_name IS NULL OR event_name IN ('click', 'redirect', 'destination_click'))
        GROUP BY 1
        ORDER BY count DESC
      ) t
    ), '[]'::jsonb),
    'by_country', COALESCE((
      SELECT jsonb_agg(row_to_json(t))
      FROM (
        SELECT COALESCE(country, 'Unknown') AS name, COUNT(*)::int AS count
        FROM public.smart_link_clicks
        WHERE smart_link_id = p_link_id
          AND clicked_at >= p_since
          AND (event_name IS NULL OR event_name IN ('click', 'redirect', 'destination_click'))
        GROUP BY 1
        ORDER BY count DESC
        LIMIT 10
      ) t
    ), '[]'::jsonb),
    'unique_visitors', (
      SELECT COUNT(DISTINCT fingerprint)::int
      FROM public.smart_link_clicks
      WHERE smart_link_id = p_link_id
        AND clicked_at >= p_since
        AND fingerprint IS NOT NULL
        AND (event_name IS NULL OR event_name IN ('click', 'redirect', 'destination_click'))
    ),
    'total_clicks', (
      SELECT COUNT(*)::int
      FROM public.smart_link_clicks
      WHERE smart_link_id = p_link_id
        AND clicked_at >= p_since
        AND (event_name IS NULL OR event_name IN ('click', 'redirect', 'destination_click'))
    ),
    'interstitial_views', v_interstitial_views,
    'destination_clicks', v_destination_clicks,
    'direct_redirects', v_direct_redirects,
    'dropoff_rate', CASE
      WHEN v_interstitial_views > 0
      THEN GREATEST(0, (v_interstitial_views - v_destination_clicks)::numeric / v_interstitial_views)
      ELSE 0
    END,
    'deep_link_attempts', (
      SELECT COUNT(*)::int
      FROM public.smart_link_clicks
      WHERE smart_link_id = p_link_id
        AND clicked_at >= p_since
        AND deep_link_attempted = true
        AND (event_name IS NULL OR event_name IN ('click', 'redirect', 'destination_click'))
    ),
    'conversions', COALESCE((
      SELECT jsonb_build_object(
        'count', COUNT(*)::int,
        'total_value', COALESCE(SUM(conversion_value), 0)
      )
      FROM public.smart_link_conversions
      WHERE smart_link_id = p_link_id AND converted_at >= p_since
    ), '{"count": 0, "total_value": 0}'::jsonb)
  ) INTO v_result;

  RETURN v_result;
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.smart_link_analytics(UUID, TIMESTAMPTZ, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.smart_link_analytics(UUID, TIMESTAMPTZ, TEXT) TO service_role;

COMMIT;
