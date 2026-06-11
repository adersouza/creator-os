export type Platform = 'all' | 'threads' | 'ig';

export const PLATFORMS: Array<{ id: Platform; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'threads', label: 'Threads' },
  { id: 'ig', label: 'Instagram' },
];

/** Map the Dashboard platform to useFleetMetrics' platform union. */
export function fleetPlatformFor(p: Platform): 'all' | 'threads' | 'instagram' {
  return p === 'ig' ? 'instagram' : p;
}

export function formatCompact(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, '')}K`;
  return Math.round(n).toString();
}

export function formatPct(n: number | null | undefined, digits = 0): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return `${n.toFixed(digits)}%`;
}

export function formatSignedDelta(n: number | null | undefined, digits = 1): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(digits)}`;
}

export function isTinyBaselineDelta(n: number | null | undefined): boolean {
  return n != null && Number.isFinite(n) && n > 999;
}

export function formatReachDeltaLabel(n: number | null | undefined, digits = 1): string {
  if (isTinyBaselineDelta(n)) return 'new baseline';
  return formatSignedDelta(n, digits);
}

/**
 * Minimum number of posts that must clear the EQS reach floor before we
 * trust the QWE score. Below this, a single high-engagement post can peg
 * the score at 100/10 even on a fleet that's otherwise dropping reach —
 * see useFleetMetrics.eqsQualifyingPostCount and src/lib/eqs.ts.
 */
export const MIN_QUALIFYING_POSTS_FOR_QWE = 5;

export function shouldAuditQwe(
  qweOutOfTen: number | null | undefined,
  qualityActions: number | null | undefined,
  /**
   * Posts in the current window that cleared the EQS reach floor.
   * Optional so consumers that don't have this signal yet (or are reading
   * from a pre-v6 RPC payload) keep the prior heuristic-only behavior.
   * When provided and below MIN_QUALIFYING_POSTS_FOR_QWE, audit triggers
   * regardless of the perfect-score heuristic — the sample is just too
   * thin for the score to mean anything.
   */
  eqsQualifyingPostCount?: number | null | undefined,
): boolean {
  if (qweOutOfTen == null || !Number.isFinite(qweOutOfTen)) return false;
  // Backend-driven sample-size gate. Pre-v6 RPCs leave this undefined,
  // so the heuristic below stays the only signal until the new column lands.
  if (
    eqsQualifyingPostCount != null &&
    eqsQualifyingPostCount < MIN_QUALIFYING_POSTS_FOR_QWE
  ) return true;
  if (qweOutOfTen <= 0) return false;
  // Heuristic: perfect score with very few quality actions = thin sample.
  if (qweOutOfTen >= 9.95 && (qualityActions ?? 0) < 10) return true;
  return false;
}
