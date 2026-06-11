/**
 * Reactive scroll-edge effect — writes `--scroll-depth` (0..1) onto every
 * `.scroll-edge` element as its nearest scrollable ancestor moves. The CSS in
 * index.css uses the var to scale the fade + backdrop-filter blur on the
 * floating topbar.
 *
 * HIG Materials § Scroll edge: "variable blur intensifies as content slides
 * underneath." One passive scroll listener per scroll container, rAF-coalesced.
 *
 * Respects prefers-reduced-motion — no-op if the user asked for reduced motion.
 */

const RAMP_PX = 96; // scrollTop where depth reaches 1.0
const ATTR = 'data-scroll-edge-installed';

let installed = false;

function findScrollParent(el: Element | null): HTMLElement | Window | null {
  let node: Element | null = el;
  while (node && node !== document.body) {
    const style = window.getComputedStyle(node);
    const overflowY = style.overflowY;
    if ((overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight > node.clientHeight) {
      return node as HTMLElement;
    }
    node = node.parentElement;
  }
  return window;
}

function depthFor(scroller: HTMLElement | Window): number {
  const top = scroller instanceof Window ? window.scrollY : scroller.scrollTop;
  return Math.min(1, Math.max(0, top / RAMP_PX));
}

export function installScrollEdge(): void {
  if (installed) return;
  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  if (
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  ) {
    return;
  }

  const scrollers = new Map<HTMLElement | Window, HTMLElement[]>();

  const update = () => {
    scrollers.forEach((edges, scroller) => {
      const depth = depthFor(scroller).toFixed(3);
      edges.forEach((edge) => { edge.style.setProperty('--scroll-depth', depth); });
    });
  };

  let pending = false;
  const schedule = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      update();
    });
  };

  const attach = (edges: Iterable<HTMLElement>) => {
    for (const edge of edges) {
      if (edge.hasAttribute(ATTR)) continue;
      const scroller = findScrollParent(edge);
      if (!scroller) continue;
      if (!scrollers.has(scroller)) {
        scrollers.set(scroller, []);
        (scroller as HTMLElement | (Window & typeof globalThis)).addEventListener('scroll', schedule, { passive: true });
      }
      scrollers.get(scroller)?.push(edge);
      edge.setAttribute(ATTR, 'true');
    }
    update();
  };

  // Re-attach on DOM mutations so late-mounted `.scroll-edge` elements (route
  // transitions, slide-overs) still get wired up.
  const observer = new MutationObserver(() => {
    const missing = document.querySelectorAll<HTMLElement>(`.scroll-edge:not([${ATTR}])`);
    if (missing.length) attach(missing);
  });
  observer.observe(document.body, { childList: true, subtree: true });

  attach(document.querySelectorAll<HTMLElement>('.scroll-edge'));
  installed = true;
}
