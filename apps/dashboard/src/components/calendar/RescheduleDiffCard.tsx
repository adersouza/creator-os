import { useEffect, useMemo, useState } from 'react';
import { RotateCcw, X } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Progress } from '@/components/ui/Progress';

export interface RescheduleDiffEntry {
  id: string;
  postId: string;
  title: string;
  account: string;
  prevScheduledAt: string | null;
  newScheduledAt: string | null;
}

export interface RescheduleDiffBatch {
  batchId: string;
  reason: string;
  createdAt: string;
  entries: RescheduleDiffEntry[];
}

function formatDateTime(iso: string | null): string {
  if (!iso) return 'Draft';
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export function RescheduleDiffCard({
  batch,
  onUndo,
  onClose,
}: {
  batch: RescheduleDiffBatch;
  onUndo: () => Promise<void>;
  onClose: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, []);

  const remaining = Math.max(0, 30_000 - (now - new Date(batch.createdAt).getTime()));
  const canUndo = remaining > 0 && !busy;
  const progress = useMemo(() => Math.max(0, Math.min(100, (remaining / 30_000) * 100)), [remaining]);

  return (
    <aside
      className="fixed bottom-6 right-6 z-[70] w-[420px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-border bg-card shadow-2xl"
    >
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-foreground">
            {batch.entries.length} rescheduled
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">{batch.reason}</div>
        </div>
        <Button type="button" variant="ghost" size="icon" aria-label="Dismiss reschedule diff" onClick={onClose}>
          <X aria-hidden="true" />
        </Button>
      </div>

      <div className="max-h-64 overflow-y-auto">
        {batch.entries.slice(0, 8).map((entry) => (
          <div key={entry.id} className="grid grid-cols-[1fr_auto] gap-3 border-b border-border px-4 py-2.5 last:border-b-0">
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-foreground">{entry.title}</div>
              <div className="text-[0.6875rem] text-muted-foreground">{entry.account}</div>
            </div>
            <div className="text-right font-mono text-[0.6875rem] text-muted-foreground">
              {formatDateTime(entry.prevScheduledAt)}
              <span className="px-1 text-muted-foreground">→</span>
              {formatDateTime(entry.newScheduledAt)}
            </div>
          </div>
        ))}
      </div>

      <div className="px-4 py-3">
        <Progress className="mb-3" value={progress} />
        <Button
          type="button"
          disabled={!canUndo}
          onClick={async () => {
            setBusy(true);
            try {
              await onUndo();
            } finally {
              setBusy(false);
            }
          }}
          className="w-full"
        >
          <RotateCcw data-icon="inline-start" />
          {remaining > 0 ? `Undo ${Math.ceil(remaining / 1000)}s` : 'Undo expired'}
        </Button>
      </div>
    </aside>
  );
}
