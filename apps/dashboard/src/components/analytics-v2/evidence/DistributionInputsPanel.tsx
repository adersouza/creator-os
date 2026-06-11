import { useMemo } from "react";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { useContentMixHealth } from "@/hooks/useContentMixHealth";
import { useContentTypeTrend } from "@/hooks/useContentTypeTrend";
import { useHashtagPerformance } from "@/hooks/useHashtagPerformance";
import { useNonFollowerReach } from "@/hooks/useNonFollowerReach";
import { useSkipRateAlerts } from "@/hooks/useSkipRateAlerts";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { BarChart3 } from "lucide-react";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { cn } from "@/lib/utils";
import { formatCompact } from "../shared";

interface Props {
  days: number;
  scopedAccount?: ScopedAccountLite | null | undefined;
  platform?: "all" | "instagram" | undefined;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
}

const SURFACES = [
  { key: "reels", label: "Reels", color: "var(--color-chart-1)" },
  { key: "feed", label: "Feed", color: "var(--color-chart-2)" },
  { key: "story", label: "Stories", color: "var(--color-chart-4)" },
] as const;

export function DistributionInputsPanel({
  days,
  scopedAccount,
  platform = "instagram",
  accountIds: scopedAccountIds,
  groupId,
}: Props) {
  const storeScope = useAccountScopeStore((s) => s.scopedAccount);
  const scope = scopedAccount ?? storeScope;
  const { accounts } = useConnectedAccounts();
  const accountIds = useMemo(() => {
    if (scope?.platform === "instagram" && scope.id) return [scope.id];
    if (groupId) return undefined;
    if (scopedAccountIds && scopedAccountIds.length > 0) {
      const instagramIds = new Set(
        accounts
          .filter((account) => account.platform === "instagram")
          .map((account) => account.id),
      );
      return scopedAccountIds.filter((id) => instagramIds.has(id));
    }
    return undefined;
  }, [scope, groupId, scopedAccountIds, accounts]);
  const accountId =
    scope?.platform === "instagram" && scope.id ? scope.id : null;
  const accountScope = accountId
    ? {
        accountId,
        accountPlatform: "instagram" as const,
        accountHandle: scope?.handle ?? null,
      }
    : null;

  const formatTrend = useContentTypeTrend(
    accountId ? undefined : accountIds,
    accountId,
    groupId,
  );
  const surfaceMix = useContentMixHealth(
    accountId,
    accountId ? undefined : accountIds,
    days,
    accountId ? null : groupId,
  );
  const hashtags = useHashtagPerformance({
    accountIds: accountId ? undefined : accountIds,
    accountId,
    groupId,
    periodDays: days,
    platform,
    limit: 12,
  });
  const skipRate = useSkipRateAlerts(
    days,
    0.5,
    accountId,
    accountId ? undefined : accountIds,
    accountId ? null : groupId,
  );
  const discovery = useNonFollowerReach(
    { days },
    accountScope,
    accountId ? undefined : accountIds,
    accountId ? null : groupId,
  );

  const formatRows = useMemo(() => {
    const data = formatTrend.data;
    if (!data) return [];
    const keys = new Set([
      ...Object.keys(data.current),
      ...Object.keys(data.previous),
    ]);
    return [...keys]
      .map((format) => {
        const current = data.current[format]?.reach ?? 0;
        const previous = data.previous[format]?.reach ?? 0;
        const pct = data.deltas[format]?.reach?.pctChange ?? null;
        return { label: format, current, previous, pct };
      })
      .filter((row) => row.current > 0 || row.previous > 0)
      .sort((a, b) => b.current - a.current)
      .slice(0, 5);
  }, [formatTrend.data]);

  const surfaceRows = useMemo(() => {
    const rows = SURFACES.map((surface) => ({
      ...surface,
      reach: surfaceMix.current[surface.key]?.reach ?? 0,
    }));
    const total = rows.reduce((sum, row) => sum + row.reach, 0);
    return {
      total,
      rows: rows.map((row) => ({
        ...row,
        pct: total > 0 ? (row.reach / total) * 100 : 0,
      })),
    };
  }, [surfaceMix.current]);

  const hashtagRows = useMemo(() => {
    const rows = [...(hashtags.data?.hashtags ?? [])];
    return rows
      .sort(
        (a, b) =>
          (b.totalReach || b.totalViews) - (a.totalReach || a.totalViews),
      )
      .slice(0, 6);
  }, [hashtags.data]);
  const maxHashtagReach = Math.max(
    1,
    ...hashtagRows.map((row) => row.totalReach || row.totalViews || 0),
  );
  const skipRows = [...skipRate.alerts]
    .sort((a, b) => b.skipRate - a.skipRate)
    .slice(0, 4);
  const topFormat = formatRows[0] ?? null;
  const discoveryPct = discovery.hasRealData ? discovery.nonFollowerPct : null;
  const hasRealInputs =
    formatRows.length > 0 ||
    surfaceRows.total > 0 ||
    hashtagRows.length > 0 ||
    skipRows.length > 0 ||
    discovery.hasRealData;
  const accountHint = accountIds
    ? `${accountIds.length || "No"} IG account${accountIds.length === 1 ? "" : "s"}`
    : groupId
      ? "Group scope"
      : "Fleet scope";

  return (
    <EvidenceCard
      eyebrow="Distribution inputs"
      title="What is changing distribution"
      description={`${accountHint} · last ${days}d`}
      action={
        <InvestigateButton
          accountId={accountId}
          metric="reach"
          metricLabel="Distribution inputs"
          periodDays={days}
        />
      }
      contentClassName="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(260px,0.85fr)]"
    >
      <section className="flex min-w-0 flex-col gap-4">
        <div className="grid overflow-hidden rounded-xl border border-border bg-muted/25 sm:grid-cols-3">
          <MiniKpi
            label="Leading format"
            value={topFormat ? titleCase(topFormat.label) : "—"}
            caption={
              topFormat
                ? `${formatCompact(topFormat.current)} reach`
                : "No format rows"
            }
            tone="neutral"
          />
          <MiniKpi
            label="Discovery"
            value={discoveryPct == null ? "—" : `${discoveryPct.toFixed(1)}%`}
            caption={discovery.delta ?? "non-follower reach"}
            tone={
              discoveryPct == null
                ? "neutral"
                : discoveryPct < 10
                  ? "bad"
                  : discoveryPct <= 60
                    ? "good"
                    : "warn"
            }
          />
          <MiniKpi
            label="Skip alerts"
            value={skipRows.length.toString()}
            caption={`above ${(skipRate.threshold * 100).toFixed(0)}%`}
            tone={skipRows.length > 0 ? "bad" : "good"}
          />
        </div>

        {hasRealInputs ? (
          <div className="rounded-xl border border-border bg-muted/25 p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <span className="text-[0.72rem] font-medium tracking-wide text-muted-foreground uppercase">
                Format reach
              </span>
              <strong className="text-[0.72rem] font-medium text-foreground">
                7d vs prior 7d
              </strong>
            </div>
            <div className="flex flex-col gap-2">
              {formatRows.length > 0
                ? formatRows.map((row) => (
                    <RankBar
                      key={row.label}
                      label={titleCase(row.label)}
                      value={formatCompact(row.current)}
                      note={
                        row.pct == null
                          ? "new baseline"
                          : `${row.pct >= 0 ? "+" : ""}${row.pct.toFixed(1)}%`
                      }
                      pct={percentOf(row.current, formatRows[0]?.current ?? 1)}
                      tone={row.pct == null || row.pct >= 0 ? "good" : "bad"}
                    />
                  ))
                : SURFACES.map((surface) => (
                    <RankBar
                      key={surface.key}
                      label={surface.label}
                      value="—"
                      note="No IG rows"
                      pct={8}
                      tone="neutral"
                    />
                  ))}
            </div>
          </div>
        ) : (
          <NovaEmpty
            className="min-h-[260px]"
            icon={<BarChart3 data-icon aria-hidden="true" />}
            title="Distribution inputs unavailable"
            description="IG format, surface, hashtag, and skip-rate rows will consolidate here once the selected window has enough synced posts."
          />
        )}
      </section>

      <aside className="flex min-w-0 flex-col gap-3">
        <div className="rounded-xl border border-border bg-muted/25 p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="text-[0.72rem] font-medium tracking-wide text-muted-foreground uppercase">
              Audience surface
            </span>
            <strong className="text-[0.72rem] font-medium text-foreground">
              {formatCompact(surfaceRows.total)} reach
            </strong>
          </div>
          <div className="flex flex-col gap-2">
            {surfaceRows.rows.map((row) => (
              <SurfaceRow key={row.key} row={row} />
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-muted/25 p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="text-[0.72rem] font-medium tracking-wide text-muted-foreground uppercase">
              Tag pull
            </span>
            <strong className="text-[0.72rem] font-medium text-foreground">
              {hashtags.data
                ? `${hashtagRows.length}/${hashtags.data.hashtags.length}`
                : hashtags.isLoading
                  ? "Loading"
                  : "—"}
            </strong>
          </div>
          <div className="flex flex-col gap-2">
            {hashtagRows.length > 0 ? (
              hashtagRows.map((row) => {
                const reach = row.totalReach || row.totalViews || 0;
                return (
                  <RankBar
                    key={row.hashtag}
                    label={`#${row.hashtag}`}
                    value={formatCompact(reach)}
                    note={`${row.postCount} posts`}
                    pct={percentOf(reach, maxHashtagReach)}
                    tone="warn"
                  />
                );
              })
            ) : (
              <MutedNote text="No hashtag reach rows in this window." />
            )}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-muted/25 p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="text-[0.72rem] font-medium tracking-wide text-muted-foreground uppercase">
              Reels friction
            </span>
            <strong className="text-[0.72rem] font-medium text-foreground">
              {skipRate.hasError
                ? "Offline"
                : skipRows.length
                  ? `${skipRows.length} alerts`
                  : "Clear"}
            </strong>
          </div>
          {skipRows.length > 0 ? (
            <div className="flex flex-col gap-2">
              {skipRows.map((alert) => (
                <div
                  key={alert.id}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background/35 px-3 py-2"
                >
                  <span className="min-w-0 truncate text-[0.78rem] text-muted-foreground">
                    {alert.content || "No caption"}
                  </span>
                  <strong className="shrink-0 text-[0.78rem] font-medium tabular-nums text-foreground">
                    {(alert.skipRate * 100).toFixed(0)}%
                  </strong>
                </div>
              ))}
            </div>
          ) : (
            <MutedNote text="No Reels exceeded the current skip-rate threshold." />
          )}
        </div>
      </aside>
    </EvidenceCard>
  );
}

function MiniKpi({
  label,
  value,
  caption,
  tone,
}: {
  label: string;
  value: string;
  caption: string;
  tone: "good" | "bad" | "warn" | "neutral";
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1 border-border border-b p-4 last:border-b-0 sm:border-r sm:border-b-0 sm:last:border-r-0">
      <span className="text-[0.68rem] font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </span>
      <strong
        className={cn(
          "text-2xl font-semibold tracking-tight text-foreground tabular-nums",
          tone === "good" && "text-success",
          tone === "bad" && "text-danger",
          tone === "warn" && "text-warning",
        )}
      >
        {value}
      </strong>
      <small className="text-[0.72rem] text-muted-foreground">{caption}</small>
    </div>
  );
}

function RankBar({
  label,
  value,
  note,
  pct,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  pct: number;
  tone: "good" | "bad" | "warn" | "neutral";
}) {
  return (
    <div className="grid gap-2 rounded-lg border border-border bg-background/35 px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="block truncate text-[0.78rem] font-medium text-foreground">
            {label}
          </span>
          <small className="text-[0.7rem] text-muted-foreground">{note}</small>
        </div>
        <strong className="shrink-0 text-[0.78rem] font-medium tabular-nums text-foreground">
          {value}
        </strong>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-border/55">
        <i
          className={cn(
            "block h-full rounded-full bg-muted-foreground",
            tone === "good" && "bg-success",
            tone === "bad" && "bg-danger",
            tone === "warn" && "bg-warning",
          )}
          style={{ width: `${clamp(pct, 3, 100)}%` }}
        />
      </div>
    </div>
  );
}

function SurfaceRow({
  row,
}: {
  row: (typeof SURFACES)[number] & { reach: number; pct: number };
}) {
  return (
    <div className="grid grid-cols-[auto_minmax(58px,0.5fr)_minmax(0,1fr)_auto] items-center gap-2 rounded-lg border border-border bg-background/35 px-3 py-2">
      <div className="size-2.5 rounded-sm" style={{ background: row.color }} />
      <span className="text-[0.78rem] font-medium text-foreground">
        {row.label}
      </span>
      <i className="h-1.5 overflow-hidden rounded-full bg-border/55">
        <b
          className="block h-full rounded-full bg-primary"
          style={{ width: `${clamp(row.pct, row.reach > 0 ? 4 : 0, 100)}%` }}
        />
      </i>
      <strong className="text-[0.78rem] font-medium tabular-nums text-foreground">
        {row.reach > 0 ? `${Math.round(row.pct)}%` : "0%"}
      </strong>
    </div>
  );
}

function MutedNote({ text }: { text: string }) {
  return (
    <p className="rounded-lg border border-dashed border-border bg-background/30 px-3 py-3 text-[0.78rem] leading-relaxed text-muted-foreground">
      {text}
    </p>
  );
}

function percentOf(value: number, max: number) {
  return max > 0 ? (value / max) * 100 : 0;
}

function titleCase(value: string) {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}
