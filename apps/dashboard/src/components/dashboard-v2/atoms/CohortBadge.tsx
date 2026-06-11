import { Badge } from '@/components/ui/Badge';

interface Props {
  /** 0..100 percentile. */
  percentile: number;
  label?: string | undefined;
}

export function CohortBadge({ percentile, label }: Props) {
  return (
    <Badge tone="outline" className="border-[color-mix(in_srgb,var(--color-success)_28%,var(--color-border))] bg-[color-mix(in_srgb,var(--color-success)_10%,transparent)] font-mono text-[0.625rem] text-[color:var(--color-success)]">
      P{Math.round(percentile)}
      {label ? ` · ${label}` : null}
    </Badge>
  );
}
