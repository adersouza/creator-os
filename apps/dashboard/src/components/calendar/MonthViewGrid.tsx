// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { memo, useMemo } from 'react';
import { TARGET_POSTS_PER_DAY } from '@/hooks/useCalendarPosts';
import { Button } from '@/components/ui/Button';
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { cn } from '@/lib/utils';
import { DAY_NAMES, type Post } from './shared';

/* =========================================================================
   MONTH VIEW — density heatmap.
   Extracted from src/pages/Calendar.tsx verbatim.
   ========================================================================= */
function MonthViewGridInner({ posts, weekStart, today, onDayClick }: {
  posts: Post[];
  weekStart: Date;
  today: Date;
  onDayClick: (isoDate: string) => void;
}) {
  // Build a 5×7 grid representing the month containing weekStart
  const monthStart = new Date(weekStart);
  monthStart.setDate(1);
  const firstDayOffset = (monthStart.getDay() + 6) % 7; // Mon=0
  const daysInMonth = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDayOffset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length < 35) cells.push(null);

  // Real data lookup: group the current week's posts by their actual date. Days
  // outside the current week render as "not in view" rather than fabricated
  // counts — the hook only fetches a week at a time, so we stay honest about
  // what we know. A future month-window fetch can fill in the rest.
  type GroupCount = { id: string; name: string; color: string; count: number };
  const { countsByDate, weekStartISO } = useMemo(() => {
    const map = new Map<string, GroupCount[]>();
    const iso = new Date(weekStart);
    iso.setHours(0, 0, 0, 0);
    for (const p of posts) {
      const d = new Date(iso);
      d.setDate(iso.getDate() + p.day);
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      const row = map.get(key) ?? [];
      const existing = row.find((r) => r.id === p.groupId);
      if (existing) existing.count += 1;
      else row.push({ id: p.groupId, name: p.groupName, color: p.groupColor, count: 1 });
      map.set(key, row);
    }
    return { countsByDate: map, weekStartISO: iso };
  }, [posts, weekStart]);

  const keyForMonthDay = (monthDay: number) => {
    const d = new Date(monthStart);
    d.setDate(monthDay);
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  };
  const countsFor = (monthDay: number): GroupCount[] => countsByDate.get(keyForMonthDay(monthDay)) ?? [];
  const isInCurrentWeek = (monthDay: number): boolean => {
    const d = new Date(monthStart);
    d.setDate(monthDay);
    const diffDays = Math.floor((d.getTime() - weekStartISO.getTime()) / (24 * 60 * 60 * 1000));
    return diffDays >= 0 && diffDays <= 6;
  };

  const isoFor = (monthDay: number) => {
    const d = new Date(monthStart);
    d.setDate(monthDay);
    return d.toISOString().split('T')[0]!;
  };
  const isToday = (monthDay: number) => {
    const d = new Date(monthStart);
    d.setDate(monthDay);
    return d.toDateString() === today.toDateString();
  };

  const monthLabel = monthStart.toLocaleString(undefined, { month: 'long', year: 'numeric' });
  const maxTotal = useMemo(() => {
    let max = 1;
    for (const row of countsByDate.values()) {
      let total = 0;
      for (const g of row) total += g.count;
      if (total > max) max = total;
    }
    return max;
  }, [countsByDate]);

  // Legend — unique groups present this week
  const legendGroups = useMemo(() => {
    const m = new Map<string, { id: string; name: string; color: string }>();
    for (const p of posts) {
      if (!m.has(p.groupId)) m.set(p.groupId, { id: p.groupId, name: p.groupName, color: p.groupColor });
    }
    return Array.from(m.values());
  }, [posts]);

  return (
    <NovaCard contentClassName="p-4 md:p-6" aria-labelledby="month-overview-label">
      <div className="flex items-baseline justify-between gap-3 mb-4 flex-wrap">
        <div>
          <div className="text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground mb-1.5">
            Week-loaded month map
          </div>
          <div
            id="month-overview-label"
            className="text-[0.9375rem] font-medium text-foreground tracking-[-0.01em]"
          >
            {monthLabel}
          </div>
        </div>
        <div className="flex items-center gap-3 text-[0.65625rem] text-muted-foreground uppercase tracking-[0.1em] tabular-nums flex-wrap">
          {legendGroups.map((g) => (
            <span key={g.id} className="inline-flex items-center gap-1.5">
              <span className="size-1.5 rounded-full" style={{ backgroundColor: g.color }} />
              {g.name}
            </span>
          ))}
          {legendGroups.length > 0 && (
            <span className="inline-flex items-center gap-1.5 pl-3 border-l border-border">
              <span className="size-1.5 rounded-full" style={{ backgroundColor: 'var(--color-oxblood)' }} />
              Gap
            </span>
          )}
        </div>
      </div>

      <div
        role="grid"
        aria-label={`Month overview, ${monthLabel}`}
        className="grid grid-cols-7 gap-1.5"
      >
        {DAY_NAMES.map((d) => (
          <div
            key={d}
            role="columnheader"
            tabIndex={0}
            className="text-[0.59375rem] uppercase tracking-[0.1em] text-muted-foreground text-center"
          >
            {d}
          </div>
        ))}
        {cells.map((d, i) => {
          if (d === null) {
            return <div key={i} aria-hidden="true" className="aspect-square" />;
          }
          const counts = countsFor(d);
          const total = counts.reduce((s, g) => s + g.count, 0);
          const inWeek = isInCurrentWeek(d);
          // Only flag gaps for days in the currently-loaded week — we don't
          // fabricate counts for other days anymore, so "0 posts" there just
          // means "we haven't fetched that window", not a real gap.
          const isGap = inWeek && total < TARGET_POSTS_PER_DAY;
          const today_ = isToday(d);
          const dateForLabel = new Date(monthStart);
          dateForLabel.setDate(d);
          const dayLabel = dateForLabel.toLocaleDateString(undefined, {
            weekday: 'long',
            month: 'long',
            day: 'numeric',
          });
          const statusLabel = !inWeek
            ? 'day outside current week'
            : total === 0
              ? 'empty, no posts scheduled'
              : isGap
                ? `${total} ${total === 1 ? 'post' : 'posts'}, ${TARGET_POSTS_PER_DAY - total} under target`
                : `${total} ${total === 1 ? 'post' : 'posts'}, on target`;
          return (
            <Button
              key={i}
              type="button"
              variant="ghost"
              role="gridcell"
              onClick={() => onDayClick(isoFor(d))}
              className={cn(
                "relative h-auto aspect-square rounded-md border text-left p-2 flex flex-col items-stretch justify-start hover:shadow-sm transition-[background-color,border-color,box-shadow]",
                today_
                  ? 'border-primary/45 bg-primary/5'
                  : 'border-border hover:border-input bg-card',
              )}
              aria-label={`${dayLabel}${today_ ? ', today' : ''}: ${statusLabel}`}
            >
              <div className="flex items-start justify-between">
                <span className={`text-[0.75rem] tabular-nums ${today_ ? 'font-semibold text-foreground' : 'font-normal text-foreground'}`}>
                  {d}
                </span>
                {isGap && total === 0 && (
                  <span
                    role="img"
                    className="size-1.5 rounded-full mt-1"
                    style={{ backgroundColor: 'var(--color-oxblood)' }}
                    aria-label="empty day"
                  />
                )}
              </div>

              {total > 0 ? (
                <div className="mt-auto flex flex-col gap-1">
                  <div
                    className="h-1 w-full rounded-full overflow-hidden flex"
                    style={{ backgroundColor: 'color-mix(in srgb, var(--color-ink) 4%, transparent)' }}
                  >
                    {counts.map((g) =>
                      g.count > 0 ? (
                        <div
                          key={g.id}
                          style={{
                            width: `${(g.count / maxTotal) * 100}%`,
                            backgroundColor: g.color,
                          }}
                        />
                      ) : null,
                    )}
                  </div>
                  <div className="flex items-center justify-between text-[0.59375rem] tabular-nums">
                    <span className="text-muted-foreground">{total} {total === 1 ? 'post' : 'posts'}</span>
                    {isGap && (
                      <span
                        className="text-[0.53125rem] font-semibold uppercase tracking-[0.08em]"
                        style={{ color: 'var(--color-oxblood)' }}
                      >
                        gap
                      </span>
                    )}
                  </div>
                </div>
              ) : inWeek ? (
                // This week, but no posts on this day — a real gap.
                <div className="mt-auto">
                  <span
                    className="text-[0.59375rem] font-semibold uppercase tracking-[0.1em]"
                    style={{ color: 'var(--color-oxblood)' }}
                  >
                    empty
                  </span>
                </div>
              ) : (
                // Outside the currently-loaded week — we don't know yet, so
                // show a neutral placeholder instead of falsely labeling "empty".
                <div className="mt-auto">
                  <span className="text-[0.625rem] tabular-nums text-muted-foreground">—</span>
                </div>
              )}
            </Button>
          );
        })}
      </div>

      <p className="mt-4 text-[0.75rem] text-muted-foreground leading-relaxed">
        Click any day to review the list. Bars show group composition for the loaded week; muted days are outside the current fetch window.
      </p>
    </NovaCard>
  );
}

export const MonthViewGrid = memo(MonthViewGridInner);
