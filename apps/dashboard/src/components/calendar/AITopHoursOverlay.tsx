import { HOUR_HEIGHT, START_HOUR } from './shared';

export function AITopHoursOverlay({ hours }: { hours: number[] }) {
  return (
    <>
      {hours.map((h, index) => (
        <div
          key={`ai-hour-${h}`}
          className="absolute left-0 right-0 pointer-events-none"
          style={{
            top: (h - START_HOUR) * HOUR_HEIGHT,
            height: HOUR_HEIGHT,
            backgroundColor:
              index < 3
                ? 'color-mix(in srgb, var(--color-oxblood) 6%, transparent)'
                : 'color-mix(in srgb, var(--color-gold) 4%, transparent)',
          }}
          aria-hidden="true"
        />
      ))}
    </>
  );
}
