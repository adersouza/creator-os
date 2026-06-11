-- Atomic referral code usage increment.
-- Prevents TOCTOU race: concurrent apply-code requests could exceed max_uses
-- because the check (uses < max_uses) and the increment were separate operations.
--
-- This function does SELECT ... FOR UPDATE + conditional increment in one step.
-- Returns TRUE if incremented, FALSE if at limit.

CREATE OR REPLACE FUNCTION increment_referral_uses(
  p_code_id UUID,
  p_max_limit INTEGER
) RETURNS BOOLEAN AS $$
DECLARE
  v_uses INTEGER;
BEGIN
  -- Lock the row to prevent concurrent increments
  SELECT uses INTO v_uses
    FROM referral_codes
    WHERE id = p_code_id
    FOR UPDATE;

  IF NOT FOUND THEN
    RETURN FALSE;
  END IF;

  -- Check limit (0 = unlimited)
  IF p_max_limit > 0 AND v_uses >= p_max_limit THEN
    RETURN FALSE;
  END IF;

  UPDATE referral_codes
    SET uses = v_uses + 1
    WHERE id = p_code_id;

  RETURN TRUE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION increment_referral_uses(UUID, INTEGER) TO service_role;
