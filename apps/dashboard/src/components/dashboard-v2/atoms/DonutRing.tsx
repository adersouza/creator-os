/**
 * Donut ring — single-stat ring with center label. Mockup #9 Scorecard pattern.
 *
 * `value` is 0..1 (0 = empty ring, 1 = full ring). The ring stroke uses
 * `tone` to pick a token color; the center label is caller-provided.
 */
type Tone = 'good' | 'ox' | 'warn' | 'crit' | 'muted';

interface Props {
  value: number;
  tone?: Tone | undefined;
  size?: number | undefined;
  label: string;
  unit?: string | undefined;
}

const TONE_VAR: Record<Tone, string> = {
  good: 'var(--color-health-good)',
  ox: 'var(--color-oxblood)',
  warn: 'var(--color-health-warn)',
  crit: 'var(--color-health-critical)',
  muted: 'var(--color-border)',
};

export function DonutRing({ value, tone = 'good', size = 76, label, unit }: Props) {
  const r = 26;
  const circumference = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  const minArc = circumference * (2 / 360);
  const arc = v > 0 ? Math.max(minArc, v * circumference) : 0;
  const dash = `${arc} ${circumference}`;

  return (
    <div className="relative inline-grid place-items-center">
      <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true">
        <circle
          cx="32"
          cy="32"
          r={r}
          fill="none"
          strokeWidth="6"
          stroke="var(--color-border)"
          strokeDasharray={v === 0 ? "2 4" : undefined}
        />
        {v > 0 ? (
          <circle
            cx="32"
            cy="32"
            r={r}
            fill="none"
            strokeWidth="6"
            strokeDasharray={dash}
            strokeLinecap="round"
            stroke={TONE_VAR[tone]}
            transform="rotate(-90 32 32)"
          />
        ) : null}
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center text-sm font-semibold tabular-nums text-foreground">
        {label}
        {unit ? <small className="block text-[0.625rem] font-medium text-muted-foreground">{unit}</small> : null}
      </div>
    </div>
  );
}
