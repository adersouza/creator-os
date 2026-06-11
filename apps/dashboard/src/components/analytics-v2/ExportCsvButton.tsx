import { useState, useRef } from 'react';
import { Download } from 'lucide-react';
import type { FleetMetricsState } from '@/hooks/useFleetMetrics';
import type { FleetKpiState } from '@/hooks/useFleetKpiData';
import { Button } from '@/components/ui/Button';
import { FilterChip } from '@/components/ui/FilterChip';
import { PortalDropdown } from '@/components/ui/PortalDropdown';
import {
  buildAccountAggregatesCsv,
  buildDailySeriesCsv,
  buildKpiSnapshotCsv,
  downloadCsv,
} from '@/services/analyticsCsv';

interface Props {
  fleet: FleetMetricsState;
  /** Period-compare KPI totals (incl. IG-specific fields). Optional so older
   *  callers without `useFleetKpiData` access still work. */
  kpi?: FleetKpiState | undefined;
  /** Used to namespace the filename. */
  scopeLabel: string;
}

/**
 * Lightweight CSV export trigger for the current Analytics view. Backed by
 * services/analyticsCsv.ts which serializes whatever's already in memory —
 * no server round-trip. Two outputs: per-account aggregates, and daily
 * series. Renders disabled while fleet metrics are still loading so the
 * download never ships an empty CSV.
 */
export function ExportCsvButton({ fleet, kpi, scopeLabel }: Props) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const ts = new Date().toISOString().slice(0, 10);
  const slug = scopeLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'fleet';

  const exportAccounts = () => {
    if (fleet.isLoading || fleet.accounts.length === 0) return;
    downloadCsv(`juno33-accounts-${slug}-${ts}.csv`, buildAccountAggregatesCsv(fleet));
    setOpen(false);
  };

  const exportSeries = () => {
    if (fleet.isLoading || fleet.series.length === 0) return;
    downloadCsv(`juno33-daily-${slug}-${ts}.csv`, buildDailySeriesCsv(fleet));
    setOpen(false);
  };

  const exportKpi = () => {
    if (!kpi || kpi.isLoading) return;
    downloadCsv(`juno33-kpis-${slug}-${ts}.csv`, buildKpiSnapshotCsv(kpi));
    setOpen(false);
  };

  const disabled =
    fleet.isLoading || (fleet.accounts.length === 0 && fleet.series.length === 0);

  return (
    <>
      <FilterChip
        ref={triggerRef}
        icon={Download}
        onClick={() => setOpen((v) => !v)}
        title="Export CSV"
        disabled={disabled}
      >
        Export
      </FilterChip>
      <PortalDropdown
        open={open}
        onClose={() => setOpen(false)}
        triggerRef={triggerRef}
        className="w-56 rounded-xl border border-border bg-popover p-1 shadow-lg"
      >
        <Item
          label="Per-account rollup"
          hint={`${fleet.accounts.length} account${fleet.accounts.length === 1 ? '' : 's'}`}
          onClick={exportAccounts}
          disabled={fleet.accounts.length === 0}
        />
        <Item
          label="Daily reach + EQS"
          hint={`${fleet.series.length} day${fleet.series.length === 1 ? '' : 's'}`}
          onClick={exportSeries}
          disabled={fleet.series.length === 0}
        />
        {kpi ? (
          <Item
            label="KPI snapshot (period totals)"
            hint="incl. IG fields"
            onClick={exportKpi}
            disabled={kpi.isLoading}
          />
        ) : null}
      </PortalDropdown>
    </>
  );
}

function Item({
  label,
  hint,
  onClick,
  disabled,
}: {
  label: string;
  hint: string;
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      disabled={disabled}
      variant="ghost"
      size="sm"
      className="h-auto w-full justify-between px-2.5 py-1.5 text-left text-[0.8125rem] normal-case tracking-normal disabled:text-muted-foreground"
    >
      <span>{label}</span>
      <span className="text-[0.625rem] font-mono text-muted-foreground tabular-nums">
        {hint}
      </span>
    </Button>
  );
}
