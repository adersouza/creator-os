-- Publishing Pipeline Audit: Atomic increment RPC for posts_today
-- Replaces non-atomic JS read-modify-write with a single SQL UPDATE ... RETURNING

CREATE OR REPLACE FUNCTION increment_group_posts_today(
  p_workspace_id TEXT,
  p_group_id TEXT,
  p_column TEXT DEFAULT 'posts_today'
) RETURNS INTEGER AS $$
DECLARE v_new INT;
BEGIN
  IF p_column = 'ig_posts_today' THEN
    UPDATE auto_post_group_state
      SET ig_posts_today = COALESCE(ig_posts_today, 0) + 1, updated_at = NOW()
      WHERE workspace_id = p_workspace_id AND group_id = p_group_id
      RETURNING ig_posts_today INTO v_new;
  ELSE
    UPDATE auto_post_group_state
      SET posts_today = COALESCE(posts_today, 0) + 1, updated_at = NOW()
      WHERE workspace_id = p_workspace_id AND group_id = p_group_id
      RETURNING posts_today INTO v_new;
  END IF;
  RETURN COALESCE(v_new, 0);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;
