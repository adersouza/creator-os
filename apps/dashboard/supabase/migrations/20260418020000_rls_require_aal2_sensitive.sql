-- RLS: require AAL2 for destructive / credential operations on sensitive
-- tables when the user has MFA enrolled.
--
-- Defense in depth: middleware at `/api/admin/*` and `requireStepUp` already
-- gate the API surface. This blocks direct supabase-js writes that bypass
-- the API entirely (juno33 uses direct RLS for most reads/writes).
--
-- Policy pattern: RESTRICTIVE, so it AND-stacks with each table's existing
-- permissive "user can manage own X" policy — we're *tightening*, not
-- replacing. If the user has NO verified MFA factors, we short-circuit and
-- allow (don't lock unenrolled users out of their own account).
--
-- Attack this blocks: attacker with AAL1 token (stolen cookie, password only)
-- tries to DELETE the victim's account or rotate their developer API key. At
-- AAL1 + victim-has-MFA, RLS refuses. They'd have to complete TOTP first.
--
-- Service role bypasses RLS entirely, so token-refresh crons, Stripe webhook
-- handlers, etc. are unaffected. This only applies to the `authenticated`
-- role (end-user JWTs).

-- ── helper: true if the calling user is AAL2-authenticated OR has no MFA ──
-- Wrapping in a function keeps the RLS expressions legible and lets us unit
-- test the predicate in isolation. STABLE so the planner can cache per-
-- statement. `auth.jwt()` and `auth.uid()` are both STABLE themselves.
CREATE OR REPLACE FUNCTION public.aal2_or_no_mfa()
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = public, auth
AS $$
  -- auth.mfa_factors requires elevated read permissions; SECURITY DEFINER
  -- lets the function inspect the caller's own factors without exposing
  -- the table to direct client queries. auth.uid() / auth.jwt() still
  -- reflect the *calling* session since they read the GUC, not the owner.
  SELECT
    (auth.jwt() ->> 'aal') = 'aal2'
    OR NOT EXISTS (
      SELECT 1 FROM auth.mfa_factors
      WHERE user_id = auth.uid() AND status = 'verified'
    );
$$;

-- Lock down EXECUTE so only the authenticated role can call it (matches
-- where it's referenced in policies). Public execute would be harmless
-- since the function only reflects the caller's own state, but tightening
-- the grant keeps the surface minimal.
REVOKE ALL ON FUNCTION public.aal2_or_no_mfa() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.aal2_or_no_mfa() TO authenticated;

COMMENT ON FUNCTION public.aal2_or_no_mfa IS
  'True when the caller is at AAL2 or has no verified MFA factor. Used by RESTRICTIVE RLS policies to require step-up for sensitive writes.';

-- ── accounts (Threads) — DELETE requires AAL2 if MFA is on ─────────────
CREATE POLICY "aal2_required_accounts_delete"
  ON public.accounts
  AS RESTRICTIVE
  FOR DELETE
  TO authenticated
  USING ((SELECT public.aal2_or_no_mfa()));

-- ── instagram_accounts — DELETE requires AAL2 if MFA is on ─────────────
CREATE POLICY "aal2_required_instagram_accounts_delete"
  ON public.instagram_accounts
  AS RESTRICTIVE
  FOR DELETE
  TO authenticated
  USING ((SELECT public.aal2_or_no_mfa()));

-- ── api_keys — INSERT / UPDATE / DELETE require AAL2 ───────────────────
-- Personal developer API keys grant service-level access; treat creation,
-- rotation, and deletion as credential operations.
CREATE POLICY "aal2_required_api_keys_insert"
  ON public.api_keys
  AS RESTRICTIVE
  FOR INSERT
  TO authenticated
  WITH CHECK ((SELECT public.aal2_or_no_mfa()));

CREATE POLICY "aal2_required_api_keys_update"
  ON public.api_keys
  AS RESTRICTIVE
  FOR UPDATE
  TO authenticated
  USING ((SELECT public.aal2_or_no_mfa()))
  WITH CHECK ((SELECT public.aal2_or_no_mfa()));

CREATE POLICY "aal2_required_api_keys_delete"
  ON public.api_keys
  AS RESTRICTIVE
  FOR DELETE
  TO authenticated
  USING ((SELECT public.aal2_or_no_mfa()));

-- ── webhook_subscriptions — INSERT / UPDATE / DELETE require AAL2 ──────
-- Webhooks carry a signing `secret`; same credential category as API keys.
CREATE POLICY "aal2_required_webhook_subs_insert"
  ON public.webhook_subscriptions
  AS RESTRICTIVE
  FOR INSERT
  TO authenticated
  WITH CHECK ((SELECT public.aal2_or_no_mfa()));

CREATE POLICY "aal2_required_webhook_subs_update"
  ON public.webhook_subscriptions
  AS RESTRICTIVE
  FOR UPDATE
  TO authenticated
  USING ((SELECT public.aal2_or_no_mfa()))
  WITH CHECK ((SELECT public.aal2_or_no_mfa()));

CREATE POLICY "aal2_required_webhook_subs_delete"
  ON public.webhook_subscriptions
  AS RESTRICTIVE
  FOR DELETE
  TO authenticated
  USING ((SELECT public.aal2_or_no_mfa()));
