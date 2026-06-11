BEGIN;

DO $$
DECLARE
  function_regprocedure REGPROCEDURE;
BEGIN
  function_regprocedure := to_regprocedure('public.touch_autoposter_strategy_recommendations()');

  IF function_regprocedure IS NOT NULL THEN
    EXECUTE format('ALTER FUNCTION %s SET search_path = public', function_regprocedure);
  END IF;
END $$;

DO $$
DECLARE
  function_signature TEXT;
  function_regprocedure REGPROCEDURE;
BEGIN
  FOREACH function_signature IN ARRAY ARRAY[
    'public.get_rate_limit_status(text)',
    'public.get_rate_limit_status(text, integer, integer)'
  ]
  LOOP
    function_regprocedure := to_regprocedure(function_signature);

    IF function_regprocedure IS NOT NULL THEN
      EXECUTE format(
        'REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, anon, authenticated',
        function_regprocedure
      );
      EXECUTE format(
        'GRANT EXECUTE ON FUNCTION %s TO service_role',
        function_regprocedure
      );
    END IF;
  END LOOP;
END $$;

DO $$
DECLARE
  target RECORD;
  function_regprocedure REGPROCEDURE;
BEGIN
  FOR target IN
    SELECT *
    FROM (
      VALUES
        (
          'public.aal2_or_no_mfa()',
          'Intentional authenticated SECURITY DEFINER RLS helper. Used by restrictive MFA policies; direct execution only reveals the caller MFA predicate.'
        ),
        (
          'public.is_workspace_admin(text)',
          'Intentional authenticated SECURITY DEFINER RLS helper for workspace authorization checks.'
        ),
        (
          'public.is_workspace_member(text)',
          'Intentional authenticated SECURITY DEFINER RLS helper for workspace authorization checks.'
        ),
        (
          'public.is_workspace_member(text, text)',
          'Intentional authenticated SECURITY DEFINER RLS helper for workspace authorization checks.'
        ),
        (
          'public.is_workspace_owner(text, text)',
          'Intentional authenticated SECURITY DEFINER RLS helper for workspace authorization checks.'
        )
    ) AS v(signature, rationale)
  LOOP
    function_regprocedure := to_regprocedure(target.signature);

    IF function_regprocedure IS NOT NULL THEN
      EXECUTE format(
        'COMMENT ON FUNCTION %s IS %L',
        function_regprocedure,
        target.rationale
      );
    END IF;
  END LOOP;
END $$;

COMMIT;
