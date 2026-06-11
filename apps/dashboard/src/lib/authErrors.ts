/**
 * Backend → frontend error code shared by routes that require AAL2
 * (api/_lib/middleware.ts::requireStepUp). When the user is authed at AAL1
 * but has a verified TOTP factor, destructive routes return 403 with this
 * body code so the frontend can route the user to /login for re-auth.
 */
export const MFA_STEP_UP_CODE = 'MFA_STEP_UP_REQUIRED';

/**
 * Inspect a failed response. If it's a step-up 403, drop the AAL1 session
 * and bounce the user to /login so the challenge screen can re-prompt.
 * Returns true if handled (caller should abort its own error path).
 *
 * Safe to call on any non-ok response — returns false for unrelated errors.
 */
export async function handleMfaStepUp(response: Response): Promise<boolean> {
  if (response.status !== 403) return false;
  let body: unknown;
  try {
    body = await response.clone().json();
  } catch {
    return false;
  }
  const code = (body as { code?: string | undefined } | null)?.code;
  if (code !== MFA_STEP_UP_CODE) return false;

  // Local sign-out so the next /login visit sees no session and re-asks
  // for the password. A full sign-out would clobber the refresh token for
  // other devices — scope:'local' only affects this browser.
  try {
    const { supabase } = await import('@/services/supabase');
    await supabase.auth.signOut({ scope: 'local' });
  } catch {
    /* ignore */
  }

  try {
    const { appToast } = await import('@/lib/toast');
    appToast.error('Re-verify to continue', {
      description: 'That action needs a fresh authenticator code. Sign in again to confirm.',
    });
  } catch {
    /* ignore */
  }

  // Hard navigate — the SPA's protected-layout bounce catches it, but this
  // is a security-sensitive redirect so we don't trust in-memory router state.
  window.location.assign('/login');
  return true;
}
