/**
 * Few 2006 bullet chart — P25/P75 qualitative bands, oxblood measure bar,
 * high-ink target tick at P50 (or caller-provided). All values 0..100 scale.
 */
interface Props {
  /** 0–100 measure (bar length). */
  value: number;
  /** 0–100 position of the target tick. Default 50. */
  target?: number | undefined;
  /** Widen to full container. */
  fullWidth?: boolean | undefined;
  /** Stronger measure bar when the value is in the top band (P75+). */
  highlightTop?: boolean | undefined;
  /** Actual percentile breakpoints on the same 0–100 scale as value. */
  bands?: { p25: number; p50: number; p75: number; max: number } | undefined;
  /** Optional semantic color override for migrated shadcn/Nova callers. */
  measureColor?: string | undefined;
}

export function BulletChart({ value, target = 50, fullWidth = false, highlightTop = false, bands, measureColor }: Props) {
  const clamped = Math.max(0, Math.min(100, value));
  const t = Math.max(0, Math.min(100, target));
  const bandMax = bands ? Math.max(1, bands.max) : 100;
  const bandWeights = bands
    ? [
        Math.max(1, Math.min(bandMax, bands.p25)),
        Math.max(1, Math.min(bandMax, bands.p75) - Math.min(bandMax, bands.p25)),
        Math.max(1, bandMax - Math.min(bandMax, bands.p75)),
      ]
    : [25, 50, 25];
  return (
    <div
      className="relative h-4 overflow-hidden rounded-md border border-border bg-muted"
      style={fullWidth ? { width: '100%' } : undefined}
    >
      <div className="absolute inset-0 flex">
        {bandWeights.map((weight, i) => (
          <div
            key={i}
            style={{
              flex: weight,
              background:
                i === 0
                  ? 'color-mix(in srgb, var(--color-muted-foreground) 10%, transparent)'
                  : i === 1
                    ? 'color-mix(in srgb, var(--color-muted-foreground) 7%, transparent)'
                    : 'color-mix(in srgb, var(--color-muted-foreground) 4%, transparent)',
            }}
          />
        ))}
      </div>
      <div
        className="absolute left-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full"
        style={{
          width: `${clamped}%`,
          background: highlightTop
            ? measureColor ?? 'var(--color-oxblood)'
            : 'color-mix(in srgb, var(--color-oxblood) 72%, var(--color-muted-foreground))',
        }}
      />
      <div
        className="absolute top-0 h-full w-px bg-foreground"
        style={{ left: `${t}%` }}
      />
    </div>
  );
}
