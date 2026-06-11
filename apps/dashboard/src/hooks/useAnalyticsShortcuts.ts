import { useEffect } from 'react';
import {
  cyclePlatform,
  cycleDateRange,
  shiftDateRange,
  type AnalyticsState,
} from '@/lib/analyticsUrlState';

interface Options {
  state: AnalyticsState;
  onUpdate: (patch: Partial<AnalyticsState>) => void;
  enabled?: boolean | undefined;
  allowPlatformCycle?: boolean | undefined;
}

/**
 * Registers the Analytics-page keyboard shortcuts (spec §11):
 *   C   → toggle compare
 *   D   → cycle date range preset
 *   [ ] → shift custom date range backward/forward (no-op on presets)
 *   P   → cycle platform (All → Threads → IG → All)
 *
 * Shortcut keys are swallowed ONLY when no input/textarea has focus, and the
 * user is not in a contenteditable region. ⌘K, ⌘↵, ⌘⇧I, J/K are handled
 * elsewhere (command palette, InvestigateButton hotkey=true, fleet grid
 * row navigation respectively).
 */
export function useAnalyticsShortcuts({
  state,
  onUpdate,
  enabled = true,
  allowPlatformCycle = true,
}: Options) {
  useEffect(() => {
    if (!enabled) return;
    const handler = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const target = e.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) return;
      }

      switch (e.key.toLowerCase()) {
        case 'c': {
          onUpdate({ compare: state.compare === 'off' ? 'prev' : 'off' });
          e.preventDefault();
          break;
        }
        case 'd': {
          onUpdate({ dateRange: cycleDateRange(state.dateRange) });
          e.preventDefault();
          break;
        }
        case 'p': {
          if (!allowPlatformCycle) break;
          onUpdate({ platform: cyclePlatform(state.platform) });
          e.preventDefault();
          break;
        }
        case '[': {
          if (state.dateRange.kind === 'custom') {
            onUpdate({ dateRange: shiftDateRange(state.dateRange, -1) });
            e.preventDefault();
          }
          break;
        }
        case ']': {
          if (state.dateRange.kind === 'custom') {
            onUpdate({ dateRange: shiftDateRange(state.dateRange, 1) });
            e.preventDefault();
          }
          break;
        }
        default:
          break;
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [state, onUpdate, enabled, allowPlatformCycle]);
}
