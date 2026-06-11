import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { useReplyChainDistribution } from "@/hooks/useReplyChainDistribution";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";

interface Props {
  days: number;
  scopedAccount?: ScopedAccountLite | undefined;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
}

export function ReplyDepthDistributionTile({
  days,
  scopedAccount,
  accountIds,
  groupId,
}: Props) {
  const accountId =
    scopedAccount?.platform === "threads" && scopedAccount.id
      ? scopedAccount.id
      : null;
  const { buckets, deepThreads, hasRealData, loading } =
    useReplyChainDistribution(
      days,
      accountId,
      accountId ? undefined : accountIds,
      groupId,
    );

  if (!hasRealData && !loading) {
    return (
      <EvidenceCard
        state="empty"
        eyebrow="Threads"
        title="Reply depth distribution"
      >
        <NovaEmpty
          title="Reply depth needs more data"
          description="Reply-depth distribution needs enough synced Threads posts with max-depth metrics to produce a real histogram. It stays empty until the sample can show depth reliably."
        />
      </EvidenceCard>
    );
  }

  if (loading && buckets.length === 0) {
    return (
      <EvidenceCard
        state="loading"
        eyebrow="Threads"
        title="Reply depth distribution"
        description={`Threads · last ${days}d`}
      >
        <div
          className="flex flex-col gap-3"
          role="status"
          aria-label="Loading reply depth distribution"
        >
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-36 w-full rounded-lg" />
          <Skeleton className="h-5 w-4/5 rounded-lg" />
        </div>
      </EvidenceCard>
    );
  }

  const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
  const deepPct = total > 0 ? (deepThreads / total) * 100 : 0;

  return (
    <EvidenceCard
      eyebrow="Threads"
      title="Reply depth distribution"
      description={`Threads · last ${days}d`}
      action={
        <InvestigateButton
          accountId={accountId}
          metric="engagement"
          metricLabel="Reply depth distribution"
          periodDays={days}
        />
      }
    >
      <div className="flex flex-col gap-5">
        <div className="flex items-end justify-between gap-4">
          <div>
            <div className="text-4xl font-semibold tracking-[-0.04em] tabular-nums text-foreground">
              {deepThreads}
            </div>
            <div className="mt-1 text-sm text-muted-foreground">
              threads reached 4+ turns
            </div>
          </div>
          <div className="text-right">
            <div className="text-[0.68rem] font-medium tracking-wide text-muted-foreground uppercase">
              Deep-chain share
            </div>
            <div className="mt-1 font-mono text-[0.875rem] text-foreground tabular-nums">
              {deepPct.toFixed(1)}%
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-muted/35 px-3 py-4">
          <div className="flex h-[126px] items-end gap-2">
            {buckets.map((bucket) => {
              const height = Math.max(4, (bucket.count / max) * 100);
              const isDeep = bucket.depth === "4+ turns";
              return (
                <div
                  key={bucket.depth}
                  className="flex h-full flex-1 items-end justify-center"
                >
                  <div
                    className="w-full max-w-[42px] rounded-t-sm"
                    style={{
                      height: `${height}%`,
                      background: isDeep
                        ? "var(--color-oxblood)"
                        : "var(--color-foreground)",
                      opacity: isDeep ? 0.8 : 0.42,
                    }}
                  />
                </div>
              );
            })}
          </div>
          <div className="mt-2 grid grid-cols-5 gap-1 text-center">
            {buckets.map((bucket) => (
              <div
                key={bucket.depth}
                className="truncate text-[0.6rem] text-muted-foreground"
              >
                {bucket.depth.replace(" turns", "")}
              </div>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-5 gap-1 text-center">
          {buckets.map((bucket) => (
            <div
              key={bucket.depth}
              className="font-mono text-xs text-muted-foreground tabular-nums"
            >
              {bucket.count}
            </div>
          ))}
        </div>
      </div>
    </EvidenceCard>
  );
}
