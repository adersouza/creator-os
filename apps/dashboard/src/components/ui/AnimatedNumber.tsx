import { useEffect, useRef } from 'react';
import { animate, useMotionValue } from 'motion/react';

interface Props {
  /** The numeric value to animate to. */
  value: number;
  /** Format the interpolated number — e.g. (v) => v.toLocaleString(), (v) => v.toFixed(1) + '%' */
  format?: ((v: number) => string) | undefined;
  /** Animation duration in seconds. Defaults to 0.9s (research: 600ms–1s sweet spot). */
  duration?: number | undefined;
  /** Start value — defaults to 0 for mount, or pass prior value for delta counter morph. */
  from?: number | undefined;
  className?: string | undefined;
}

/**
 * Animated number counter — spring-eased count-up on mount.
 * Research (micro_interactions_2026): "KPI numbers don't appear statically —
 * they count up from zero using spring physics. Communicates precision + freshness."
 * Respects `prefers-reduced-motion` (snaps to final).
 */
export function AnimatedNumber({ value, format, duration = 0.9, from = 0, className }: Props) {
  const motionValue = useMotionValue(from);
  const ref = useRef<HTMLSpanElement>(null);
  const fmt = format ?? ((v) => Math.round(v).toLocaleString());

  useEffect(() => {
    // Respect reduced motion — snap instantly
    const prefersReduced =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (prefersReduced) {
      motionValue.set(value);
      if (ref.current) ref.current.textContent = fmt(value);
      return;
    }

    const controls = animate(motionValue, value, {
      duration,
      ease: [0.22, 1, 0.36, 1], // spring-smooth curve per Kowalski
    });
    const unsubscribe = motionValue.on('change', (v) => {
      if (ref.current) ref.current.textContent = fmt(v);
    });
    return () => {
      controls.stop();
      unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, fmt, motionValue.set, motionValue.on, motionValue, duration]);

  return (
    <span ref={ref} className={className}>
      {fmt(from)}
    </span>
  );
}
