import { useState, useRef } from 'react';
import { Users, Lock, ExternalLink } from 'lucide-react';
import { useDataContribution } from '@/hooks/useDataContribution';
import { Button } from '@/components/ui/Button';
import { FilterChip } from '@/components/ui/FilterChip';
import { PortalDropdown } from '@/components/ui/PortalDropdown';
import { cn } from '@/lib/utils';

// The four cohort slices surfaced in v1. All but 'all-accounts' target the
// anonymized follower-band × niche pipeline, so they're gated behind the
// user's opt-in state. Enabling cohort sharing in Settings → Data & Privacy
// unlocks all of them; the chart still respects k-anonymity suppression on
// the read side when a specific bucket hasn't cleared N ≥ 30 / N_users ≥ 10.
const COHORT_LABELS: Record<string, string> = {
  'all-accounts': 'All accounts',
  '10-50k-ofm': '10–50K · OFM niche',
  '10-50k-threads': '10–50K · Threads',
  '50-250k-ofm': '50–250K · OFM niche',
};

const COHORT_REQUIRES_OPT_IN: Record<string, boolean> = {
  'all-accounts': false,
  '10-50k-ofm': true,
  '10-50k-threads': true,
  '50-250k-ofm': true,
};

interface Props {
  value: string;
  onChange: (next: string) => void;
}

export function CohortChip({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const { optedIn } = useDataContribution();

  const label = COHORT_LABELS[value] ?? value;

  return (
    <>
      <FilterChip ref={triggerRef} icon={Users} chevron onClick={() => setOpen(!open)}>
        Cohort: {label}
      </FilterChip>
      <PortalDropdown
        open={open}
        onClose={() => setOpen(false)}
        triggerRef={triggerRef}
        className="w-64 rounded-xl border border-border bg-popover p-1 shadow-lg filter-select-menu"
      >
        {Object.entries(COHORT_LABELS).map(([key, lbl]) => {
          const locked = COHORT_REQUIRES_OPT_IN[key] && !optedIn;
          const available = !locked;
          return (
            <Button
              key={key}
              type="button"
              variant="ghost"
              size="sm"
              disabled={!available}
              onClick={() => {
                if (!available) return;
                onChange(key);
                setOpen(false);
              }}
              className={cn(
                'h-auto w-full justify-between px-2.5 py-1.5 text-left text-[0.8125rem] font-normal',
                value === key
                  ? 'bg-muted text-foreground font-medium'
                  : available
                    ? 'text-muted-foreground hover:bg-muted hover:text-foreground'
                    : 'text-muted-foreground/45 cursor-not-allowed',
              )}
            >
              <span className="inline-flex items-center gap-2">
                {locked && <Lock className="h-3 w-3" />}
                {lbl}
              </span>
              {value === key && <span className="text-[var(--color-oxblood)]">•</span>}
            </Button>
          );
        })}
        {!optedIn && (
          <div className="mt-1 flex items-start gap-1.5 border-t border-border px-2.5 py-2 text-[0.6875rem] text-muted-foreground">
            <Lock className="mt-0.5 h-3 w-3 shrink-0" />
            <div className="flex flex-col gap-1">
              <span>
                Cohort sharing is opt-in. Anonymized bucket aggregates only —
                never account IDs or individual posts.
              </span>
              {/* Open settings in a new tab so the user doesn't lose their
                  current analytics filter context (the audit flagged the
                  in-page navigate as disruptive). */}
              <a
                href="/settings/data"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-foreground hover:underline"
              >
                Open Settings → Data &amp; Privacy
                <ExternalLink className="h-3 w-3" />
              </a>
            </div>
          </div>
        )}
      </PortalDropdown>
    </>
  );
}
