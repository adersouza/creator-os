-- Atomic account-to-group assignment
-- Eliminates fetch-modify-write race condition in multi-user workspaces
-- by performing array_remove + array_append in a single transaction.

CREATE OR REPLACE FUNCTION assign_account_to_group(
  p_account_id TEXT,
  p_target_group_id TEXT,  -- NULL to just unassign
  p_user_id TEXT
) RETURNS void AS $$
BEGIN
  -- Remove from ALL groups that contain this account (atomic, no client-side read)
  UPDATE account_groups
  SET account_ids = array_remove(account_ids, p_account_id),
      updated_at = NOW()
  WHERE user_id = p_user_id
    AND p_account_id = ANY(account_ids);

  -- Add to target group (if specified)
  IF p_target_group_id IS NOT NULL THEN
    UPDATE account_groups
    SET account_ids = array_append(account_ids, p_account_id),
        updated_at = NOW()
    WHERE id = p_target_group_id
      AND user_id = p_user_id;
  END IF;

  -- Update denormalized group_id on accounts table
  UPDATE accounts
  SET group_id = p_target_group_id,
      updated_at = NOW()
  WHERE id = p_account_id
    AND user_id = p_user_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
   SET search_path = public;
