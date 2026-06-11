export type TrafficState = 'crit' | 'warn' | 'ok' | 'ghost';

interface Props {
  state: TrafficState;
  className?: string | undefined;
}

const STYLE: Record<TrafficState, { background: string; borderColor: string; opacity?: number }> = {
  crit: {
    background: 'var(--color-danger)',
    borderColor: 'color-mix(in srgb, var(--color-danger) 45%, var(--color-border))',
  },
  warn: {
    background: 'var(--color-warning)',
    borderColor: 'color-mix(in srgb, var(--color-warning) 45%, var(--color-border))',
  },
  ok: {
    background: 'var(--color-success)',
    borderColor: 'color-mix(in srgb, var(--color-success) 45%, var(--color-border))',
  },
  ghost: {
    background: 'var(--color-muted)',
    borderColor: 'var(--color-border)',
    opacity: 0.72,
  },
};

export function TrafficDot({ state, className }: Props) {
  return (
    <span
      className={`inline-block size-2 rounded-full border ${className ?? ''}`}
      style={STYLE[state]}
      aria-hidden="true"
    />
  );
}
