// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo } from 'react';
import { Badge } from '@/components/ui/Badge';
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from '@/components/ui/Skeleton';
import { useReelWatchTimeLeaders } from '@/hooks/useReelWatchTimeLeaders';
import type { DashboardScopeProps } from '../scope';

const HISTOGRAM_BARS = 14;

/**
 * Watch-time hold · 14 reels.
 *
 * Two real signals from the IG API: avg watch seconds (rescaled to 0-100
 * as a "watch-time index") and per-reel hold rate = (1 - ig_skip_rate).
 * The median bar is the sample median of these 14 reels — NOT a
 * fleet-wide cohort benchmark (we don't have one). Meta doesn't expose a
 * per-second retention curve, so this is the strongest verifiable hook
 * signal available.
 *
 * IG view only — Reels-specific signal.
 */
export function HookStrengthTile({
  scopedAccount,
  accountIds,
  groupId,
  periodDays = 30,
}: DashboardScopeProps & { periodDays?: number }) {
  const { leaders, isLoading, hasError } = useReelWatchTimeLeaders(periodDays, scopedAccount, accountIds, groupId);

  const sample = useMemo(() => leaders.slice(0, HISTOGRAM_BARS), [leaders]);
  const sampleSize = sample.length;

  const aggregateScore = useMemo(() => {
    if (sampleSize === 0) return null;
    // Avg watch in seconds → 0..100 score, capped at 100. Same formula as ribbon.
    const sum = sample.reduce((acc, r) => acc + r.avgWatchSec, 0);
    const avg = sum / sampleSize;
    return Math.min(100, Math.round((avg / 6) * 100));
  }, [sample, sampleSize]);

  const medianHold = useMemo(() => {
    const holds = sample
      .map((r) => (r.igSkipRate != null ? Math.max(0, Math.min(100, (1 - r.igSkipRate) * 100)) : null))
      .filter((v): v is number => v != null)
      .sort((a, b) => a - b);
    if (holds.length === 0) return null;
    const mid = Math.floor(holds.length / 2);
    return holds.length % 2 === 0 ? (holds[mid - 1]! + holds[mid]!) / 2 : holds[mid];
  }, [sample]);

  // For each reel: hold-rate = 1 - skip_rate (0..1), nullable.
  // Bar height: hold-rate × 100. Highlight bars below the real sample median.
  const bars = useMemo(() => {
    return sample.map((r) => {
      const hold = r.igSkipRate != null ? Math.max(0, Math.min(100, (1 - r.igSkipRate) * 100)) : null;
      return {
        id: r.id,
        hold,
        belowMedian: hold != null && medianHold != null ? hold < medianHold : false,
      };
    });
  }, [sample, medianHold]);

  const belowMedianCount = bars.filter((b) => b.belowMedian).length;
  const hasBaseline = medianHold != null;
  const aggregateTone =
    aggregateScore == null ? 'var(--color-muted-foreground)' :
    aggregateScore >= 70 ? 'var(--color-health-good)' :
    aggregateScore >= 40 ? 'var(--color-foreground)' :
    'var(--color-danger)';

  return (
    <NovaCard
      eyebrow={`Watch-time hold · ${periodDays}d`}
      title="Hook strength"
      description="Reel hold-rate and watch-time index across the latest sample."
      action={<Badge variant="outline">IG · index 0-100</Badge>}
    >
        {sampleSize > 0 && aggregateScore != null ? (
          <>
            <div className="mb-1 flex items-baseline gap-2">
              <span
                className="text-5xl font-semibold tracking-[-0.03em]"
                style={{
                  color: aggregateTone,
                }}
                title="Index · avg watch ÷ 6s × 100"
              >
                {aggregateScore}
              </span>
              <span className="font-mono text-sm text-muted-foreground">
                sample / 100
              </span>
            </div>
            <div className="mb-1 text-xs text-muted-foreground">
              Index · avg watch ÷ 6s × 100.
            </div>
            <div className="mb-3 text-sm leading-relaxed text-muted-foreground">
              {hasBaseline ? (
                <>
                  Sample median hold: <strong className="font-semibold text-foreground">{Math.round(medianHold)}</strong>{' '}
                  (median of these {bars.length} reels).
                </>
              ) : (
                'Synced Reel watch-time is available; per-reel skip-rate is still filling in.'
              )}
            </div>

            <Histogram bars={bars} medianHold={medianHold ?? null} />

            <div className="mt-3 text-xs leading-relaxed text-muted-foreground">
              <strong className="font-semibold text-foreground">
                {belowMedianCount} of {bars.length}
              </strong>{' '}
              below sample median. Avg watch{' '}
              <strong className="font-semibold text-foreground">
                {(sample.reduce((acc, r) => acc + r.avgWatchSec, 0) / Math.max(1, sampleSize)).toFixed(1)}s
              </strong>
              .{' '}
              <span className="font-mono text-[11px] opacity-80">
                Hold = 1 − ig_skip_rate · last {bars.length} sampled.
              </span>
            </div>
          </>
        ) : (
          <HookStrengthEmpty isLoading={isLoading} hasError={hasError} />
        )}
    </NovaCard>
  );
}

function Histogram({
  bars,
  medianHold,
}: {
  bars: Array<{ id: string; hold: number | null; belowMedian: boolean }>;
  medianHold: number | null;
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${HISTOGRAM_BARS}, 1fr)`,
        gap: 3,
        alignItems: 'end',
        height: 60,
        marginTop: 4,
        position: 'relative',
      }}
    >
      {medianHold != null && (
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: `${medianHold}%`,
            height: 0,
            borderTop: '1px dashed var(--color-border)',
            zIndex: 0,
            pointerEvents: 'none',
          }}
        />
      )}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: '50%',
          height: 0,
          borderTop: '1px solid color-mix(in srgb, var(--color-foreground) 18%, transparent)',
          zIndex: 0,
          pointerEvents: 'none',
        }}
      />
      {Array.from({ length: HISTOGRAM_BARS }).map((_, i) => {
        const b = bars[i];
        if (!b || b.hold == null) {
          return (
            <div
              key={i}
              style={{
                background: 'var(--color-muted)',
                border: '1px dashed var(--color-border)',
                borderRadius: 2,
                height: '20%',
                opacity: 0.5,
              }}
              title="No skip-rate captured"
            />
          );
        }
        const heightPct = Math.max(8, Math.min(100, b.hold));
        return (
          <div
            key={b.id}
            style={{
              background: b.belowMedian
                ? 'color-mix(in srgb, var(--color-danger) 72%, transparent)'
                : 'var(--color-oxblood)',
              borderRadius: 2,
              height: `${heightPct}%`,
              minHeight: 4,
              transition: 'height 0.2s ease',
              zIndex: 1,
            }}
            title={`Hold ~${Math.round(b.hold)}%`}
          />
        );
      })}
    </div>
  );
}

function HookStrengthEmpty({ isLoading, hasError }: { isLoading: boolean; hasError: boolean }) {
  if (isLoading) {
    return (
      <div className="rounded-lg border border-border bg-muted/35 p-4">
        <div className="flex items-end gap-1.5">
          {Array.from({ length: HISTOGRAM_BARS }).map((_, index) => (
            <Skeleton
              key={index}
              className="flex-1 rounded-sm"
              style={{ height: `${24 + ((index * 17) % 44)}px` }}
            />
          ))}
        </div>
        <Skeleton className="mt-4 h-3 w-2/3" />
      </div>
    );
  }

  return (
    <NovaEmpty
      title={hasError ? 'Watch-time unavailable' : 'No Reel watch-time sample yet'}
      description={
        hasError
          ? 'Refresh the dashboard to retry the Reel watch-time query.'
          : 'Synced Reels will appear here once the account has enough watch-time and skip-rate data.'
      }
    />
  );
}
