import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll, afterAll } from 'vitest';
import { server } from './msw';

// Stub browser APIs that jsdom doesn't ship but the app calls at import time.
// matchMedia: used by prefers-reduced-motion, prefers-color-scheme lookups.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// IntersectionObserver: motion/react + a few in-view utilities assume it.
if (!('IntersectionObserver' in window)) {
  class MockIntersectionObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return []; }
    root = null;
    rootMargin = '';
    thresholds = [];
  }
  // @ts-expect-error jsdom doesn't type this slot
  window.IntersectionObserver = MockIntersectionObserver;
}

// ResizeObserver: Radix uses it for popover positioning.
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
const ResizeObserverCtor = window.ResizeObserver ?? MockResizeObserver;
window.ResizeObserver = ResizeObserverCtor;
globalThis.ResizeObserver = ResizeObserverCtor as unknown as typeof ResizeObserver;

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());
