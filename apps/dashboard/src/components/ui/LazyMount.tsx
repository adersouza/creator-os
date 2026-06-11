import { useEffect, useRef, useState, type ReactNode } from 'react';

interface LazyMountProps {
  rootMargin?: string | undefined;
  fallback?: ReactNode | undefined;
  children: ReactNode;
}

export function LazyMount({
  rootMargin = '200px 0px',
  fallback = null,
  children,
}: LazyMountProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [isMounted, setIsMounted] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
  });

  useEffect(() => {
    if (isMounted) return;
    if (typeof window === 'undefined' || !('IntersectionObserver' in window)) {
      setIsMounted(true);
      return;
    }

    const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    if (prefersReducedMotion) {
      setIsMounted(true);
      return;
    }

    const node = rootRef.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setIsMounted(true);
        observer.disconnect();
      },
      { rootMargin },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [isMounted, rootMargin]);

  return <div ref={rootRef}>{isMounted ? children : fallback}</div>;
}
