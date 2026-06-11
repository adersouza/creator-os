-- Atomic beta seat claim.
-- Prevents concurrent claim requests from oversubscribing the fixed beta cap.
-- Uses an advisory transaction lock to serialize the cap check + profile update.

CREATE OR REPLACE FUNCTION claim_beta_spot(
  p_user_id TEXT,
  p_total_spots INTEGER DEFAULT 50
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_is_beta BOOLEAN;
  v_spots_left INTEGER;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('claim_beta_spot_v1', 0));

  SELECT is_beta_user
  INTO v_is_beta
  FROM profiles
  WHERE id = p_user_id
  FOR UPDATE;

  IF NOT FOUND THEN
    RETURN jsonb_build_object(
      'ok', false,
      'reason', 'profile_not_found'
    );
  END IF;

  SELECT GREATEST(p_total_spots - COUNT(*), 0)
  INTO v_spots_left
  FROM profiles
  WHERE is_beta_user = true;

  IF COALESCE(v_is_beta, false) THEN
    RETURN jsonb_build_object(
      'ok', true,
      'claimed', false,
      'already_beta', true,
      'spots_left', v_spots_left
    );
  END IF;

  IF v_spots_left <= 0 THEN
    RETURN jsonb_build_object(
      'ok', false,
      'reason', 'sold_out',
      'spots_left', 0
    );
  END IF;

  UPDATE profiles
  SET
    is_beta_user = true,
    beta_joined_at = now(),
    trial_ends_at = now() + interval '30 days',
    has_used_trial = false,
    beta_discount_code = 'BETA30'
  WHERE id = p_user_id;

  RETURN jsonb_build_object(
    'ok', true,
    'claimed', true,
    'already_beta', false,
    'spots_left', GREATEST(v_spots_left - 1, 0)
  );
END;
$$;

GRANT EXECUTE ON FUNCTION claim_beta_spot(TEXT, INTEGER) TO service_role;
