export function SlotIndicator({ variant }: { variant: 'slot' | 'peak' }) {
  const isPeak = variant === 'peak';
  return (
    <span
      className={`pointer-events-none inline-flex h-[18px] items-center rounded px-1.5 text-[0.5625rem] font-bold uppercase leading-none tracking-[0.12em] ${
        isPeak ? 'border-transparent text-primary-foreground' : 'border border-dashed bg-card/80'
      }`}
      style={
        isPeak
          ? {
              backgroundColor: 'var(--color-oxblood)',
              boxShadow: '0 1px 5px color-mix(in srgb, var(--color-oxblood) 26%, transparent)',
            }
          : {
              color: 'var(--color-oxblood)',
              borderColor: 'color-mix(in srgb, var(--color-oxblood) 42%, transparent)',
            }
      }
    >
      {isPeak ? 'Peak' : 'Slot'}
    </span>
  );
}

export function MagnetGuide({ y, label }: { y: number; label: string }) {
  return (
    <div
      className="pointer-events-none absolute left-0 right-0 z-20 origin-left"
      style={{ top: y }}
      aria-hidden="true"
    >
      <div
        className="h-[2px]"
        style={{
          backgroundColor: 'var(--color-gold)',
          boxShadow: '0 0 0 2px color-mix(in srgb, var(--color-gold) 18%, transparent)',
        }}
      />
      <span
        className="absolute right-1.5 -top-[9px] inline-flex h-[18px] items-center rounded px-1.5 font-mono text-[0.625rem] font-semibold tabular-nums"
        style={{
          color: 'var(--color-gold)',
          backgroundColor: 'color-mix(in srgb, var(--color-gold) 12%, var(--color-card))',
          border: '0.5px solid color-mix(in srgb, var(--color-gold) 34%, transparent)',
        }}
      >
        {label}
      </span>
    </div>
  );
}
