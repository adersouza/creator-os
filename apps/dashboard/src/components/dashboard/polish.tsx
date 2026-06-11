// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Polish primitives — shared visual vocabulary for the Juno33 dashboard.
 *
 * These read from design tokens so they respect light + dark mode without
 * inline theme math in each widget. The rules the reference mocks settled
 * on:
 *   whisper  var(--color-oxblood)      text, delta chips, inline highlights
 *   bar      var(--color-oxblood-bar)  progress fills, CTAs, KPI bars
 *   tracks   color-mix of the foreground so the rail reads on cream + ink
 *   pills    semantic bg from var(--color-*) mixed at ~14%, fg at full
 *
 * Do not hardcode hex colors inside these components — every fallback has
 * a token equivalent. See DESIGN_BIBLE.md for the wider system.
 */

import type React from 'react';

export type PillTone = 'crit' | 'hot' | 'warn' | 'good' | 'neutral';

const PILL_COLOR: Record<PillTone, { fg: string; bg: string }> = {
  crit: {
    fg: 'var(--color-oxblood)',
    bg: 'color-mix(in srgb, var(--color-oxblood) 14%, transparent)',
  },
  hot: {
    // Decoupled from `crit` 2026-04-28: was identical (both oxblood), so
    // positive-signal pills read as failures. `hot` = positive, sage.
    fg: 'var(--color-health-good)',
    bg: 'color-mix(in srgb, var(--color-health-good) 16%, transparent)',
  },
  warn: {
    fg: 'var(--color-gold)',
    bg: 'color-mix(in srgb, var(--color-gold) 14%, transparent)',
  },
  good: {
    fg: 'var(--color-health-good)',
    bg: 'color-mix(in srgb, var(--color-health-good) 12%, transparent)',
  },
  neutral: {
    fg: 'var(--color-label-secondary)',
    bg: 'var(--color-secondary)',
  },
};

export function StatusPill({
  tone = 'neutral',
  children,
}: {
  tone?: PillTone | undefined;
  children: React.ReactNode;
}) {
  const { fg, bg } = PILL_COLOR[tone];
  return (
    <span
      className="inline-flex items-center gap-1 h-[22px] px-2.5 rounded-full text-[0.625rem] font-semibold uppercase tabular-nums"
      style={{ color: fg, backgroundColor: bg, letterSpacing: '0.06em' }}
    >
      {children}
    </span>
  );
}

export function DeltaPill({
  value,
  tone = 'hot',
}: {
  value: string;
  tone?: PillTone | undefined;
}) {
  const { fg, bg } = PILL_COLOR[tone];
  return (
    <span
      className="inline-flex items-center h-[18px] px-1.5 rounded-md text-[0.625rem] font-semibold tabular-nums"
      style={{ color: fg, backgroundColor: bg }}
    >
      {value}
    </span>
  );
}

/** Small eyebrow label — uppercase, tight tracking, quaternary tone. */
export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[0.625rem] font-semibold uppercase tracking-[0.14em] text-label-quaternary">
      {children}
    </div>
  );
}

/* --------------------------------------------------------------------------
   AccountAvatar — deterministic gradient circle keyed on handle hash.
   -------------------------------------------------------------------------- */

const AVATAR_PAIRS: [string, string][] = [
  ['#fb7185', '#f59e0b'],
  ['#8b5cf6', '#ec4899'],
  ['#f97316', '#facc15'],
  ['#be123c', '#ef4444'],
  ['#7c3aed', '#22d3ee'],
  ['#f43f5e', '#9f1239'],
  ['#ea580c', '#fb7185'],
  ['#a855f7', '#60a5fa'],
  ['#dc2626', '#7c2d12'],
  ['#c026d3', '#fb7185'],
];

function avatarPairFor(seed: string): [string, string] {
  let h = 0;
  for (let i = 0; i < seed.length; i += 1) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_PAIRS[h % AVATAR_PAIRS.length]!;
}

export function AccountAvatar({
  handle,
  size = 28,
  rounded = 'full',
}: {
  handle: string;
  size?: number | undefined;
  rounded?: 'md' | 'full' | undefined;
}) {
  const seed = handle.trim().replace(/^@/, '') || 'unknown';
  const [a, b] = avatarPairFor(seed);
  return (
    <span
      aria-hidden="true"
      className={`shrink-0 inline-block ${rounded === 'full' ? 'rounded-full' : 'rounded-lg'}`}
      style={{
        width: size,
        height: size,
        background: `radial-gradient(circle at 30% 25%, ${a}, ${b} 80%)`,
      }}
    />
  );
}

/* --------------------------------------------------------------------------
   RowBar — inline percentile bar used in leaderboard rows.
   Track = muted foreground, fill = oxblood-bar gradient, tick = foreground.
   -------------------------------------------------------------------------- */

export function RowBar({
  fill,
  median = 50,
}: {
  fill: number; // 0..100
  median?: number | undefined; // 0..100
}) {
  return (
    <div
      className="relative h-[5px] rounded-full overflow-hidden"
      style={{
        backgroundColor: 'color-mix(in srgb, var(--color-label-tertiary) 22%, transparent)',
      }}
    >
      <div
        className="absolute inset-y-0 left-0"
        style={{
          width: `${Math.min(100, Math.max(0, fill))}%`,
          background: `linear-gradient(90deg, color-mix(in srgb, var(--color-oxblood-bar) 55%, transparent), var(--color-oxblood-bar))`,
        }}
      />
      <div
        className="absolute inset-y-[-1px] w-[1.5px]"
        style={{
          left: `calc(${median}% - 0.75px)`,
          backgroundColor: 'var(--color-foreground)',
          opacity: 0.75,
        }}
      />
    </div>
  );
}

/** Percentile bar with P25/P50/P75/P90 labels + tick marker. */
export function PercentileBar({
  value,
  p25,
  p50,
  p75,
  p90,
  unit = '',
}: {
  value: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  unit?: string | undefined;
}) {
  const min = p25 * 0.6;
  const max = p90 * 1.1;
  const pct = Math.min(1, Math.max(0, (value - min) / (max - min)));
  return (
    <div className="w-full">
      <div
        className="relative h-[6px] rounded-full overflow-hidden mb-1.5"
        style={{
          backgroundColor: 'color-mix(in srgb, var(--color-label-tertiary) 22%, transparent)',
        }}
      >
        <div
          className="absolute inset-y-0 left-0"
          style={{
            width: `${pct * 100}%`,
            background: `linear-gradient(90deg, color-mix(in srgb, var(--color-oxblood-bar) 45%, transparent), var(--color-oxblood-bar))`,
          }}
        />
        <div
          className="absolute inset-y-[-2px] w-[2px] rounded-sm"
          style={{
            left: `calc(${pct * 100}% - 1px)`,
            backgroundColor: 'var(--color-foreground)',
          }}
        />
      </div>
      <div className="flex justify-between text-[0.625rem] text-label-quaternary tabular-nums">
        <span>P25 · {p25}{unit}</span>
        <span>P50 · {p50}{unit}</span>
        <span>P75 · {p75}{unit}</span>
        <span>P90 · {p90}{unit}</span>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------
   Sparkline — lightweight trend line for hero cards.
   -------------------------------------------------------------------------- */

export function Sparkline({
  points,
  color = 'var(--color-oxblood-bar)',
  height = 40,
}: {
  points: number[];
  color?: string | undefined;
  height?: number | undefined;
}) {
  if (points.length < 2) return null;
  const w = 320;
  const h = height;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const d = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 6) - 3;
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height={h}
      preserveAspectRatio="none"
      role="img"
      aria-label="Trend sparkline"
    >
      <title>Trend sparkline</title>
      <defs>
        <linearGradient id="polish-spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.18" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${d} L ${w} ${h} L 0 ${h} Z`} fill="url(#polish-spark-fill)" />
      <path d={d} fill="none" stroke={color} strokeWidth="1.75" strokeLinecap="round" />
      <circle
        cx={w - 1}
        cy={h - ((points[points.length - 1]! - min) / range) * (h - 6) - 3}
        r="2.5"
        fill={color}
      />
    </svg>
  );
}

/* --------------------------------------------------------------------------
   Card shells — editorial layout helpers.
   -------------------------------------------------------------------------- */

export function PanelHeader({
  label,
  title,
  badge,
  action,
}: {
  label: string;
  title?: React.ReactNode | undefined;
  badge?: React.ReactNode | undefined;
  action?: React.ReactNode | undefined;
}) {
  return (
    <div className="flex items-start justify-between gap-3 mb-3">
      <div className="min-w-0">
        <SectionLabel>{label}</SectionLabel>
        {title && (
          <div className="text-[0.9375rem] font-medium text-foreground mt-1 tracking-[-0.005em]">
            {title}
          </div>
        )}
      </div>
      <div className="shrink-0 flex items-center gap-1.5">
        {badge}
        {action}
      </div>
    </div>
  );
}
