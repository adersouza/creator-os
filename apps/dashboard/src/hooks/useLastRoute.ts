import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * Persist the operator's last in-app route for future product surfaces.
 *
 * On every pathname change inside ProtectedLayout, we write the current route
 * to localStorage. We do not auto-restore from /dashboard: Dashboard is a
 * first-class destination, and silently replacing it with the previous route
 * makes sidebar navigation and reloads feel broken.
 *
 * Skip routes: /login, /signup, /welcome, /auth/*, /invite/*, /share/* — these
 * are onboarding/auth surfaces we never want to drop an authed user into on
 * cold start.
 */

const LAST_ROUTE_KEY = 'juno33-last-route';

function shouldRemember(pathname: string): boolean {
  if (!pathname.startsWith('/')) return false;
  if (pathname === '/' || pathname === '/login' || pathname === '/signup') return false;
  if (pathname.startsWith('/auth/') || pathname.startsWith('/invite/')) return false;
  if (pathname.startsWith('/share/')) return false;
  if (pathname.startsWith('/welcome')) return false;
  return true;
}

export function useLastRoute() {
  const { pathname } = useLocation();

  // Remember: persist every pathname that's a "real" in-app route.
  useEffect(() => {
    if (!shouldRemember(pathname)) return;
    try {
      window.localStorage.setItem(LAST_ROUTE_KEY, pathname);
    } catch {
      /* storage unavailable — best effort */
    }
  }, [pathname]);
}
