import { useCallback, useEffect, useState } from 'react';

/**
 * useFirstTimeHint — persistent one-shot hint tracker.
 *
 * Each hint has a stable id. On first mount, the hint renders; the operator
 * dismisses it (or an auto-dismiss path hits) and that id gets stamped in
 * localStorage so the hint never reappears. Multi-tab safe via the storage
 * event — dismissing in one tab hides the hint in every other open tab.
 *
 * Usage:
 *   const { show, dismiss } = useFirstTimeHint('cmdk-global');
 *   if (!show) return null;
 *   return <HintPill onDismiss={dismiss}>Press ⌘K to search anywhere</HintPill>;
 */

const STORAGE_KEY = 'juno33-hints-seen';

function loadSeen(): Set<string> {
  if (typeof window === 'undefined') return new Set();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? new Set(parsed.filter((x): x is string => typeof x === 'string')) : new Set();
  } catch {
    return new Set();
  }
}

function persistSeen(seen: Set<string>) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(seen)));
  } catch {
    /* storage unavailable — hint re-shows next session */
  }
}

export function useFirstTimeHint(id: string, opts?: { delayMs?: number | undefined }) {
  const [show, setShow] = useState(() => !loadSeen().has(id));

  // Hide until the delay elapses — prevents flash on cold start when the
  // operator hasn't seen the surface yet.
  const delay = opts?.delayMs ?? 0;
  const [delayElapsed, setDelayElapsed] = useState(delay === 0);
  useEffect(() => {
    if (delay === 0 || !show) return;
    const t = setTimeout(() => setDelayElapsed(true), delay);
    return () => clearTimeout(t);
  }, [delay, show]);

  // Multi-tab sync: if the user dismissed this hint in another tab, catch up.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY) return;
      setShow(!loadSeen().has(id));
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [id]);

  const dismiss = useCallback(() => {
    const seen = loadSeen();
    seen.add(id);
    persistSeen(seen);
    setShow(false);
  }, [id]);

  return { show: show && delayElapsed, dismiss };
}
