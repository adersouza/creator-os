// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useId, useMemo } from 'react';
import { Badge } from '@/components/ui/Badge';

interface Annotation {
  /** Index in the points array where the annotation marker sits. */
  index: number;
  label: string;
  tone: 'ox' | 'gold';
}

interface Props {
  points: number[];
  /** Optional second series drawn as a gold dashed line (Threads search-surface). */
  secondary?: number[] | undefined;
  annotations?: Annotation[] | undefined;
  height?: number | undefined;
  /** Caption shown beneath the chart (`SOURCE · ...`). */
  caption?: string | undefined;
}

const W = 840;

/**
 * Hero sparkline — SVG 14-day trendline with gradient fill, optional second
 * dashed line for dual-metric views (spec §3.4 Threads variant), and gold
 * annotation markers with labels.
 */
export function HeroSparkline({ points, secondary, annotations = [], height = 60, caption }: Props) {
  const uid = useId();
  const safePoints = useMemo(() => points.filter((p) => Number.isFinite(p)), [points]);
  const safeSecondary = useMemo(
    () => (secondary ?? []).filter((p) => Number.isFinite(p)),
    [secondary],
  );

  if (safePoints.length < 2) {
    return (
      <div
        className="relative w-full overflow-hidden rounded-md border border-dashed border-border bg-[color-mix(in_srgb,var(--color-foreground)_3%,transparent)]"
        style={{ height }}
      >
        <svg
          viewBox={`0 0 ${W} ${height}`}
          preserveAspectRatio="none"
          width="100%"
          height={height}
          role="img"
          aria-label="Trend baseline awaiting more history"
        >
          {[0.25, 0.5, 0.75].map((p) => (
            <line
              key={p}
              x1="0"
              x2={W}
              y1={height * p}
              y2={height * p}
              stroke="var(--color-border)"
              strokeDasharray="3 7"
              opacity="0.65"
            />
          ))}
          <path
            d={`M 0 ${height * 0.72} C ${W * 0.18} ${height * 0.42}, ${W * 0.32} ${height * 0.82}, ${W * 0.5} ${height * 0.56} S ${W * 0.82} ${height * 0.28}, ${W} ${height * 0.45}`}
            fill="none"
            stroke="var(--color-foreground)"
            strokeWidth="1.5"
            strokeLinecap="round"
            opacity="0.18"
          />
          <path
            d={`M 0 ${height * 0.82} C ${W * 0.22} ${height * 0.58}, ${W * 0.36} ${height * 0.78}, ${W * 0.55} ${height * 0.64} S ${W * 0.84} ${height * 0.46}, ${W} ${height * 0.52}`}
            fill="none"
            stroke="var(--color-gold)"
            strokeWidth="1.25"
            strokeDasharray="5 5"
            strokeLinecap="round"
            opacity="0.22"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <Badge tone="outline" className="bg-background/80">
            Awaiting trend baseline
          </Badge>
        </div>
      </div>
    );
  }

  const all = [...safePoints, ...safeSecondary];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min || 1;

  const toPath = (arr: number[]) =>
    arr
      .map((v, i) => {
        const x = (i / (arr.length - 1)) * W;
        const y = height - ((v - min) / range) * height;
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(' ');

  const primaryPath = toPath(safePoints);
  const fillPath = `${primaryPath} L${W} ${height} L0 ${height} Z`;
  const secondaryPath = safeSecondary.length >= 2 ? toPath(safeSecondary) : null;

  const endX = W;
  const endY = height - ((safePoints[safePoints.length - 1]! - min) / range) * height;

  return (
    <div className="w-full">
      <svg
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        width="100%"
        height={height}
        role="img"
        aria-label="Hero trend line"
      >
        <defs>
          <linearGradient id={`${uid}-fill`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-foreground)" stopOpacity="0.18" />
            <stop offset="100%" stopColor="var(--color-foreground)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={fillPath} fill={`url(#${uid}-fill)`} />
        <path
          d={primaryPath}
          fill="none"
          stroke="var(--color-foreground)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {secondaryPath && (
          <path
            d={secondaryPath}
            fill="none"
            stroke="var(--color-gold)"
            strokeWidth="1.25"
            strokeDasharray="4 3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {annotations.map((a, i) => {
          const x = (a.index / (safePoints.length - 1)) * W;
          const y = height - ((safePoints[a.index]! - min) / range) * height;
          const color = a.tone === 'gold' ? 'var(--color-gold)' : 'var(--color-foreground)';
          return (
            <g key={i}>
              <line x1={x} x2={x} y1={0} y2={height} stroke={color} strokeWidth="0.75" strokeDasharray="2 2" opacity="0.6" />
              <circle cx={x} cy={y} r="3" fill={color} />
              <text
                x={x + 6}
                y={12}
                fontFamily="var(--font-mono)"
                fontSize="9"
                fill={color}
                style={{ letterSpacing: '0.08em', textTransform: 'uppercase' }}
              >
                {a.label}
              </text>
            </g>
          );
        })}
        <circle cx={endX - 1} cy={endY} r="2.5" fill="var(--color-foreground)" />
      </svg>
      {caption && (
        <p className="mt-2 text-[0.6875rem] font-medium uppercase tracking-[0.12em] text-muted-foreground">
          {caption}
        </p>
      )}
    </div>
  );
}
