import { Button } from '@/components/ui/Button';
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { Progress } from '@/components/ui/Progress';
import { QUEUE_TARGET_DAYS, type QueueHealthRow } from './shared';

/* =========================================================================
   QUEUE HEALTH STRIP — per-group days-of-content (real data).
   Extracted from src/pages/Calendar.tsx verbatim.
   ========================================================================= */
export function QueueHealthStrip({ rows, onFillGaps }: {
  rows: QueueHealthRow[];
  onFillGaps: (groupId: string) => void;
}) {
  if (rows.length === 0) return null;
  return (
    <NovaCard
      className="mt-4"
      eyebrow="Queue health"
      title="Days of content per group"
      action={
        <div className="text-[0.71875rem] text-muted-foreground tabular-nums">
          Target: {QUEUE_TARGET_DAYS} days
        </div>
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {rows.map((q) => {
          // Scale bar relative to target*2 so a group that's exactly on target
          // lands at 50% and going over reads as surplus, not ceiling.
          const maxBar = QUEUE_TARGET_DAYS * 2;
          const pct = Math.min(100, (q.daysOfContent / maxBar) * 100);
          const targetPct = (QUEUE_TARGET_DAYS / maxBar) * 100;
          const under = q.daysOfContent < QUEUE_TARGET_DAYS;
          return (
            <div key={q.id}>
              <div className="flex items-baseline justify-between gap-2 mb-1.5">
                <span className="flex items-center gap-1.5 text-[0.78125rem]">
                  <span className="size-1.5 rounded-full" style={{ backgroundColor: q.color }} />
                  <span className="text-foreground font-medium">{q.name}</span>
                </span>
                <span className="text-[0.75rem] tabular-nums">
                  <span
                    className="font-medium"
                    style={{ color: under ? 'var(--color-oxblood)' : 'var(--color-foreground)' }}
                  >
                    {q.daysOfContent}
                  </span>
                  <span className="text-muted-foreground"> / {QUEUE_TARGET_DAYS} days</span>
                </span>
              </div>
              <div className="relative">
                <Progress value={pct} tone={under ? 'default' : 'good'} />
                {/* Target marker */}
                <div
                  className="absolute top-[-3px] bottom-[-3px] w-px opacity-40"
                  style={{ left: `${targetPct}%`, backgroundColor: 'var(--color-foreground)' }}
                  aria-hidden="true"
                />
              </div>
              {under && (
                <Button
                  type="button"
                  onClick={() => onFillGaps(q.id)}
                  variant="ghost"
                  size="sm"
                  className="mt-1.5 px-0 text-primary hover:bg-transparent"
                >
                  Fill gaps →
                </Button>
              )}
            </div>
          );
        })}
      </div>
    </NovaCard>
  );
}
