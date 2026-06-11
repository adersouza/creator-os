/**
 * Pointer-tracked specular highlight for `.liquid-hover` / `.hover-specular`
 * elements. Writes `--mx` / `--my` (relative to the element) on pointermove.
 * CSS does the rendering; this module is just the delegated listener.
 *
 * Install once at app boot (see main.tsx). Respects prefers-reduced-motion.
 */

const SPECULAR_SELECTOR = '.liquid-hover, .hover-specular';

let installed = false;

export function installHoverSpecular(): void {
  if (installed) return;
  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  if (
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  ) {
    return;
  }

  const handler = (event: PointerEvent) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const el = target.closest(SPECULAR_SELECTOR) as HTMLElement | null;
    if (!el) return;

    const rect = el.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 100;
    const y = ((event.clientY - rect.top) / rect.height) * 100;
    el.style.setProperty('--mx', `${x}%`);
    el.style.setProperty('--my', `${y}%`);
  };

  document.addEventListener('pointermove', handler, { passive: true });
  installed = true;
}
