
import { cn } from '@/lib/utils';

interface Sigil33Props {
  size?: number | undefined;
  className?: string | undefined;
  /** Label opacity — 0.5–0.85 for visible brand marks, 0.04–0.07 for atmospheric watermarks */
  opacity?: number | undefined;
}

/**
 * Juno33 brand sigil — concentric circles + "33" label.
 * Theme-aware: uses currentColor so it inherits from parent (ink in light, white in dark).
 */
export function Sigil33({ size = 24, className, opacity = 1 }: Sigil33Props) {
  return (
    <span
      className={cn('relative inline-flex items-center justify-center flex-shrink-0', className)}
      style={{ width: size, height: size, opacity }}
      aria-hidden="true"
    >
      <svg
        aria-hidden="true"
        width={size}
        height={size}
        viewBox="0 0 22 22"
        className="absolute inset-0"
      >
        <circle cx="11" cy="11" r="10" fill="none" stroke="currentColor" strokeWidth="0.6" opacity="0.5" />
        <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="0.6" opacity="0.85" />
      </svg>
      <span
        className="relative font-bold tracking-tight"
        style={{ fontSize: size * 0.33, letterSpacing: '-0.02em' }}
      >
        33
      </span>
    </span>
  );
}
