import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { createPortal } from 'react-dom';
import { Z } from './overlayZ';

/**
 * PortalDropdown — portaled menu/dropdown panel anchored to a trigger.
 *
 * Why portal: filter chips, saved-views menus, and similar floaters lived in
 * absolutely-positioned siblings of their trigger. The instant their parent
 * had `overflow: hidden`, the panel got clipped at the card edge.
 * Portaling to <body> with fixed positioning makes the panel
 * survive any future ancestor overflow without forcing every host to opt
 * into `overflowVisible`.
 *
 * The component owns: position recompute on resize/scroll, outside-click
 * dismiss, Escape dismiss, and z-index from `overlayZ`. The trigger keeps
 * its toggle state — same contract as a controlled menu.
 */

interface Props {
  open: boolean;
  onClose: () => void;
  /** Ref to the trigger element. Used for positioning + outside-click pass-through. */
  triggerRef: RefObject<HTMLElement | null>;
  /** Anchor edge. `start` aligns panel-left to trigger-left, `end` aligns panel-right to trigger-right. */
  align?: 'start' | 'end' | undefined;
  /** Pixel gap between trigger bottom and panel top. */
  gap?: number | undefined;
  /** Class names for the panel surface. */
  className?: string | undefined;
  /**
   * ARIA role on the panel. Default is none — these chips are single-select
   * option lists with click-only interaction; `role="menu"` would require
   * arrow-key navigation we don't implement, and shipping that lie is worse
   * than no role. Callers can opt in to `listbox` if they wire keyboard nav.
   */
  role?: 'menu' | 'listbox' | 'dialog' | undefined;
  children: ReactNode;
}

const VIEWPORT_GUTTER = 8;

export function PortalDropdown({
  open,
  onClose,
  triggerRef,
  align = 'start',
  gap = 6,
  className = '',
  role,
  children,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  // Position computation. useLayoutEffect to avoid the first-paint flash at (0,0).
  // Two-pass: first pass positions with the panel's prior width (or 0 on initial
  // open); a follow-up rAF re-runs once the panel has mounted and we can measure
  // its real width. The second pass clamps the panel inside the viewport so an
  // align="end" panel anchored to a left-side trigger doesn't slide off-screen.
  useLayoutEffect(() => {
    if (!open) return;
    let frame = 0;
    const update = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      // If the trigger has scrolled out of view (above the viewport or below
      // it), close the panel rather than letting it float anchored to nothing.
      // The panel's z-index sits above page chrome, so a sticky topbar won't
      // hide it — explicit close is the only correct behavior.
      if (rect.bottom < 0 || rect.top > window.innerHeight) {
        onClose();
        return;
      }
      const panelW = panelRef.current?.offsetWidth ?? 0;
      const ideal = align === 'end' ? rect.right - panelW : rect.left;
      // Clamp to viewport with a small gutter so we never clip an edge.
      const max = window.innerWidth - panelW - VIEWPORT_GUTTER;
      const left = panelW > 0 ? Math.max(VIEWPORT_GUTTER, Math.min(ideal, max)) : ideal;
      setPos({ top: rect.bottom + gap, left });
    };
    update();
    // After the panel mounts, re-run with the now-measurable offsetWidth.
    frame = requestAnimationFrame(update);
    window.addEventListener('resize', update);
    // capture: catch nested scroll containers (filter bar inside scrollable page).
    window.addEventListener('scroll', update, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [open, align, gap, triggerRef, onClose]);

  // Dismiss handlers.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t)) return;
      if (panelRef.current?.contains(t)) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose, triggerRef]);

  if (!open || !pos) return null;

  return createPortal(
    <div
      ref={panelRef}
      role={role}
      className={className}
      style={{
        position: 'fixed',
        top: pos.top,
        left: pos.left,
        zIndex: Z.popover,
      }}
    >
      {children}
    </div>,
    document.body,
  );
}
