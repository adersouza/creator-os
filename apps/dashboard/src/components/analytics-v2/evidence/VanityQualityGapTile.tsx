import { useVanityAccounts } from "@/hooks/useVanityAccounts";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";

interface Props {
  days?: number | undefined;
  scopedAccount?: ScopedAccountLite | undefined;
  accountIds?: string[] | undefined;
}

function normalizedDays(days: number): 7 | 30 | 90 {
  if (days <= 7) return 7;
  if (days >= 90) return 90;
  return 30;
}

export function VanityQualityGapTile({
  days = 30,
  scopedAccount,
  accountIds,
}: Props) {
  const accountId =
    scopedAccount?.platform === "instagram" ? scopedAccount.id : null;
  const { accounts, fleetAvgRatio, hasRealData, loading } = useVanityAccounts(
    normalizedDays(days),
    accountId,
    accountId ? undefined : accountIds,
  );
  const top = accounts[0] ?? null;
  const quality = top ? top.sends + top.saves : 0;

  if ((!hasRealData || !top) && !loading) {
    return (
      <EvidenceCard
        state="empty"
        eyebrow="Quality"
        title="Quality action gap"
        description="Healthy"
      >
        <NovaEmpty
          title="No quality-action gap"
          description={`No account crossed the likes-heavy, saves-and-sends-light threshold in the last ${days} days. This tile only opens when passive likes materially outpace quality actions.`}
        />
      </EvidenceCard>
    );
  }

  if (loading && !top) {
    return (
      <EvidenceCard
        state="loading"
        eyebrow="Quality"
        title="Quality action gap"
        description={`IG · likes vs sends+saves · ${days}d`}
      >
        <div
          className="flex flex-col gap-3"
          role="status"
          aria-label="Loading quality action gap"
        >
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-12 w-full rounded-lg" />
          <Skeleton className="h-24 w-full rounded-lg" />
        </div>
      </EvidenceCard>
    );
  }

  const ratio = top?.ratio ?? 0;
  const alert = ratio > Math.max(20, fleetAvgRatio * 2);

  return (
    <EvidenceCard
      eyebrow="Quality"
      title="Quality action gap"
      description={`IG · likes vs sends+saves · ${days}d`}
      action={
        <InvestigateButton
          accountId={top?.accountId ?? null}
          metric="engagement"
          metricLabel="Quality action gap"
          periodDays={days}
        />
      }
    >
      <div className="flex flex-col gap-4">
        <div>
          <div
            className="text-4xl font-semibold tracking-[-0.04em] tabular-nums text-foreground"
            style={{
              color: alert ? "var(--color-oxblood)" : "var(--color-foreground)",
            }}
          >
            {ratio.toFixed(1)}x
          </div>
          <div className="mt-1 text-sm text-muted-foreground">
            likes per quality action
          </div>
        </div>

        <div className="rounded-lg border border-border bg-muted/35 px-3 py-2">
          <div className="text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground">
            {top?.handle ?? "Top account"}
          </div>
          <div className="mt-1 text-sm text-muted-foreground">
            Fleet baseline {fleetAvgRatio}:1
          </div>
        </div>

        {top ? (
          <div className="flex flex-col gap-2">
            <VanityBar
              label="Likes"
              value={top.likes}
              max={top.likes}
              color="var(--color-chart-ink)"
            />
            <VanityBar
              label="Sends"
              value={top.sends}
              max={top.likes}
              color="var(--color-muted-foreground)"
            />
            <VanityBar
              label="Saves"
              value={top.saves}
              max={top.likes}
              color="color-mix(in srgb, var(--color-muted-foreground) 58%, transparent)"
            />
          </div>
        ) : null}

        <p className="text-sm leading-relaxed text-muted-foreground">
          {quality.toLocaleString()} sends+saves against{" "}
          {(top?.likes ?? 0).toLocaleString()} likes.
        </p>
      </div>
    </EvidenceCard>
  );
}

function VanityBar({
  label,
  value,
  max,
  color,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
}) {
  const width =
    value > 0
      ? Math.max(4, Math.min(100, (value / Math.max(1, max)) * 100))
      : 3;
  return (
    <div className="grid grid-cols-[52px_1fr_48px] items-center gap-2 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <div className="h-1.5 overflow-hidden rounded-full bg-border">
        <div
          className="h-full rounded-full"
          style={{ width: `${width}%`, background: color }}
        />
      </div>
      <span className="text-right font-mono text-muted-foreground tabular-nums">
        {value.toLocaleString()}
      </span>
    </div>
  );
}
