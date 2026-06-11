import { useEffect } from 'react';
import { appToast } from '@/lib/toast';
import { supabase } from '@/services/supabase';

/**
 * Watches Supabase session expiry. Emits a 30-second warning toast before
 * the JWT dies, offering a [Stay signed in] button that forces a refresh
 * and dismisses the toast. If the user ignores, the session is re-checked
 * on the next auth state change — stale sessions trigger a normal redirect
 * from the Protected layouts.
 *
 * Mounted once at app root. No-op until there's a session.
 */
export function SessionExpiryWatcher() {
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    let warningId: string | number | null = null;
    let cancelled = false;

    const schedule = (expiresAtSec: number | undefined) => {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      if (warningId !== null) {
        appToast.dismiss(warningId);
        warningId = null;
      }
      if (!expiresAtSec) return;

      const nowMs = Date.now();
      const expiresMs = expiresAtSec * 1000;
      const fireAt = expiresMs - 30_000; // 30s before expiry
      const delay = Math.max(0, fireAt - nowMs);

      timer = setTimeout(async () => {
        if (cancelled) return;
        warningId = appToast.warn('Session expiring soon', {
          description: "You'll be signed out in 30 seconds unless you stay signed in.",
          duration: 30_000,
          action: {
            label: 'Stay signed in',
            onClick: async () => {
              const { data, error } = await supabase.auth.refreshSession();
              if (warningId !== null) {
                appToast.dismiss(warningId);
                warningId = null;
              }
              if (error) {
                appToast.error('Could not refresh session', { description: error.message });
                return;
              }
              if (data.session?.expires_at) {
                schedule(data.session.expires_at);
                appToast.success('Session extended');
              }
            },
          },
        });
      }, delay);
    };

    (async () => {
      const { data: { session } } = await supabase.auth.getSession();
      schedule(session?.expires_at);
    })();

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      schedule(session?.expires_at);
    });

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      if (warningId !== null) appToast.dismiss(warningId);
      subscription.unsubscribe();
    };
  }, []);

  return null;
}
