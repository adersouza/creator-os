import type { FleetMetricsState } from '@/hooks/useFleetMetrics';
import type { FleetKpiState } from '@/hooks/useFleetKpiData';

/**
 * Client-side CSV export for analytics payloads.
 *
 * Everything we need is already in memory (useFleetMetrics fetches per-account
 * aggregates + the daily series), so these helpers turn that into a blob and
 * hand it to the browser without round-tripping through a server. A proper
 * scheduled-PDF pipeline lands when the Reports backend ships; until then this
 * covers the "give me my numbers" escape hatch.
 */

function csvEscape(value: unknown): string {
  if (value == null) return '';
  const str = String(value);
  if (/[",\n]/.test(str)) return `"${str.replace(/"/g, '""')}"`;
  return str;
}

function toCsv(headers: string[], rows: unknown[][]): string {
  const lines = [headers.map(csvEscape).join(',')];
  for (const row of rows) lines.push(row.map(csvEscape).join(','));
  return `${lines.join('\n')}\n`;
}

export function buildAccountAggregatesCsv(fleet: FleetMetricsState): string {
  const headers = [
    'handle',
    'platform',
    'posts',
    'eqs',
    'reach',
    'sends',
    'saves',
    'comments',
    'likes',
    'follower_growth_pct',
  ];
  const rows = fleet.accounts.map((a) => [
    a.username ?? '',
    a.platform,
    a.posts,
    a.eqs.toFixed(2),
    a.reach,
    a.sends,
    a.saves,
    a.comments,
    a.likes,
    a.followerGrowthPct == null ? '' : a.followerGrowthPct.toFixed(2),
  ]);
  return toCsv(headers, rows);
}

export function buildDailySeriesCsv(fleet: FleetMetricsState): string {
  const headers = ['date', 'eqs', 'reach'];
  const rows = fleet.series.map((p) => [p.date, p.eqs.toFixed(2), p.reach]);
  return toCsv(headers, rows);
}

/**
 * KPI strip snapshot — one row of period-compare totals + deltas. Includes
 * IG-specific fields (profile views, website clicks, non-follower reach %)
 * and Threads-specific (reposts, quotes, replies). Useful for assembling
 * weekly client-report PDFs externally; complements the per-account roll-up
 * which doesn't carry these aggregate totals.
 */
export function buildKpiSnapshotCsv(kpi: FleetKpiState): string {
  const headers = ['metric', 'value', 'pct_delta_vs_prior'];
  const fmt = (n: number | null) =>
    n == null || !Number.isFinite(n) ? '' : n.toFixed(2);
  const rows: unknown[][] = [
    ['reach', kpi.reach, fmt(kpi.reachDelta)],
    ['total_interactions', kpi.totalInteractions, fmt(kpi.totalInteractionsDelta)],
    ['saves', kpi.saves, fmt(kpi.savesDelta)],
    ['shares', kpi.shares, fmt(kpi.sharesDelta)],
    ['threads_reposts', kpi.reposts, fmt(kpi.repostsDelta)],
    ['threads_quotes', kpi.quotes, fmt(kpi.quotesDelta)],
    ['replies', kpi.replies, fmt(kpi.repliesDelta)],
    ['link_clicks', kpi.totalClicks, fmt(kpi.totalClicksDelta)],
    ['ig_profile_views', kpi.igProfileViews, fmt(kpi.igProfileViewsDelta)],
    ['ig_website_clicks', kpi.igWebsiteClicks, fmt(kpi.igWebsiteClicksDelta)],
    ['ig_total_interactions', kpi.igTotalInteractions, fmt(kpi.igTotalInteractionsDelta)],
    [
      'ig_non_follower_reach_pct',
      fmt(kpi.igNonFollowerReachPct),
      fmt(kpi.igNonFollowerReachPctDelta),
    ],
    ['engagement_rate_pct', fmt(kpi.engagementRate), fmt(kpi.engagementRateDelta)],
    ['save_rate_pct', fmt(kpi.saveRate), fmt(kpi.saveRateDelta)],
    ['send_rate_pct', fmt(kpi.sendRate), fmt(kpi.sendRateDelta)],
  ];
  return toCsv(headers, rows);
}

export function downloadCsv(filename: string, content: string): void {
  if (typeof window === 'undefined') return;
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Give the browser a beat before revoking so Safari finalises the download.
  window.setTimeout(() => URL.revokeObjectURL(url), 4_000);
}
