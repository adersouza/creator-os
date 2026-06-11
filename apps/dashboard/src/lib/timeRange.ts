export type TimeRange =
  | '7d'
  | '14d'
  | '30d'
  | '90d'
  | { days: number }
  | { hours: number };

export type LegacyDayRange = '7' | '14' | '30' | '90';
export type TimeRangeInput = TimeRange | LegacyDayRange | number;

const DAY_PRESETS: Record<string, number> = {
  '7d': 7,
  '14d': 14,
  '30d': 30,
  '90d': 90,
  '7': 7,
  '14': 14,
  '30': 30,
  '90': 90,
};

function positiveInteger(value: number): number {
  return Math.max(1, Math.round(value));
}

export function toDays(tr: TimeRangeInput): number {
  if (tr == null) return 30;
  if (typeof tr === 'number') return positiveInteger(tr);
  if (typeof tr === 'string') return DAY_PRESETS[tr] ?? 30;
  if ('days' in tr) return positiveInteger(tr.days);
  return Math.max(1, Math.ceil(positiveInteger(tr.hours) / 24));
}

export function toHours(tr: TimeRangeInput): number {
  if (tr == null) return 720;
  if (typeof tr === 'number') return positiveInteger(tr);
  if (typeof tr === 'string') return toDays(tr) * 24;
  if ('hours' in tr) return positiveInteger(tr.hours);
  return positiveInteger(tr.days) * 24;
}

export function toLabel(tr: TimeRangeInput): string {
  if (tr == null) return '30d';
  if (typeof tr === 'number') return `${positiveInteger(tr)}d`;
  if (typeof tr === 'string') return `${toDays(tr)}d`;
  if ('hours' in tr) return `${positiveInteger(tr.hours)}h`;
  return `${positiveInteger(tr.days)}d`;
}
