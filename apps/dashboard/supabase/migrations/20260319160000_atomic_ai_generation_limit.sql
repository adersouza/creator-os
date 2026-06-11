-- Replace increment_ai_generations with an atomic reserve-and-cap version.
-- Returns the number of slots actually granted (0 to p_count).
-- Uses FOR UPDATE to prevent concurrent workers from overshooting the limit.
CREATE OR REPLACE FUNCTION increment_ai_generations(
  p_workspace_id TEXT,
  p_count INT,
  p_today DATE,
  p_reset BOOLEAN DEFAULT FALSE,
  p_limit INT DEFAULT 0
) RETURNS INT LANGUAGE plpgsql SECURITY DEFINER AS $$
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
