// Vitest global setup
import "@testing-library/jest-dom";

import.meta.env.VITE_SUPABASE_URL ??= "http://127.0.0.1:54321";
import.meta.env.VITE_SUPABASE_ANON_KEY ??= "test-anon-key";

// Ensure localStorage is available in jsdom environment.
// Some jsdom versions provide a broken localStorage stub — always override.
const store: Record<string, string> = {};
const localStoragePolyfill = {
  getItem: (key: string): string | null => store[key] ?? null,
  setItem: (key: string, value: string): void => { store[key] = String(value); },
  removeItem: (key: string): void => { delete store[key]; },
  clear: (): void => { Object.keys(store).forEach(k => delete store[k]); },
  get length(): number { return Object.keys(store).length; },
  key: (index: number): string | null => Object.keys(store)[index] ?? null,
};

Object.defineProperty(globalThis, 'localStorage', {
  value: localStoragePolyfill,
  writable: true,
  configurable: true,
});

Object.defineProperty(window, 'localStorage', {
  value: localStoragePolyfill,
  writable: true,
  configurable: true,
});

// Radix/shadcn primitives use ResizeObserver in layout effects. jsdom does not
// provide a reliable global constructor, so expose the same mock everywhere.
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const ResizeObserverCtor = window.ResizeObserver ?? ResizeObserverMock;
// @ts-expect-error jsdom does not type this slot consistently across globals.
window.ResizeObserver = ResizeObserverCtor;
globalThis.ResizeObserver = ResizeObserverCtor as unknown as typeof ResizeObserver;
