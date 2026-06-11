-- Create RPC function to increment DM template use count
-- This fixes the broken increment logic in api/instagram/dm-templates.ts

CREATE OR REPLACE FUNCTION increment_dm_template_use(
  p_template_id uuid,
  p_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  -- Atomically increment use_count and update timestamp
  UPDATE ig_dm_templates
  SET
    use_count = COALESCE(use_count, 0) + 1,
    updated_at = now()
  WHERE
    id = p_template_id
    AND user_id = p_user_id;
END;
$$;

-- Grant execute permission to authenticated users
GRANT EXECUTE ON FUNCTION increment_dm_template_use(uuid, uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION increment_dm_template_use(uuid, uuid) TO service_role;

COMMENT ON FUNCTION increment_dm_template_use IS 'Atomically increments the use_count for a DM template. Used when a template is applied to a message.';
