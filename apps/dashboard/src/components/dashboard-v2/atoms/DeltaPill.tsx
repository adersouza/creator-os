import type { ReactNode } from 'react';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';

export type DeltaTone = 'up' | 'down' | 'warn';

interface Props {
  tone: DeltaTone;
  children: ReactNode;
  /** Fixed width helper for right-column alignment in table-like rows. */
  width?: number | undefined;
  className?: string | undefined;
}

const CLASS: Record<DeltaTone, string> = {
  up: 'border-[color-mix(in_srgb,var(--color-success)_28%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-success)_10%,transparent)] text-[color:var(--color-success)]',
  down: 'border-[color-mix(in_srgb,var(--color-oxblood)_28%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-oxblood)_10%,transparent)] text-[color:var(--color-oxblood)]',
  warn: 'border-[color-mix(in_srgb,var(--color-warning)_30%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-warning)_12%,transparent)] text-[color:var(--color-warning)]',
};

export function DeltaPill({ tone, children, width, className }: Props) {
  return (
    <Badge
      tone="outline"
      className={cn('justify-center font-mono tabular-nums', CLASS[tone], className)}
      style={width ? { width, justifyContent: 'center' } : undefined}
    >
      {children}
    </Badge>
  );
}
