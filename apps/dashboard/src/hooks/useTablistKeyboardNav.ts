// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useCallback, type KeyboardEvent } from 'react';

/**
 * ARIA Authoring Practices tablist keyboard navigation.
 *
 * Several pages render `role="tab"` buttons but only respond to clicks; the
 * audit flagged that screen readers put users in "application mode" expecting
 * arrow-key navigation that didn't exist. This hook returns an `onKeyDown`
 * handler the caller wires to the `role="tablist"` container; ArrowLeft/Right
 * (or Up/Down for vertical) navigate, Home/End jump to ends.
 *
 * Pair with `data-tab-id={id}` on each tab button and `tabIndex={isActive ? 0 : -1}`
 * for the roving-tabindex pattern. The hook focuses the new active tab via
 * the data attribute after the navigate callback runs.
 */
interface Options {
  /** Ordered tab ids — must match the `data-tab-id` on each tab button. */
  ids: readonly string[];
  /** Currently active id. */
  activeId: string;
  /** Called when keyboard navigation selects a new tab. */
  onNavigate: (id: string) => void;
  /** `horizontal` (default) listens to ArrowLeft/Right; `vertical` listens to ArrowUp/Down. */
  orientation?: 'horizontal' | 'vertical' | undefined;
  /**
   * Optional scope selector — when multiple tablists with overlapping ids
   * coexist (e.g. desktop + mobile copies on Settings), pass a unique
   * selector prefix like `[data-tablist="settings-desktop"]` so focus
   * lands on the right element.
   */
  scopeSelector?: string | undefined;
}

export function useTablistKeyboardNav({
  ids,
  activeId,
  onNavigate,
  orientation = 'horizontal',
  scopeSelector,
}: Options) {
  return useCallback(
    (e: KeyboardEvent<HTMLElement>) => {
      const isHorizontal = orientation === 'horizontal';
      const nextKey = isHorizontal ? 'ArrowRight' : 'ArrowDown';
      const prevKey = isHorizontal ? 'ArrowLeft' : 'ArrowUp';
      const idx = ids.indexOf(activeId);
      if (idx < 0) return;

      let target: number | null = null;
      if (e.key === nextKey) target = (idx + 1) % ids.length;
      else if (e.key === prevKey) target = (idx - 1 + ids.length) % ids.length;
      else if (e.key === 'Home') target = 0;
      else if (e.key === 'End') target = ids.length - 1;
      if (target === null) return;

      e.preventDefault();
      const newId = ids[target];
      onNavigate(newId!);

      // Defer focus until React commits the new active state. The new
      // active tab gets tabIndex=0, so calling .focus() lands cleanly.
      requestAnimationFrame(() => {
        const scope = scopeSelector
          ? `${scopeSelector} [data-tab-id="${newId}"]`
          : `[data-tab-id="${newId}"]`;
        const el = document.querySelector<HTMLElement>(scope);
        el?.focus();
      });
    },
    [ids, activeId, onNavigate, orientation, scopeSelector],
  );
}
