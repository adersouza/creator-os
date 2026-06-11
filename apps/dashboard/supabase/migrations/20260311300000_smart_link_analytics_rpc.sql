-- Server-side aggregation for smart link analytics.
-- Replaces 7 parallel client-side queries (each capped at 10K rows)
-- with a single RPC that does GROUP BY in Postgres — no row limit.

CREATE OR REPLACE FUNCTION smart_link_analytics(
  p_link_id UUID,
  p_since TIMESTAMPTZ
) RETURNS JSONB AS $$
DECLARE
  v_result JSONB;
BEGIN
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
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

GRANT EXECUTE ON FUNCTION smart_link_analytics(UUID, TIMESTAMPTZ) TO service_role;
