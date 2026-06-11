-- Webhook p95 processing latency helper
-- Called by health-monitor checkWebhookLag to detect processing backlogs.
-- Returns the 95th-percentile latency in seconds between received_at and processed_at
-- for events processed within the given time window. Returns NULL if no data.

CREATE OR REPLACE FUNCTION webhook_p95_latency_seconds(tbl text, since timestamptz)
RETURNS numeric
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  result numeric;
BEGIN
  -- Only allow the two known webhook event tables to prevent SQL injection
  IF tbl NOT IN ('threads_webhook_events', 'ig_webhook_events') THEN
    RAISE EXCEPTION 'Invalid table name: %', tbl;
  END IF;

  IF tbl = 'threads_webhook_events' THEN
    SELECT ROUND(
      PERCENTILE_CONT(0.95) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (processed_at - received_at))
      )::numeric, 1
    )
    INTO result
    FROM threads_webhook_events
    WHERE processed = true
      AND processed_at IS NOT NULL
      AND received_at IS NOT NULL
      AND processed_at >= since;
  ELSE
    SELECT ROUND(
      PERCENTILE_CONT(0.95) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (processed_at - received_at))
      )::numeric, 1
    )
    INTO result
    FROM ig_webhook_events
    WHERE processed = true
      AND processed_at IS NOT NULL
      AND received_at IS NOT NULL
      AND processed_at >= since;
  END IF;

  RETURN result;
END;
$$;

-- Only the service role can call this (health-monitor uses service role key)
REVOKE ALL ON FUNCTION webhook_p95_latency_seconds(text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION webhook_p95_latency_seconds(text, timestamptz) TO service_role;
