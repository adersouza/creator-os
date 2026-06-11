import { render, screen, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LazyMount } from './LazyMount';

let intersectionCallback: IntersectionObserverCallback | null = null;

class TestIntersectionObserver {
  readonly root = null;
  readonly rootMargin: string;
  readonly thresholds = [];

  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    intersectionCallback = callback;
    this.rootMargin = options?.rootMargin ?? '';
  }

  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  takeRecords = () => [];
}

function triggerIntersection(isIntersecting = true) {
  if (!intersectionCallback) throw new Error('IntersectionObserver was not registered');
  act(() => {
    intersectionCallback?.(
      [{ isIntersecting } as IntersectionObserverEntry],
      {} as IntersectionObserver,
    );
  });
}

afterEach(() => {
  intersectionCallback = null;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
});

describe('LazyMount', () => {
  it('keeps fallback mounted until the container intersects', () => {
    vi.stubGlobal('IntersectionObserver', TestIntersectionObserver);

    render(
      <LazyMount fallback={<div id="evidence-2">reserved anchor</div>}>
        <div>Loaded evidence</div>
      </LazyMount>,
    );

    expect(screen.getByText('reserved anchor')).toBeInTheDocument();
    expect(document.getElementById('evidence-2')).toBeInTheDocument();
    expect(screen.queryByText('Loaded evidence')).not.toBeInTheDocument();

    triggerIntersection();

    expect(screen.getByText('Loaded evidence')).toBeInTheDocument();
    expect(screen.queryByText('reserved anchor')).not.toBeInTheDocument();
  });

  it('renders eagerly for reduced-motion users', () => {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    vi.stubGlobal('IntersectionObserver', TestIntersectionObserver);

    render(
      <LazyMount fallback={<div>reserved</div>}>
        <div>Static evidence</div>
      </LazyMount>,
    );

    expect(screen.getByText('Static evidence')).toBeInTheDocument();
    expect(screen.queryByText('reserved')).not.toBeInTheDocument();
    expect(intersectionCallback).toBeNull();
  });
});
