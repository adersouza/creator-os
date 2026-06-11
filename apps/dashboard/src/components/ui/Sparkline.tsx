import { useId, useMemo } from 'react';
import { cn } from '@/lib/utils';

// Single source of truth for every sparkline across the app. Each consumer
// before this file rolled its own polyline math — same algorithm copied six
// times with minor drift. This primitive matches the landing-page chart-draw
// signature (stroke-dasharray reveal, cubic-bezier(0.23, 1, 0.32, 1) per
// CLAUDE.md) and respects prefers-reduced-motion via a CSS animation.

export interface SparklineProps {
  points: number[];
  /** Stroke color. Defaults to ink (light) / warm off-white (dark) via CSS var. */
  color?: string | undefined;
  /** Optional fill under the line, usually same hue as stroke at low opacity. */
  fillOpacity?: number | undefined;
  /** Base height in px. Width fills the container. */
  height?: number | undefined;
  /** Shown when draw animation should reveal the line on mount. */
  animate?: boolean | undefined;
  /** Optional accessible label — defaults to "Trend sparkline". */
  ariaLabel?: string | undefined;
  className?: string | undefined;
  strokeWidth?: number | undefined;
}

/**
 * Hand-rolled SVG polyline — no Recharts, to keep sparklines cheap on mobile.
 * Ships with a 900ms stroke-dasharray reveal (cubic-bezier(0.23, 1, 0.32, 1))
 * when `animate` is true — shorter than the landing page's 1800ms hero chart
 * because sparklines are supporting detail, not signature motion. Flat-line
 * (all points equal) renders a center horizontal rule so the card never
 * looks broken.
 */
export function Sparkline({
  points,
  color = 'var(--color-chart-line, var(--color-ink))',
  fillOpacity = 0,
  height = 32,
  animate = true,
  ariaLabel = 'Trend sparkline',
  className,
  strokeWidth = 1.4,
}: SparklineProps) {
  const width = 120;
  const pad = 2;
  const gradientId = useId().replace(/:/g, '');

  const { polyline, area, hasRange } = useMemo(() => {
    if (!points || points.length < 2) {
      return { polyline: '', area: '', hasRange: false };
    }
    const min = Math.min(...points);
    const max = Math.max(...points);
    const range = max - min;
    const hasRange = range > 0.0001;
    const pts = points.map((v, i) => {
      const x = (i / (points.length - 1)) * (width - pad * 2) + pad;
      const y = hasRange
        ? height - pad - ((v - min) / range) * (height - pad * 2)
        : height / 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const polyline = pts.join(' ');
    // Close the polyline into a filled area by dropping back to the baseline.
    const first = `${pad},${height}`;
    const last = `${width - pad},${height}`;
    const area = `${first} ${polyline} ${last}`;
    return { polyline, area, hasRange };
  }, [points, height]);

  if (!polyline) return null;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label={ariaLabel}
      className={cn('overflow-visible', className)}
    >
      {fillOpacity > 0 && hasRange && (
        <>
          <defs>
            <linearGradient id={`spark-fill-${gradientId}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={fillOpacity} />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={area} fill={`url(#spark-fill-${gradientId})`} />
        </>
      )}
      <polyline
        points={polyline}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="dark:opacity-80"
        style={animate ? {
          // 800 is a generous overestimate of path length for a 120px width;
          // the keyframe + global reduced-motion rule in index.css handle the
          // rest. Browser clips excess dasharray automatically.
          strokeDasharray: 800,
          strokeDashoffset: 800,
          animation: 'spark-draw 900ms cubic-bezier(0.23, 1, 0.32, 1) forwards',
        } : undefined}
      />
    </svg>
  );
}
