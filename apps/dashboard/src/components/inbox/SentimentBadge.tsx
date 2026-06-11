import { cn } from '@/lib/utils';
import { sentimentColor, sentimentLabel } from './helpers';
import type { Sentiment } from './types';

export function SentimentBadge({ sentiment, compact }: { sentiment?: Sentiment | undefined; compact?: boolean | undefined }) {
  const label = sentimentLabel(sentiment);
  return (
    <span
      className={cn(
        'inline-flex items-center rounded font-semibold uppercase tracking-[0.08em]',
        compact ? 'px-1 text-[0.5625rem]' : 'px-1.5 py-0.5 text-[0.625rem]',
      )}
      style={{
        background:
          label === 'negative'
            ? 'color-mix(in srgb, var(--color-negative) 10%, transparent)'
            : label === 'positive'
              ? 'color-mix(in srgb, var(--color-gold) 12%, transparent)'
              : 'color-mix(in srgb, var(--color-muted-foreground) 12%, transparent)',
        color: sentimentColor(label),
      }}
    >
      {label}
    </span>
  );
}
