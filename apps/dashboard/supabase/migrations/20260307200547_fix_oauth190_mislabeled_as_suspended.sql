-- Backfilled from DB: applied via Supabase dashboard on 2026-03-07
-- Remediate accounts mislabeled as "suspended" by the sync-orchestrator bug.
--
-- Root cause: syncAccount() in sync-orchestrator.ts treated OAuthException (code 190)
-- identically to a content-policy suspension (codes 100/10). Both paths wrote
-- status = 'suspended', is_active = false — but code 190 should write
-- status = 'needs_reauth', needs_reauth = true so users get a "Reconnect" prompt
-- instead of a "Suspended" badge, and the token-refresh cron can find them.
--
-- Safe discriminator: all affected rows have token_expires_at < NOW() and
-- needs_reauth = false. Genuine content-policy suspensions do not have this pattern.

DO $$
BEGIN
  IF to_regclass('public.accounts') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'accounts'
         AND column_name IN ('status', 'needs_reauth', 'updated_at', 'is_active', 'token_expires_at')
       GROUP BY table_name
       HAVING COUNT(*) = 5
     ) THEN
    UPDATE accounts
    SET
      status      = 'needs_reauth',
      needs_reauth = true,
      updated_at  = NOW()
    WHERE
      status         = 'suspended'
      AND is_active  = false
      AND needs_reauth = false
      AND token_expires_at IS NOT NULL
      AND token_expires_at < NOW();
  END IF;
END $$;
