// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useId } from 'react';

/**
 * Compact sparkline — raw points (low opacity) + smoothed line + filled area.
 * Endpoint dot highlighted. Tufte-ish: markers drive the eye to min/max/end.
 */
interface Props {
  points: number[];
  width?: number | undefined;
  height?: number | undefined;
  /** Stroke color CSS. Defaults to Juno oxblood. */
  color?: string | undefined;
  /** Draw small raw-point dots at 35% opacity. */
  showRawDots?: boolean | undefined;
  /** Highlight min/max + endpoint. */
  showMarkers?: boolean | undefined;
  /** Render a dashed baseline at zero, or at min when the whole series is positive. */
  showBaseline?: boolean | undefined;
  className?: string | undefined;
}

export function Sparkline({
  points,
  width = 320,
  height = 48,
  color = 'var(--color-oxblood)',
  showRawDots = true,
  showMarkers = true,
  showBaseline = false,
  className,
}: Props) {
  const gradientSeed = useId().replace(/:/g, '');
  if (points.length === 0) return null;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const step = points.length > 1 ? width / (points.length - 1) : 0;
  const ptCoords = points.map((p, i) => ({
    x: i * step,
    y: height - ((p - min) / span) * (height - 4) - 2,
  }));

  // Cubic-ish path via simple catmull-rom → bezier.
  const path = ptCoords
    .map((p, i, a) => {
      if (i === 0) return `M${p.x},${p.y}`;
      const prev = a[i - 1];
      const cpx = prev!.x + (p.x - prev!.x) / 2;
      return `C${cpx},${prev!.y} ${cpx},${p.y} ${p.x},${p.y}`;
    })
    .join(' ');

  const area = `${path} L${width},${height} L0,${height} Z`;
  const gradId = `juno-spark-${gradientSeed}`;

  const endPt = ptCoords[ptCoords.length - 1];
  const minIdx = points.indexOf(min);
  const maxIdx = points.indexOf(max);
  const baselineValue = min > 0 ? min : 0;
  const baselineY = height - ((baselineValue - min) / span) * (height - 4) - 2;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ width: '100%', height }}
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.4} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      {showBaseline ? (
        <line
          x1={0}
          x2={width}
          y1={baselineY}
          y2={baselineY}
          stroke="var(--color-muted-foreground)"
          strokeWidth={1}
          strokeDasharray="3 3"
          opacity={0.45}
        />
      ) : null}
      {showRawDots &&
        ptCoords.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={1.4} fill={color} opacity={0.35} />
        ))}
      <path d={area} fill={`url(#${gradId})`} />
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" />
      {showMarkers && (
        <>
          <circle cx={ptCoords[minIdx]!.x} cy={ptCoords[minIdx]!.y} r={2.5} fill="var(--color-warning)" />
          <circle cx={ptCoords[maxIdx]!.x} cy={ptCoords[maxIdx]!.y} r={2.5} fill={color} opacity={0.85} />
          <circle cx={endPt!.x} cy={endPt!.y} r={3} fill={color} />
        </>
      )}
    </svg>
  );
}
