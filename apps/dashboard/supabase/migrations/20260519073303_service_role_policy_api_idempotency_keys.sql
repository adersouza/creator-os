-- Durable API idempotency claims are backend-only and written through the
-- service-role Supabase client. Keep RLS explicit so the table is not exposed
-- to browser sessions while satisfying the RLS-enabled-no-policy advisor.

DO $$
BEGIN
  IF to_regclass('public.api_idempotency_keys') IS NOT NULL THEN
    DROP POLICY IF EXISTS "Service role manages API idempotency keys"
      ON public.api_idempotency_keys;

    CREATE POLICY "Service role manages API idempotency keys"
      ON public.api_idempotency_keys
      FOR ALL TO service_role
      USING (true)
      WITH CHECK (true);
  END IF;
END $$;
