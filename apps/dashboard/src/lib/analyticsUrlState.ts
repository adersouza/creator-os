// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

export type AnalyticsPlatform = 'all' | 'ig' | 'threads';

export type AnalyticsDateRangePreset =
  | '7d'
  | '14d'
  | '30d'
  | '90d';

export type AnalyticsDateRange =
  | { kind: 'preset'; preset: AnalyticsDateRangePreset }
  | { kind: 'custom'; start: string; end: string };

export type AnalyticsCompareMode = 'off' | 'prev' | 'year' | 'peer' | 'cohort';

export type AnalyticsBreakdown = 'format' | 'source' | 'post-type' | 'day-of-week';

export type AnalyticsTab = 'overview' | 'posts' | 'accounts' | 'audience' | 'links' | 'compare';

export interface AnalyticsState {
  tab: AnalyticsTab;
  platform: AnalyticsPlatform;
  dateRange: AnalyticsDateRange;
  compare: AnalyticsCompareMode;
  breakdown: AnalyticsBreakdown;
  cohort: string;
}

export const DATE_RANGE_PRESETS: AnalyticsDateRangePreset[] = [
  '7d',
  '14d',
  '30d',
  '90d',
];

const PRESET_SET = new Set<string>(DATE_RANGE_PRESETS);

const PLATFORM_SET = new Set<AnalyticsPlatform>(['all', 'ig', 'threads']);
const COMPARE_SET = new Set<AnalyticsCompareMode>(['off', 'prev', 'year', 'peer', 'cohort']);
const TAB_SET = new Set<AnalyticsTab>(['overview', 'posts', 'accounts', 'audience', 'links', 'compare']);
const BREAKDOWN_SET = new Set<AnalyticsBreakdown>([
  'format',
  'source',
  'post-type',
  'day-of-week',
]);

export function defaultBreakdownFor(platform: AnalyticsPlatform): AnalyticsBreakdown {
  return platform === 'threads' ? 'source' : 'format';
}

// Cohort defaults to 'all-accounts' since follower-band × niche cohorts
// require the Wave 3 anonymized opt-in pipeline.
export const DEFAULT_STATE: AnalyticsState = {
  tab: 'overview',
  platform: 'all',
  dateRange: { kind: 'preset', preset: '30d' },
  compare: 'prev',
  breakdown: 'format',
  cohort: 'all-accounts',
};

export function parseDateRange(raw: string | null): AnalyticsDateRange {
  if (!raw) return DEFAULT_STATE.dateRange;
  if (PRESET_SET.has(raw)) {
    return { kind: 'preset', preset: raw as AnalyticsDateRangePreset };
  }
  return DEFAULT_STATE.dateRange;
}

export function normalizeDateRange(range: AnalyticsDateRange): AnalyticsDateRange {
  if (range.kind === 'preset' && PRESET_SET.has(range.preset)) return range;
  return DEFAULT_STATE.dateRange;
}

export function serializeDateRange(range: AnalyticsDateRange): string {
  range = normalizeDateRange(range);
  if (range.kind === 'preset') return range.preset;
  return `${range.start}_${range.end}`;
}

export function parseState(params: URLSearchParams): AnalyticsState {
  const pRaw = params.get('p');
  const cRaw = params.get('c');
  const bRaw = params.get('b');
  const tabRaw = params.get('tab');
  const platform: AnalyticsPlatform = PLATFORM_SET.has(pRaw as AnalyticsPlatform)
    ? (pRaw as AnalyticsPlatform)
    : DEFAULT_STATE.platform;
  return {
    tab: TAB_SET.has(tabRaw as AnalyticsTab)
      ? (tabRaw as AnalyticsTab)
      : DEFAULT_STATE.tab,
    platform,
    dateRange: normalizeDateRange(parseDateRange(params.get('d'))),
    compare: COMPARE_SET.has(cRaw as AnalyticsCompareMode)
      ? (cRaw as AnalyticsCompareMode)
      : DEFAULT_STATE.compare,
    breakdown: BREAKDOWN_SET.has(bRaw as AnalyticsBreakdown)
      ? (bRaw as AnalyticsBreakdown)
      : defaultBreakdownFor(platform),
    cohort: params.get('cohort') || DEFAULT_STATE.cohort,
  };
}

export function serializeState(state: AnalyticsState): URLSearchParams {
  const out = new URLSearchParams();
  if (state.tab !== DEFAULT_STATE.tab) out.set('tab', state.tab);
  if (state.platform !== DEFAULT_STATE.platform) out.set('p', state.platform);
  const dr = serializeDateRange(state.dateRange);
  if (dr !== serializeDateRange(DEFAULT_STATE.dateRange)) out.set('d', dr);
  if (state.compare !== DEFAULT_STATE.compare) out.set('c', state.compare);
  if (state.breakdown !== defaultBreakdownFor(state.platform)) out.set('b', state.breakdown);
  if (state.cohort !== DEFAULT_STATE.cohort) out.set('cohort', state.cohort);
  return out;
}

export function useAnalyticsUrlState(): [
  AnalyticsState,
  (patch: Partial<AnalyticsState>) => void,
] {
  const [searchParams, setSearchParams] = useSearchParams();

  const state = useMemo(() => parseState(searchParams), [searchParams]);

  const update = useCallback(
    (patch: Partial<AnalyticsState>) => {
      const next = { ...state, ...patch };
      next.dateRange = normalizeDateRange(next.dateRange);
      if (patch.platform && !patch.breakdown) {
        next.breakdown = defaultBreakdownFor(patch.platform);
      }
      setSearchParams(serializeState(next), { replace: true });
    },
    [state, setSearchParams],
  );

  return [state, update];
}

export function dateRangeToDays(range: AnalyticsDateRange): number {
  if (range.kind === 'custom') {
    const start = new Date(range.start);
    const end = new Date(range.end);
    return Math.max(1, Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1);
  }
  switch (range.preset) {
    case '7d': return 7;
    case '14d': return 14;
    case '30d': return 30;
    case '90d': return 90;
    default: return 30;
  }
}

export function dateRangeLabel(range: AnalyticsDateRange): string {
  if (range.kind === 'custom') return `${range.start} → ${range.end}`;
  switch (range.preset) {
    case '7d': return 'Last 7 days';
    case '14d': return 'Last 14 days';
    case '30d': return 'Last 30 days';
    case '90d': return 'Last 90 days';
    default: return 'Last 30 days';
  }
}

export function cyclePlatform(p: AnalyticsPlatform): AnalyticsPlatform {
  const order: AnalyticsPlatform[] = ['all', 'threads', 'ig'];
  return order[(order.indexOf(p) + 1) % order.length]!;
}

export function cycleDateRange(range: AnalyticsDateRange): AnalyticsDateRange {
  if (range.kind === 'custom') return { kind: 'preset', preset: '30d' };
  const idx = DATE_RANGE_PRESETS.indexOf(range.preset);
  const next = DATE_RANGE_PRESETS[(idx + 1) % DATE_RANGE_PRESETS.length];
  return { kind: 'preset', preset: next! };
}

export function shiftDateRange(range: AnalyticsDateRange, direction: -1 | 1): AnalyticsDateRange {
  if (range.kind === 'preset') {
    return range;
  }
  const span = dateRangeToDays(range);
  const shift = span * direction * 86_400_000;
  const start = new Date(new Date(range.start).getTime() + shift);
  const end = new Date(new Date(range.end).getTime() + shift);
  const iso = (d: Date) => d.toISOString().split('T')[0]!;
  return { kind: 'custom', start: iso(start)!, end: iso(end)! };
}
