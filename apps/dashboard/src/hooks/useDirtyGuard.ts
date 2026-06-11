import { useEffect } from 'react';

/**
 * useDirtyGuard — wire the browser's native beforeunload prompt so tab-close
 * or hard refresh warns the operator when the caller has unsaved work.
 *
 * Only guards the tab lifecycle. It does NOT intercept in-app close paths
 * (Esc, X, backdrop click, SPA navigation) — those need per-surface wiring
 * because React Router's navigation doesn't fire beforeunload.
 *
 * Pass `dirty=true` when there's content worth protecting; the hook
 * attaches the listener, passes `dirty=false` to detach. Modern browsers
 * ignore the return value and show their own localized copy, but setting
 * returnValue + preventDefault is still required to trigger the prompt.
 */
export function useDirtyGuard(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      // Chrome / Edge / Safari require both; Firefox honors preventDefault alone.
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [dirty]);
}
