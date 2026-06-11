import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { appToast } from '@/lib/toast';
import { NovaCard } from '@/components/ui/NovaPrimitives';
import { Spinner } from '@/components/ui/Spinner';
import { clearPendingInvite, readPendingInvite } from '@/lib/pendingInvite';
import { supabase, supabaseAuth } from '@/services/supabase';
import { joinWorkspaceWithCode } from '@/services/teamService';
import { safeRedirectPath } from '@/utils/sanitize';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

const AUTH_REDIRECT_STORAGE_KEY = 'juno33-auth-redirect';

/**
 * OAuth / magic-link landing route.
 *
 * Supabase client is configured with `detectSessionInUrl: false`, so we
 * manually exchange the PKCE `code` param (or fall back to hash-fragment
 * implicit tokens for older providers). On success we bounce to /welcome
 * for fresh signups or /dashboard for returning users.
 */
export function AuthCallback() {
  const navigate = useNavigate();
  const refreshWorkspaces = useWorkspaceStore((s) => s.refreshWorkspaces);
  const selectWorkspace = useWorkspaceStore((s) => s.selectWorkspace);
  const [message, setMessage] = useState('Finalizing your session…');
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    (async () => {
      const url = new URL(window.location.href);
      const code = url.searchParams.get('code');
      const hashParams = new URLSearchParams(url.hash.replace(/^#/, ''));
      const accessToken = hashParams.get('access_token');
      const refreshToken = hashParams.get('refresh_token');
      const errorDescription =
        url.searchParams.get('error_description') ||
        hashParams.get('error_description');

      if (errorDescription) {
        appToast.error('Sign-in failed', { description: errorDescription });
        navigate('/login', { replace: true });
        return;
      }

      try {
        if (code) {
          const { error } = await supabase.auth.exchangeCodeForSession(code);
          if (error) throw error;
        } else if (accessToken && refreshToken) {
          const { error } = await supabase.auth.setSession({
            access_token: accessToken,
            refresh_token: refreshToken,
          });
          if (error) throw error;
        }

        const { data: { session } } = await supabase.auth.getSession();
        if (!session) {
          setMessage('No active session. Redirecting…');
          navigate('/login', { replace: true });
          return;
        }

        // OAuth bypasses the password-level TOTP prompt. If the user has a
        // verified factor on file, bounce through /login (PublicOnlyRoute
        // treats AAL1-pending as unauthed) so the challenge runs before
        // any protected navigation — including invite acceptance below.
        const mfa = await supabaseAuth.getMfaStatus();
        if (mfa.needsMfa) {
          setMessage('Almost there — verify your authenticator to continue.');
          navigate('/login', { replace: true });
          return;
        }

        const pendingInvite = readPendingInvite();
        if (pendingInvite) {
          setMessage('Accepting your workspace invite…');
          try {
            const workspaceId = await joinWorkspaceWithCode(pendingInvite);
            clearPendingInvite();
            await refreshWorkspaces();
            await selectWorkspace(workspaceId);
            appToast.success('Joined the workspace');
            navigate('/dashboard', { replace: true });
            return;
          } catch (err) {
            const description = err instanceof Error ? err.message : 'Could not accept invite.';
            appToast.error('Invite acceptance failed', { description });
          }
        }

        // Fresh signups have a very recent created_at — route to /welcome.
        const createdAt = session.user?.created_at ? new Date(session.user.created_at).getTime() : 0;
        const isFresh = Date.now() - createdAt < 5 * 60 * 1000;
        const pendingRedirect = (() => {
          try {
            return localStorage.getItem(AUTH_REDIRECT_STORAGE_KEY);
          } catch {
            return null;
          }
        })();
        if (!isFresh && pendingRedirect) {
          try {
            localStorage.removeItem(AUTH_REDIRECT_STORAGE_KEY);
          } catch {}
        }
        const safePending = pendingRedirect ? safeRedirectPath(pendingRedirect) : '/dashboard';
        navigate(isFresh ? '/welcome' : safePending, { replace: true });
      } catch (err) {
        const description = err instanceof Error ? err.message : 'Unable to complete sign-in.';
        appToast.error('Sign-in failed', { description });
        navigate('/login', { replace: true });
      }
    })();
  }, [navigate, refreshWorkspaces, selectWorkspace]);

  return (
    <NovaCard className="w-full max-w-sm" contentClassName="p-8 text-center">
      <Spinner className="mx-auto mb-4 size-6 text-primary" />
      <p className="text-sm text-muted-foreground">{message}</p>
    </NovaCard>
  );
}
