-- Prevent authenticated clients from self-granting paid entitlements through RLS.
-- Billing-owned columns must be changed only by service-role API/webhook paths.

BEGIN;

CREATE OR REPLACE FUNCTION public.is_service_role_request()
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = public
AS $$
  SELECT
    current_user IN ('postgres', 'supabase_admin', 'service_role')
    OR COALESCE(current_setting('request.jwt.claim.role', true), '') = 'service_role';
$$;

CREATE OR REPLACE FUNCTION public.reject_client_profile_billing_updates()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  IF public.is_service_role_request() THEN
    RETURN NEW;
  END IF;

  IF (to_jsonb(NEW)->'subscription_tier') IS DISTINCT FROM (to_jsonb(OLD)->'subscription_tier')
    OR (to_jsonb(NEW)->'subscription_status') IS DISTINCT FROM (to_jsonb(OLD)->'subscription_status')
    OR (to_jsonb(NEW)->'billing_interval') IS DISTINCT FROM (to_jsonb(OLD)->'billing_interval')
    OR (to_jsonb(NEW)->'stripe_customer_id') IS DISTINCT FROM (to_jsonb(OLD)->'stripe_customer_id')
    OR (to_jsonb(NEW)->'stripe_subscription_id') IS DISTINCT FROM (to_jsonb(OLD)->'stripe_subscription_id')
    OR (to_jsonb(NEW)->'has_used_trial') IS DISTINCT FROM (to_jsonb(OLD)->'has_used_trial')
    OR (to_jsonb(NEW)->'trial_used') IS DISTINCT FROM (to_jsonb(OLD)->'trial_used')
    OR (to_jsonb(NEW)->'trial_started_at') IS DISTINCT FROM (to_jsonb(OLD)->'trial_started_at')
    OR (to_jsonb(NEW)->'trial_ends_at') IS DISTINCT FROM (to_jsonb(OLD)->'trial_ends_at')
    OR (to_jsonb(NEW)->'referral_trial_ends_at') IS DISTINCT FROM (to_jsonb(OLD)->'referral_trial_ends_at')
    OR (to_jsonb(NEW)->'extra_accounts') IS DISTINCT FROM (to_jsonb(OLD)->'extra_accounts')
    OR (to_jsonb(NEW)->'extra_team_members') IS DISTINCT FROM (to_jsonb(OLD)->'extra_team_members')
  THEN
    RAISE EXCEPTION 'Billing entitlement columns can only be updated by service role'
      USING ERRCODE = '42501';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reject_client_profile_billing_updates ON public.profiles;
CREATE TRIGGER trg_reject_client_profile_billing_updates
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.reject_client_profile_billing_updates();

CREATE OR REPLACE FUNCTION public.reject_client_workspace_billing_updates()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  IF public.is_service_role_request() THEN
    RETURN NEW;
  END IF;

  IF (to_jsonb(NEW)->'tier') IS DISTINCT FROM (to_jsonb(OLD)->'tier')
    OR (to_jsonb(NEW)->'subscription') IS DISTINCT FROM (to_jsonb(OLD)->'subscription')
  THEN
    RAISE EXCEPTION 'Workspace billing columns can only be updated by service role'
      USING ERRCODE = '42501';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reject_client_workspace_billing_updates ON public.workspaces;
CREATE TRIGGER trg_reject_client_workspace_billing_updates
  BEFORE UPDATE ON public.workspaces
  FOR EACH ROW
  EXECUTE FUNCTION public.reject_client_workspace_billing_updates();

COMMIT;
