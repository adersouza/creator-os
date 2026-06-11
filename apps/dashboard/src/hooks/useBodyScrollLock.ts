import { useEffect } from 'react';

/**
 * Lock body scroll while `open=true`.
 *
 * iOS Safari ignores `document.body.style.overflow = 'hidden'` — the body
 * keeps scrolling behind any fixed-position modal/sheet. The reliable
 * cross-browser pattern is to set `position: fixed` on body with the current
 * scrollY pinned via `top: -${scrollY}px`, then restore scroll on close.
 *
 * Replaces three near-duplicate inline implementations in Modal, Sheet, and
 * ComposerModal that all used the broken `overflow: hidden` shortcut.
 */
export function useBodyScrollLock(open: boolean): void {
  useEffect(() => {
    if (!open) return;
    if (typeof document === 'undefined') return;

    const scrollY = window.scrollY;
    const body = document.body;
    const prev = {
      position: body.style.position,
      top: body.style.top,
      left: body.style.left,
      right: body.style.right,
      width: body.style.width,
      overflow: body.style.overflow,
    };

    body.style.position = 'fixed';
    body.style.top = `-${scrollY}px`;
    body.style.left = '0';
    body.style.right = '0';
    body.style.width = '100%';
    // Belt-and-suspenders for Android Chrome, where overflow:hidden DOES work.
    body.style.overflow = 'hidden';

    return () => {
      body.style.position = prev.position;
      body.style.top = prev.top;
      body.style.left = prev.left;
      body.style.right = prev.right;
      body.style.width = prev.width;
      body.style.overflow = prev.overflow;
      window.scrollTo(0, scrollY);
    };
  }, [open]);
}
