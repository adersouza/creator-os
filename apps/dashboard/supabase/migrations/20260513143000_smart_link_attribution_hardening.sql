-- Harden Smart Link attribution against forged conversions and public metric gaming.

BEGIN;

ALTER TABLE public.smart_links
  ADD COLUMN IF NOT EXISTS webhook_secret TEXT;

UPDATE public.smart_links
SET webhook_secret = replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', '')
WHERE webhook_secret IS NULL OR length(webhook_secret) < 32;

ALTER TABLE public.smart_links
  ALTER COLUMN webhook_secret SET DEFAULT (replace(gen_random_uuid()::text, '-', '') || replace(gen_random_uuid()::text, '-', ''));

ALTER TABLE public.smart_links
  DROP CONSTRAINT IF EXISTS smart_links_webhook_secret_required;

ALTER TABLE public.smart_links
  ADD CONSTRAINT smart_links_webhook_secret_required
  CHECK (webhook_secret IS NOT NULL AND length(webhook_secret) >= 32);

-- Conversion postbacks dedupe per smart link/order id and need bounded values.
CREATE UNIQUE INDEX IF NOT EXISTS idx_smart_link_conversions_link_order
  ON public.smart_link_conversions(smart_link_id, order_id)
  WHERE order_id IS NOT NULL;

ALTER TABLE public.smart_link_conversions
  DROP CONSTRAINT IF EXISTS smart_link_conversions_value_bounds;

ALTER TABLE public.smart_link_conversions
  ADD CONSTRAINT smart_link_conversions_value_bounds
  CHECK (conversion_value >= 0 AND conversion_value <= 1000000);

-- Variant RPCs are now only called by service-role API routes after page/link
-- ownership validation. Public anon/authenticated callers can no longer skew
-- Thompson sampling directly with a variant id.
REVOKE EXECUTE ON FUNCTION public.record_variant_impression(UUID) FROM anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.record_variant_click(UUID) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_variant_impression(UUID) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_variant_click(UUID) TO service_role;

-- Service-role analytics RPC with explicit owner guard. The public API verifies
-- ownership before calling this function and passes the authenticated user id.
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
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.smart_links
    WHERE id = p_link_id AND user_id = p_user_id
  ) THEN
    RAISE EXCEPTION 'Unauthorized: smart link not found or not owned by caller';
  END IF;

  SELECT jsonb_build_object(
    'clicks_by_day', COALESCE((
      SELECT jsonb_agg(row_to_json(t) ORDER BY t.day)
      FROM (
        SELECT (clicked_at AT TIME ZONE 'UTC')::date::text AS day, COUNT(*)::int AS count
        FROM public.smart_link_clicks
        WHERE smart_link_id = p_link_id
          AND clicked_at >= p_since
          AND (event_name IS NULL OR event_name IN ('click', 'redirect'))
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
          AND (event_name IS NULL OR event_name IN ('click', 'redirect'))
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
          AND (event_name IS NULL OR event_name IN ('click', 'redirect'))
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
          AND (event_name IS NULL OR event_name IN ('click', 'redirect'))
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
        AND (event_name IS NULL OR event_name IN ('click', 'redirect'))
    ),
    'total_clicks', (
      SELECT COUNT(*)::int
      FROM public.smart_link_clicks
      WHERE smart_link_id = p_link_id
        AND clicked_at >= p_since
        AND (event_name IS NULL OR event_name IN ('click', 'redirect'))
    ),
    'deep_link_attempts', (
      SELECT COUNT(*)::int
      FROM public.smart_link_clicks
      WHERE smart_link_id = p_link_id
        AND clicked_at >= p_since
        AND deep_link_attempted = true
        AND (event_name IS NULL OR event_name IN ('click', 'redirect'))
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
