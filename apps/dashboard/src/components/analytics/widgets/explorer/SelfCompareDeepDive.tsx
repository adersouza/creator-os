
import { ArrowRight, Minus, Scale, TrendingDown, TrendingUp } from 'lucide-react';
import type { FleetMetricsState } from '@/hooks/useFleetMetrics';
import { formatCompact } from '@/components/analytics/analyticsShared';
import { Badge } from '@/components/ui/Badge';
import { NovaCard, NovaEmpty } from '@/components/ui/NovaPrimitives';
import { Skeleton } from '@/components/ui/Skeleton';

interface CompareRow {
  metric: string;
  current: string;
  previous: string;
  deltaLabel: string;
  trend: 'up' | 'down' | 'flat';
  currentWidth: number;
  previousWidth: number;
}

function toTrend(delta: number | null): 'up' | 'down' | 'flat' {
  if (delta == null || delta === 0) return 'flat';
  return delta > 0 ? 'up' : 'down';
}

function barWidths(cur: number, prev: number | null): { currentWidth: number; previousWidth: number } {
  if (prev == null || prev <= 0) return { currentWidth: 60, previousWidth: 40 };
  const max = Math.max(cur, prev, 1);
  return {
    currentWidth: Math.round((cur / max) * 70) + 10,
    previousWidth: Math.round((prev / max) * 70) + 10,
  };
}

function buildRows(live: FleetMetricsState): CompareRow[] {
  const eqsPrev = live.eqsDelta != null ? live.eqs - live.eqsDelta : null;
  const reachPrev = live.reachDeltaPct != null ? live.totalReach / (1 + live.reachDeltaPct / 100) : null;
  const spsPrev = live.sendsPlusSavesDeltaPct != null ? live.sendsPlusSaves / (1 + live.sendsPlusSavesDeltaPct / 100) : null;
  const compPrev =
    live.scheduleCompliance != null && live.scheduleComplianceDelta != null
      ? live.scheduleCompliance - live.scheduleComplianceDelta
      : null;

  return [
    {
      metric: 'EQS',
      current: live.eqs > 0 ? live.eqs.toFixed(1) : '—',
      previous: eqsPrev != null ? eqsPrev.toFixed(1) : '—',
      deltaLabel:
        live.eqsDelta != null
          ? `${live.eqsDelta >= 0 ? '+' : ''}${live.eqsDelta.toFixed(1)} pts`
          : '—',
      trend: toTrend(live.eqsDelta),
      ...barWidths(live.eqs, eqsPrev),
    },
    {
      metric: 'Total Reach',
      current: live.totalReach > 0 ? formatCompact(live.totalReach) : '—',
      previous: reachPrev != null ? formatCompact(reachPrev) : '—',
      deltaLabel:
        live.reachDeltaPct != null
          ? `${live.reachDeltaPct >= 0 ? '+' : ''}${Math.round(live.reachDeltaPct)}%`
          : '—',
      trend: toTrend(live.reachDeltaPct),
      ...barWidths(live.totalReach, reachPrev),
    },
    {
      metric: 'Sends + Saves',
      current: live.sendsPlusSaves > 0 ? formatCompact(live.sendsPlusSaves) : '—',
      previous: spsPrev != null ? formatCompact(spsPrev) : '—',
      deltaLabel:
        live.sendsPlusSavesDeltaPct != null
          ? `${live.sendsPlusSavesDeltaPct >= 0 ? '+' : ''}${Math.round(live.sendsPlusSavesDeltaPct)}%`
          : '—',
      trend: toTrend(live.sendsPlusSavesDeltaPct),
      ...barWidths(live.sendsPlusSaves, spsPrev),
    },
    {
      metric: 'Schedule Rate',
      current: live.scheduleCompliance != null ? `${live.scheduleCompliance.toFixed(0)}%` : '—',
      previous: compPrev != null ? `${compPrev.toFixed(0)}%` : '—',
      deltaLabel:
        live.scheduleComplianceDelta != null
          ? `${live.scheduleComplianceDelta >= 0 ? '+' : ''}${live.scheduleComplianceDelta.toFixed(0)}pp`
          : '—',
      trend: toTrend(live.scheduleComplianceDelta),
      ...barWidths(live.scheduleCompliance ?? 0, compPrev),
    },
  ];
}

export function SelfCompareDeepDive({ live }: { live: FleetMetricsState }) {
  const hasData = !live.isLoading && live.postCount > 0;
  const rows = hasData ? buildRows(live) : [];

  return (
    <NovaCard variant="compact" contentClassName="p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2 text-[0.8125rem] font-semibold text-foreground">
          <Scale data-icon="inline-start" className="text-primary" aria-hidden="true" />
          Period Comparison
        </div>
        <div className="flex gap-2 text-[0.59375rem] font-semibold uppercase tracking-[0.1em]">
          <Badge tone="secondary">Prior</Badge>
          <span className="text-muted-foreground mt-0.5">→</span>
          <Badge tone="outline">Current</Badge>
        </div>
      </div>

      {live.isLoading ? (
        <div className="flex flex-col gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton className="h-3 w-20 rounded-full" />
              <Skeleton className="h-5 flex-1 rounded-md" />
            </div>
          ))}
        </div>
      ) : !hasData ? (
        <NovaEmpty
          className="min-h-24 p-4"
          title="No comparison yet"
          description="Publish posts to unlock period comparison."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {rows.map((row) => (
            <div key={row.metric} className="flex flex-col gap-1.5 p-3 rounded-lg border border-border bg-muted/20">
              <div className="flex items-center justify-between">
                <span className="text-[0.71875rem] font-medium text-foreground">{row.metric}</span>
                <div
                  className={`flex items-center gap-1 text-[0.65625rem] font-semibold tabular-nums ${
                    row.trend === 'up'
                      ? 'text-[color:var(--color-health-good)]'
                      : row.trend === 'down'
                      ? 'text-[color:var(--color-oxblood)]'
                      : 'text-muted-foreground'
                  }`}
                >
                  {row.trend === 'up' && <TrendingUp data-icon="inline-start" aria-hidden="true" />}
                  {row.trend === 'down' && <TrendingDown data-icon="inline-start" aria-hidden="true" />}
                  {row.trend === 'flat' && <Minus data-icon="inline-start" aria-hidden="true" />}
                  {row.deltaLabel}
                </div>
              </div>
              <div className="grid grid-cols-[1fr_auto_1fr] gap-2 items-center">
                <div className="h-5 rounded-md bg-muted relative overflow-hidden flex items-center justify-end px-2">
                  <div
                    className="absolute inset-y-0 right-0 bg-muted-foreground/10 rounded-md"
                    style={{ width: `${row.previousWidth}%` }}
                  />
                  <span className="relative text-[0.625rem] font-mono text-muted-foreground z-10">
                    {row.previous}
                  </span>
                </div>
                <ArrowRightIcon />
                <div
                  className="h-5 rounded-md relative overflow-hidden flex items-center justify-start px-2 border"
                  style={{
                    backgroundColor: 'color-mix(in srgb, var(--color-oxblood) 8%, transparent)',
                    borderColor: 'color-mix(in srgb, var(--color-oxblood) 20%, transparent)',
                  }}
                >
                  <div
                    className="absolute inset-y-0 left-0 rounded-md"
                    style={{
                      width: `${row.currentWidth}%`,
                      backgroundColor: 'color-mix(in srgb, var(--color-oxblood) 20%, transparent)',
                    }}
                  />
                  <span
                    className="relative text-[0.625rem] font-mono font-semibold z-10"
                    style={{ color: 'var(--color-oxblood)' }}
                  >
                    {row.current}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </NovaCard>
  );
}

function ArrowRightIcon() {
  return <ArrowRight data-icon="inline-start" className="shrink-0 text-muted-foreground" aria-hidden="true" />;
}
