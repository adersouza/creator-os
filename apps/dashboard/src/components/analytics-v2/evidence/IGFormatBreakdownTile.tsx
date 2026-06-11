import { useIGFormatBreakdown } from "@/hooks/useIGFormatBreakdown";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatCompact } from "../shared";

interface Props {
  days: number;
  scopedAccount?: ScopedAccountLite | null | undefined;
  accountIds?: string[] | undefined;
}

export function IGFormatBreakdownTile({
  days,
  scopedAccount,
  accountIds,
}: Props) {
  const accountId =
    scopedAccount?.platform === "instagram" ? scopedAccount.id : null;
  const { formats, loading } = useIGFormatBreakdown(
    days,
    accountId,
    accountId ? undefined : accountIds,
  );

  if (loading) {
    return (
      <EvidenceCard
        state="loading"
        title="IG format breakdown"
        description="Posts × reach × QWE"
      >
        <div
          className="flex flex-col gap-3"
          role="status"
          aria-label="Loading Instagram format breakdown"
        >
          <Skeleton className="h-9 w-full rounded-lg" />
          <Skeleton className="h-9 w-full rounded-lg" />
          <Skeleton className="h-9 w-4/5 rounded-lg" />
        </div>
      </EvidenceCard>
    );
  }

  if (formats.length === 0) {
    return (
      <EvidenceCard state="empty" eyebrow="Format" title="IG format breakdown">
        <NovaEmpty
          title="No format comparison yet"
          description="Backed by Instagram post rows and content-type capture. Publish at least five IG posts in this window to compare Reels, Stories, Carousels, and Images."
        />
      </EvidenceCard>
    );
  }

  const maxQwe = Math.max(1, ...formats.map((format) => format.qwe));

  return (
    <EvidenceCard
      eyebrow="Format"
      title="IG format breakdown"
      description={`Last ${days}d · posts × reach × QWE`}
    >
      <div className="min-w-0 overflow-hidden">
        <div className="grid grid-cols-[minmax(86px,1.3fr)_minmax(42px,0.55fr)_minmax(54px,0.75fr)_minmax(96px,1.15fr)] gap-3 border-b border-border pb-2 text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground">
          <span>Format</span>
          <span className="text-right">Posts</span>
          <span className="text-right">Reach</span>
          <span>QWE distribution</span>
        </div>
        <div className="divide-y divide-border">
          {formats.map((format, index) => {
            const qwePct = Math.max(3, (format.qwe / maxQwe) * 100);
            const tone = `var(--color-chart-${(index % 6) + 1})`;
            return (
              <div
                key={format.type}
                className="grid grid-cols-[minmax(86px,1.3fr)_minmax(42px,0.55fr)_minmax(54px,0.75fr)_minmax(96px,1.15fr)] items-center gap-3 py-3 text-sm"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className="size-2.5 rounded-sm"
                    style={{ background: tone }}
                  />
                  <span className="truncate font-medium text-foreground">
                    {format.type}
                  </span>
                </div>
                <span className="text-right font-mono tabular-nums text-muted-foreground">
                  {format.posts}
                </span>
                <span className="text-right font-mono tabular-nums text-muted-foreground">
                  {formatCompact(format.avgViews)}
                </span>
                <div className="flex items-center gap-2">
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-border">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${qwePct}%`,
                        background: `linear-gradient(90deg, ${tone}, color-mix(in srgb, ${tone} 52%, var(--color-chart-2)))`,
                      }}
                    />
                  </div>
                  <span className="w-12 text-right font-mono tabular-nums text-foreground">
                    {format.qwe.toFixed(2)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </EvidenceCard>
  );
}
