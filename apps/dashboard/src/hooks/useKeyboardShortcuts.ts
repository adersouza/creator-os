import { useEffect, useRef, useState } from 'react';

export type ShortcutKey =
  | 'go-overview' | 'go-accounts' | 'go-scheduler' | 'go-composer' | 'go-analytics' | 'go-smartlinks'
  | 'new-post' | 'open-palette' | 'toggle-help' | 'close';

interface Options {
  onShortcut: (key: ShortcutKey) => void;
  /** Disable when true (e.g., when an overlay is open that handles its own keys) */
  disabled?: boolean | undefined;
}

// Minimal pub/sub for the G-leader indicator. Decoupled so any layout
// component can subscribe without threading props through the shortcut hook.
type LeaderListener = (active: boolean) => void;
const leaderListeners = new Set<LeaderListener>();
let leaderActive = false;
function setLeaderActive(next: boolean) {
  if (next === leaderActive) return;
  leaderActive = next;
  leaderListeners.forEach((fn) => { fn(next); });
}

export function useLeaderActive(): boolean {
  const [active, setActive] = useState(leaderActive);
  useEffect(() => {
    leaderListeners.add(setActive);
    return () => { leaderListeners.delete(setActive); };
  }, []);
  return active;
}

/**
 * Keyboard shortcut handler — Linear G-prefix + single-key actions.
 * Research (micro_interactions_2026): "Linear's G-prefix navigation is the power-user secret language."
 *
 * G-prefix (press G then destination letter within 1200ms):
 *   G O  → Overview
 *   G A  → Accounts
 *   G S  → Scheduler
 *   G C  → Composer
 *   G Y  → Analytics (Y because C is taken by Composer)
 *   G L  → Smart Links
 *
 * Single-key (when not typing in an input):
 *   C    → Create post
 *   ?    → Toggle shortcuts help overlay
 *   Esc  → Close overlays
 *
 * ⌘K / Ctrl+K is handled separately in Layout (already wired).
 */
export function useKeyboardShortcuts({ onShortcut, disabled }: Options) {
  // Track G-prefix state — reset after 1.2s (Linear's timing)
  const leaderPressedAt = useRef<number>(0);
  const leaderTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (disabled) return;

    const isTyping = (el: EventTarget | null): boolean => {
      if (!(el instanceof HTMLElement)) return false;
      const tag = el.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
      if (el.isContentEditable) return true;
      return false;
    };

    const handler = (e: KeyboardEvent) => {
      // Skip if user is typing, a modifier key (other than shift) is held,
      // or a route-local handler already claimed this key (e.g.
      // useAnalyticsShortcuts swallows `c` for the compare toggle and calls
      // preventDefault — without this guard, `c` would also fire `new-post`).
      if (e.defaultPrevented) return;
      if (isTyping(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const now = Date.now();
      const key = e.key.toLowerCase();

      // G-prefix sequence — first press G, then destination within 1200ms
      if (key === 'g') {
        leaderPressedAt.current = now;
        setLeaderActive(true);
        if (leaderTimer.current) clearTimeout(leaderTimer.current);
        leaderTimer.current = setTimeout(() => setLeaderActive(false), 1200);
        return;
      }

      const withinLeader = now - leaderPressedAt.current < 1200;

      if (withinLeader) {
        let action: ShortcutKey | null = null;
        switch (key) {
          case 'o': action = 'go-overview'; break;
          case 'a': action = 'go-accounts'; break;
          case 's': action = 'go-scheduler'; break;
          case 'c': action = 'go-composer'; break;
          case 'y': action = 'go-analytics'; break;
          case 'l': action = 'go-smartlinks'; break;
        }
        if (action) {
          e.preventDefault();
          leaderPressedAt.current = 0;
          setLeaderActive(false);
          if (leaderTimer.current) clearTimeout(leaderTimer.current);
          onShortcut(action);
          return;
        }
      }

      // Single-key actions (always active when not typing)
      if (key === 'c') {
        e.preventDefault();
        onShortcut('new-post');
        return;
      }
      if (key === '?') {
        e.preventDefault();
        onShortcut('toggle-help');
        return;
      }
      if (key === 'escape') {
        onShortcut('close');
        return;
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onShortcut, disabled]);
}

/** Pretty keyboard shortcut map for help overlays + tooltips */
export const SHORTCUT_LABELS: Record<ShortcutKey, { keys: string[]; label: string; group: 'Navigation' | 'Actions' | 'Help' }> = {
  'go-overview':   { keys: ['G', 'O'], label: 'Go to Overview',    group: 'Navigation' },
  'go-accounts':   { keys: ['G', 'A'], label: 'Go to Accounts',    group: 'Navigation' },
  'go-scheduler':  { keys: ['G', 'S'], label: 'Go to Scheduler',   group: 'Navigation' },
  'go-composer':   { keys: ['G', 'C'], label: 'Go to Composer',    group: 'Navigation' },
  'go-analytics':  { keys: ['G', 'Y'], label: 'Go to Analytics',   group: 'Navigation' },
  'go-smartlinks': { keys: ['G', 'L'], label: 'Go to Smart links', group: 'Navigation' },
  'new-post':      { keys: ['C'],      label: 'Create post',       group: 'Actions' },
  'open-palette':  { keys: ['⌘', 'K'], label: 'Command palette',   group: 'Actions' },
  'toggle-help':   { keys: ['?'],      label: 'Toggle this help',  group: 'Help' },
  'close':         { keys: ['Esc'],    label: 'Close overlay',     group: 'Help' },
};
