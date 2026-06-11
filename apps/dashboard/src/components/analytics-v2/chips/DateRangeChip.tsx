import { useState, useRef } from 'react';
import { Calendar } from 'lucide-react';
import {
  type AnalyticsDateRange,
  type AnalyticsDateRangePreset,
  DATE_RANGE_PRESETS,
  dateRangeLabel,
} from '@/lib/analyticsUrlState';
import { Button } from '@/components/ui/Button';
import { FilterChip } from '@/components/ui/FilterChip';
import { PortalDropdown } from '@/components/ui/PortalDropdown';
import { cn } from '@/lib/utils';

const PRESET_LABELS: Record<AnalyticsDateRangePreset, string> = {
  '7d': 'Last 7 days',
  '14d': 'Last 14 days',
  '30d': 'Last 30 days',
  '90d': 'Last 90 days',
};

interface Props {
  value: AnalyticsDateRange;
  onChange: (next: AnalyticsDateRange) => void;
}

export function DateRangeChip({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const activePreset = value.kind === 'preset' ? value.preset : null;

  return (
    <>
      <FilterChip
        ref={triggerRef}
        icon={Calendar}
        onClick={() => setOpen(!open)}
        title="Cycle date range (D)"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {dateRangeLabel(value)}
      </FilterChip>
      <PortalDropdown
        open={open}
        onClose={() => setOpen(false)}
        triggerRef={triggerRef}
        className="w-64 rounded-xl border border-border bg-popover p-1 shadow-lg filter-select-menu"
      >
        {DATE_RANGE_PRESETS.map((preset) => (
          <Button
            key={preset}
            type="button"
            variant="ghost"
            size="sm"
            role="option"
            aria-selected={activePreset === preset}
            onClick={() => {
              onChange({ kind: 'preset', preset });
              setOpen(false);
            }}
            className={cn(
              'h-auto w-full justify-between px-2.5 py-1.5 text-left text-[0.8125rem] font-normal',
              activePreset === preset
                ? 'bg-muted text-foreground font-medium'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            {PRESET_LABELS[preset]}
            {activePreset === preset && <span className="text-[var(--color-oxblood)]">•</span>}
          </Button>
        ))}

      </PortalDropdown>
    </>
  );
}
