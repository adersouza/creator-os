import type React from 'react';
import { NovaStat } from '@/components/ui/NovaPrimitives';
import { formatDeltaPct } from '../shared';

export interface Kpi {
  label: string;
  value: string;
  caption: string;
  delta?: number | null | undefined;
  /** When true, show a preview badge next to the label. */
  aspirational?: boolean | undefined;
}

interface Props {
  kpis: Kpi[];
  /** When true, show DeltaPill on each KPI that has a numeric delta. */
  compareEnabled: boolean;
}

export function KpiStrip({ kpis, compareEnabled }: Props) {
  const cols = kpis.length === 6 ? 3 : 4;

  return (
    <div
      className="analytics-kpi-strip grid grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))] gap-4 xl:grid-cols-[repeat(var(--kpi-cols),minmax(0,1fr))]"
      style={{ '--kpi-cols': cols } as React.CSSProperties}
      data-count={kpis.length}
      data-cols={cols}
      role="group"
      aria-label="Analytics KPI summary"
    >
      {kpis.map((k, index) => {
        const isEmpty = k.value === '—';
        const value = isEmpty ? '0' : k.value;
        const caption = k.caption === '—' ? 'no data yet' : k.caption;
        const trend = compareEnabled && k.delta !== undefined && k.delta !== null ? {
          direction: k.delta >= 0 ? 'up' as const : 'down' as const,
          label: formatDeltaPct(k.delta, 1),
        } : undefined;
        return (
          <NovaStat
            key={k.label}
            className="min-h-32"
            data-trend={trendForDelta(k.delta)}
            data-empty={isEmpty ? 'true' : 'false'}
            aria-label={`${k.label}: ${value}`}
            label={k.label}
            value={value}
            description={caption}
            status={k.aspirational ? 'Preview' : undefined}
            trend={trend}
            variant={index === 0 ? 'hero' : 'default'}
          />
        );
      })}
    </div>
  );
}

function trendForDelta(delta: number | null | undefined): 'good' | 'warn' | 'bad' | 'neutral' {
  if (delta == null || !Number.isFinite(delta)) return 'neutral';
  if (delta >= 0) return 'good';
  if (delta <= -10) return 'bad';
  return 'warn';
}
