import { useEffect, useRef } from 'react';
import { appToast } from '@/lib/toast';
import { useErrorStore } from '@/stores/useErrorStore';

/**
 * Mounts once at app root. Subscribes to useErrorStore and surfaces each
 * error via sonner with the appropriate tone + action. Rate-limit errors
 * render a live countdown in the toast description; resolving the store
 * entry dismisses the toast.
 *
 * Producer side: call useErrorStore.getState().addError({ type, message, retryAfter })
 * from anywhere in the app (service workers, hooks, fetch wrappers). This
 * component does the rest.
 */
export function GlobalErrorSurface() {
  const errors = useErrorStore((s) => s.errors);
  const removeError = useErrorStore((s) => s.removeError);
  const shownIds = useRef(new Set<string>());
  const countdownIntervals = useRef(new Map<string, ReturnType<typeof setInterval>>());

  useEffect(() => {
    // Emit toasts for new errors
    for (const err of errors) {
      if (shownIds.current.has(err.id)) continue;
      shownIds.current.add(err.id);
      emit(err, removeError, countdownIntervals.current);
    }
    // Dismiss toasts for errors that left the store
    for (const seenId of Array.from(shownIds.current)) {
      if (!errors.some((e) => e.id === seenId)) {
        appToast.dismiss(seenId);
        shownIds.current.delete(seenId);
        const iv = countdownIntervals.current.get(seenId);
        if (iv) {
          clearInterval(iv);
          countdownIntervals.current.delete(seenId);
        }
      }
    }
  }, [errors, removeError]);

  // Clear any remaining countdowns on unmount (HMR, StrictMode double-mount,
  // or the rare real unmount) so stray intervals don't keep firing against
  // stale toast state.
  useEffect(() => {
    const intervals = countdownIntervals.current;
    const shown = shownIds.current;
    return () => {
      intervals.forEach((iv) => { clearInterval(iv); });
      intervals.clear();
      shown.clear();
    };
  }, []);

  return null;
}

function emit(
  err: { id: string; type: 'rate_limit' | 'auth' | 'network' | 'server'; message: string; retryAfter?: number | undefined; requestId?: string | undefined },
  removeError: (id: string) => void,
  intervals: Map<string, ReturnType<typeof setInterval>>,
) {
  const base = {
    id: err.id,
    action: {
      label: 'Dismiss',
      onClick: () => removeError(err.id),
    },
  };

  if (err.type === 'rate_limit') {
    const secondsRef = { value: err.retryAfter ?? 30 };
    const fmt = () => `Retrying in ${secondsRef.value}s — ${err.message}`;
    appToast.warn('Rate limited', {
      ...base,
      description: fmt(),
      duration: (err.retryAfter ?? 30) * 1000,
    });
    // tick every second so the toast description counts down visibly
    const iv = setInterval(() => {
      secondsRef.value -= 1;
      if (secondsRef.value <= 0) {
        clearInterval(iv);
        intervals.delete(err.id);
        removeError(err.id);
        return;
      }
      appToast.warn('Rate limited', {
        ...base,
        description: fmt(),
        duration: secondsRef.value * 1000,
      });
    }, 1000);
    intervals.set(err.id, iv);
    return;
  }

  if (err.type === 'auth') {
    appToast.error('Session issue', {
      ...base,
      description: withRequestId(err.message, err.requestId),
      duration: Infinity,
    });
    return;
  }

  if (err.type === 'network') {
    appToast.error('Connection lost', {
      ...base,
      description: withRequestId(err.message, err.requestId),
      duration: 8000,
    });
    return;
  }

  // server
  appToast.error('Server error', {
    ...base,
    description: withRequestId(err.message, err.requestId),
    duration: 10000,
  });
}

function withRequestId(message: string, requestId?: string | undefined) {
  return requestId ? `${message} Request ID: ${requestId}` : message;
}
