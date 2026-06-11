/**
 * Shared types + helpers for AnalyticsV2.
 * Re-exports Platform / Timeframe from analyticsShared so v1 and v2 stay
 * aligned on the same union types (segmented control values, hook args).
 */
import type { Platform, Timeframe } from '@/components/analytics/analyticsShared';

export type { Platform, Timeframe };

export type Breakdown = 'format' | 'source';
export type CompareMode = 'off' | 'prev';

export interface ShellState {
  platform: Platform;
  timeframe: Timeframe;
  compare: CompareMode;
  breakdown: Breakdown;
}

export const breakdownDefaultFor: Record<Platform, Breakdown> = {
  all: 'format',
  ig: 'format',
  threads: 'source',
};

export const windowDaysFor: Record<Timeframe, number> = {
  '7': 7,
  '30': 30,
  '90': 90,
};

export const timeframeLabelFor: Record<Timeframe, string> = {
  '7': 'Last 7 days',
  '30': 'Last 30 days',
  '90': 'Last 90 days',
};

export function formatInt(n: number): string {
  return new Intl.NumberFormat('en-US').format(Math.round(n));
}

export function formatCompact(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—';
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, '')}K`;
  return Math.round(n).toString();
}

export function formatDeltaPct(pct: number | null | undefined, digits = 1): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return '—';
  const sign = pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(digits)}%`;
}
