-- Backfilled from DB migration history
CREATE OR REPLACE FUNCTION increment_ai_generations(
  p_workspace_id TEXT, p_count INT, p_today DATE, p_reset BOOLEAN DEFAULT FALSE
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  UPDATE auto_post_config SET
    ai_generations_today = CASE WHEN p_reset THEN p_count ELSE ai_generations_today + p_count END,
    ai_last_generation_date = p_today
  WHERE workspace_id = p_workspace_id;
END;
$$;
