-- Backfilled from DB migration history
CREATE OR REPLACE FUNCTION assign_account_to_group(
  p_account_id TEXT,
  p_target_group_id TEXT,
  p_user_id TEXT
) RETURNS void AS $$
BEGIN
  UPDATE account_groups
  SET account_ids = array_remove(account_ids, p_account_id),
      updated_at = NOW()
  WHERE user_id = p_user_id
    AND p_account_id = ANY(account_ids);

  IF p_target_group_id IS NOT NULL THEN
    UPDATE account_groups
    SET account_ids = array_append(account_ids, p_account_id),
        updated_at = NOW()
    WHERE id = p_target_group_id
      AND user_id = p_user_id;
  END IF;

  UPDATE accounts
  SET group_id = p_target_group_id,
      updated_at = NOW()
  WHERE id = p_account_id
    AND user_id = p_user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
   SET search_path = public;
