import { START_HOUR, END_HOUR, HOUR_HEIGHT, formatHourLabel } from './shared';

function hourInTimezone(hour: number, timeZone: string): number {
  const base = new Date();
  base.setHours(hour, 0, 0, 0);
  const parts = new Intl.DateTimeFormat(undefined, {
    timeZone,
    hour: 'numeric',
    hour12: false,
  }).formatToParts(base);
  const value = Number(parts.find((p) => p.type === 'hour')?.value ?? hour);
  return value === 24 ? 0 : value;
}

function shortZone(timeZone: string): string {
  try {
    const parts = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short', timeZone }).formatToParts(new Date());
    return parts.find((p) => p.type === 'timeZoneName')?.value || timeZone;
  } catch {
    return timeZone;
  }
}

export function TimezoneGutter({ timeZones, now }: { timeZones: string[]; now: Date }) {
  const labels: number[] = [];
  for (let h = START_HOUR; h < END_HOUR; h++) labels.push(h);

  const nowTop = ((now.getHours() + now.getMinutes() / 60) - START_HOUR) * HOUR_HEIGHT;

  return (
    <div
      className="relative grid h-full border-r border-border bg-background"
      style={{ gridTemplateColumns: `repeat(${Math.max(1, timeZones.length)}, 56px)` }}
    >
      {timeZones.map((tz, index) => (
        <div key={tz} className={index > 0 ? 'relative border-l border-border/70' : 'relative'}>
          <div className="sticky top-0 z-10 h-0">
            <div className="h-5 truncate px-1.5 pt-1 text-right text-[0.5625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {index === 0 ? 'Local' : shortZone(tz)}
            </div>
          </div>
          {labels.map((h) => (
            <div
              key={`${tz}-${h}`}
              className="absolute left-0 right-0 px-2 pt-0.5 text-right font-mono text-[0.65625rem] tabular-nums text-muted-foreground"
              style={{ top: (h - START_HOUR) * HOUR_HEIGHT - 6 }}
            >
              {formatHourLabel(index === 0 ? h : hourInTimezone(h, tz))}
            </div>
          ))}
        </div>
      ))}
      {nowTop >= 0 && nowTop <= (END_HOUR - START_HOUR) * HOUR_HEIGHT && (
        <div
          className="pointer-events-none absolute left-0 right-0 h-px"
          style={{
            top: nowTop,
            backgroundColor: 'color-mix(in srgb, var(--color-oxblood) 42%, transparent)',
          }}
          aria-hidden="true"
        />
      )}
    </div>
  );
}
