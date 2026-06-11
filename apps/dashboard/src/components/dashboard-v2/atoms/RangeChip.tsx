import { useCallback, useEffect, useState } from 'react';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/ToggleGroup';

export type Range = '7d' | '30d' | '90d';

const RANGES: ReadonlyArray<{ value: Range; label: string }> = [
  { value: '7d', label: '7D' },
  { value: '30d', label: '30D' },
  { value: '90d', label: '90D' },
];

interface Props {
  /** Current selection. Drive this from tile-local state so each tile is independent. */
  value: Range;
  onChange: (next: Range) => void;
  /** True when the chip sits on a dark anchor tile. Switches to translucent-white surface. */
  onDark?: boolean | undefined;
  /** Optional aria-label for the segmented group. */
  ariaLabel?: string | undefined;
}

/**
 * Per-tile timeframe selector — three small segments (7D / 30D / 90D).
 * Sized + voiced to read as a tile-level control, not a page-level one,
 * so it doesn't compete with the platform pill in the topbar.
 */
export function RangeChip({ value, onChange, onDark, ariaLabel }: Props) {
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(next) => {
        if (next === '7d' || next === '30d' || next === '90d') onChange(next);
      }}
      aria-label={ariaLabel ?? 'Timeframe'}
      className={onDark ? 'border-white/15 bg-white/10' : undefined}
    >
      {RANGES.map((r) => (
        <ToggleGroupItem
          key={r.value}
          value={r.value}
          sizeVariant="sm"
        >
          {r.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

/**
 * Persist the selection per tile so the user's choice sticks across reloads.
 * Reads from localStorage on mount, falls back to the supplied default.
 * Returns a setter that mirrors useState.
 */
export function usePersistedRange(storageKey: string, defaultValue: Range = '7d'): [Range, (next: Range) => void] {
  const [value, setValue] = useState<Range>(defaultValue);

  // Hydrate from localStorage on mount (after first paint avoids SSR mismatch).
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw === '7d' || raw === '30d' || raw === '90d') setValue(raw);
    } catch {
      // localStorage may throw in private mode — silently keep default.
    }
  }, [storageKey]);

  const update = useCallback(
    (next: Range) => {
      setValue(next);
      try {
        window.localStorage.setItem(storageKey, next);
      } catch {
        // ignore quota / private-mode errors
      }
    },
    [storageKey],
  );

  return [value, update];
}

/** Convert the chip's value to the `days` number that data hooks expect. */
export function rangeToDays(r: Range): number {
  return r === '7d' ? 7 : r === '30d' ? 30 : 90;
}
