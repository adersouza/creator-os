import { useMemo } from "react";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { JunoShareBarChart } from "@/components/ui/JunoChart";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { useContentMixHealth } from "@/hooks/useContentMixHealth";
import { useNonFollowerReach } from "@/hooks/useNonFollowerReach";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { formatCompact } from "../shared";

interface Props {
  days: number;
  scopedAccount?: ScopedAccountLite | null | undefined;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
}

const SURFACES = [
  { key: "reels", label: "Reels", tone: "var(--color-chart-1)" },
  { key: "feed", label: "Feed", tone: "var(--color-chart-2)" },
  { key: "story", label: "Stories", tone: "var(--color-chart-4)" },
] as const;

export function IGReachSourceMixTile({
  days,
  scopedAccount,
  accountIds,
  groupId,
}: Props) {
  const accountId =
    scopedAccount?.platform === "instagram" && scopedAccount.id
      ? scopedAccount.id
      : null;
  const accountHandle =
    scopedAccount?.platform === "instagram" ? scopedAccount.handle : null;
  const accountScope = accountId
    ? {
        accountId,
        accountPlatform: "instagram" as const,
        accountHandle,
      }
    : null;

  const contentMix = useContentMixHealth(
    accountId,
    accountId ? undefined : accountIds,
    days,
    accountId ? null : groupId,
  );
  const discovery = useNonFollowerReach(
    { days },
    accountScope,
    accountId ? undefined : accountIds,
    accountId ? null : groupId,
  );

  const surfaceRows = useMemo(() => {
    const rows = SURFACES.map((surface) => ({
      ...surface,
      reach: contentMix.current[surface.key]?.reach ?? 0,
    }));
    const total = rows.reduce((sum, row) => sum + row.reach, 0);
    return {
      total,
      rows: rows
        .filter((row) => row.reach > 0)
        .map((row) => ({
          ...row,
          pct: total > 0 ? (row.reach / total) * 100 : 0,
        })),
    };
  }, [contentMix.current]);

  const isLoading = contentMix.isLoading || discovery.loading;
  const hasSurface = surfaceRows.total > 0;
  const hasDiscovery = discovery.hasRealData;

  if (isLoading) {
    return (
      <EvidenceCard
        state="loading"
        eyebrow="Source mix"
        title="Instagram reach mix"
        description={`follower x surface · last ${days}d`}
        contentClassName="flex min-h-[320px] flex-col gap-4"
      >
        <Skeleton className="h-[132px] w-full" />
        <Skeleton className="h-[132px] w-full" />
      </EvidenceCard>
    );
  }

  if (!hasSurface && !hasDiscovery) {
    return (
      <EvidenceCard
        state="empty"
        eyebrow="Source mix"
        title="Instagram reach mix"
        description={`follower x surface · last ${days}d`}
      >
        <NovaEmpty
          className="min-h-[260px]"
          title="No Instagram reach mix yet"
          description={`Reach mix needs either Meta reach-breakdown rows or IG posts with reach in the selected ${days}-day window. Once those sync, this splits discovery reach from owned-audience reach and shows which surface is carrying distribution.`}
        />
      </EvidenceCard>
    );
  }

  const discoveryRows = hasDiscovery
    ? [
        {
          label: "Non-followers",
          pct: discovery.nonFollowerPct,
          tone: "var(--color-chart-positive)",
          note: "discovery reach",
        },
        {
          label: "Followers",
          pct: discovery.followerPct,
          tone: "var(--color-chart-5)",
          note: "owned audience",
        },
      ]
    : [];

  return (
    <EvidenceCard
      eyebrow="Source mix"
      title="Instagram reach mix"
      description={`follower x surface · last ${days}d`}
      action={
        <InvestigateButton
          accountId={accountId}
          metric="reach"
          metricLabel="Instagram reach mix"
          periodDays={days}
        />
      }
      contentClassName="flex h-full flex-col gap-5"
      footer={
        <div className="text-[0.6875rem] text-muted-foreground">
          SOURCE · account_analytics.ig_non_follower_reach_pct + posts.ig_reach
          by media surface.
        </div>
      }
    >
      {discoveryRows.length > 0 ? (
        <div className="rounded-xl border border-border/70 bg-muted/25 p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <span className="text-[0.7rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Audience split
            </span>
            {discovery.delta ? (
              <span className="rounded-full bg-success/10 px-2 py-0.5 text-[0.72rem] font-medium text-success">
                {discovery.delta}
              </span>
            ) : null}
          </div>
          <MixBarChart
            rows={discoveryRows.map((row) => ({
              ...row,
              value: `${Math.round(row.pct)}%`,
            }))}
            ariaLabel="Instagram audience reach split"
          />
        </div>
      ) : null}

      {hasSurface ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="text-[0.7rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                Surface mix
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {formatCompact(surfaceRows.total)} reach across IG posts
              </div>
            </div>
            <div className="text-right text-[0.72rem] text-muted-foreground">
              post-level reach
            </div>
          </div>
          <MixBarChart
            rows={surfaceRows.rows.map((row) => ({
              label: row.label,
              value: formatCompact(row.reach),
              pct: row.pct,
              tone: row.tone,
              note: `${Math.round(row.pct)}% of surface reach`,
            }))}
            ariaLabel="Instagram reach by surface"
          />
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border/80 bg-muted/25 p-4 text-sm text-muted-foreground">
          Surface split is waiting on IG post reach. Audience split above is
          already wired from daily Meta reach-breakdown rows.
        </div>
      )}
    </EvidenceCard>
  );
}

interface MixBarRow {
  label: string;
  value: string;
  pct: number;
  tone: string;
  note: string;
}

function MixBarChart({
  rows,
  ariaLabel,
}: {
  rows: MixBarRow[];
  ariaLabel: string;
}) {
  return (
    <div className="grid gap-3">
      <JunoShareBarChart
        ariaLabel={ariaLabel}
        height={124}
        data={rows.map((row) => ({
          label: row.label,
          pct: row.pct,
          color: row.tone,
        }))}
        className="rounded-md border border-border/70 bg-muted/20 p-2"
      />
      <div className="grid gap-2">
        {rows.map((row) => (
          <div
            key={row.label}
            className="grid grid-cols-[minmax(5.5rem,0.9fr)_minmax(0,1.2fr)_minmax(3.5rem,0.45fr)] items-center gap-3"
          >
            <div>
              <div className="truncate text-sm font-medium text-foreground">
                {row.label}
              </div>
              <div className="truncate text-[0.72rem] text-muted-foreground">
                {row.note}
              </div>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted/35">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(2, Math.min(100, row.pct))}%`,
                  background: row.tone,
                }}
              />
            </div>
            <div className="text-right text-sm font-semibold tabular-nums text-foreground">
              {row.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
