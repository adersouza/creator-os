import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Kbd } from '@/components/ui/Kbd';
import { InvestigatePanel } from './InvestigatePanel';
import type { InvestigateMetric } from '@/hooks/useInvestigate';

interface InvestigateButtonProps {
  accountId: string | null;
  metric: InvestigateMetric;
  metricLabel: string;
  periodDays?: number | undefined;
  focusDate?: string | undefined;
  accountHandle?: string | undefined;
  /** Keyboard shortcut trigger — defaults to Cmd/Ctrl+Enter when the chart has focus. */
  hotkey?: boolean | undefined;
  className?: string | undefined;
}

/**
 * Drop-in "Investigate this" button for any chart or tile.
 * Renders an inline trigger and owns the open/closed state of the
 * InvestigatePanel. When `hotkey` is true, listens for Cmd/Ctrl+Enter
 * globally and fires the panel — intended for the primary chart on a page.
 */
export function InvestigateButton({
  accountId,
  metric,
  metricLabel,
  periodDays = 30,
  focusDate,
  accountHandle,
  hotkey = false,
  className,
}: InvestigateButtonProps) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!hotkey) return;
    const handler = (e: KeyboardEvent) => {
      const isCmd = e.metaKey || e.ctrlKey;
      if (isCmd && e.key === 'Enter') {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [hotkey]);

  return (
    <>
      <Button
        type="button"
        onClick={() => setOpen(true)}
        variant="outline"
        size="sm"
        className={className}
        aria-label={`Investigate ${metricLabel}`}
        title={hotkey ? 'Investigate (⌘↵)' : `Investigate ${metricLabel}`}
      >
        <Search data-icon="inline-start" aria-hidden="true" />
        Investigate
        {hotkey ? (
          <Kbd className="ml-1 text-[0.5rem]">
            ⌘↵
          </Kbd>
        ) : null}
      </Button>
      <InvestigatePanel
        open={open}
        onClose={() => setOpen(false)}
        accountId={accountId}
        metric={metric}
        metricLabel={metricLabel}
        periodDays={periodDays}
        focusDate={focusDate}
        accountHandle={accountHandle}
      />
    </>
  );
}
