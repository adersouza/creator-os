import { useMemo } from "react";
import { useFunnelCorrelation } from "@/hooks/useFunnelCorrelation";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { useFleetKpiData } from "@/hooks/useFleetKpiData";
import { Badge } from "@/components/ui/Badge";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { EvidenceTile } from "../EvidenceTile";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { formatCompact } from "../shared";

const IG_FLEET_ACCOUNT_ID = "__ig_fleet__";

interface Props {
  accountId?: string | null | undefined;
  /** Window in days. */
  days?: number | undefined;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
}

/**
 * Discovery funnel — IG views → reach → follows → profile link taps where
 * current Graph API metrics exist, with follower correlation underneath.
 */
export function DiscoveryFunnel({
  accountId,
  days = 30,
  accountIds,
  groupId,
}: Props) {
  const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
  const { accounts } = useConnectedAccounts();
  const hasFilteredScope = !!(accountIds && accountIds.length > 0) || !!groupId;
  const aggregateScopeLabel = scopedAccount?.handle
    ? scopedAccount.handle.startsWith("@")
      ? scopedAccount.handle
      : `@${scopedAccount.handle}`
    : groupId
      ? "selected group"
      : accountIds && accountIds.length > 0
        ? `${accountIds.length} selected account${accountIds.length === 1 ? "" : "s"}`
        : hasFilteredScope
          ? "selected accounts"
          : "all accounts";

  const resolved = useMemo(() => {
    if (accountId) return accountId;
    if (scopedAccount?.platform === "instagram" && scopedAccount.id) {
      return scopedAccount.id;
    }
    return accounts.some((a) => a.platform === "instagram")
      ? IG_FLEET_ACCOUNT_ID
      : null;
  }, [accountId, scopedAccount, accounts]);

  const isFleetFunnel = resolved === IG_FLEET_ACCOUNT_ID;
  const { data, isLoading, hasError } = useFunnelCorrelation(
    isFleetFunnel ? null : resolved,
    days,
  );
  const fleetKpi = useFleetKpiData(
    { days },
    "instagram",
    scopedAccount,
    accountIds,
    groupId,
  );

  if (!resolved) {
    return (
      <EvidenceTile
        state="empty"
        label="Funnel"
        title="Discovery funnel"
        note="Connect at least one Instagram account to see how views translate into follower growth."
        variant="bullet"
      />
    );
  }

  if (isFleetFunnel) {
    if (fleetKpi.isLoading) {
      return (
        <EvidenceTile
          state="loading"
          index={14}
          title="Discovery funnel"
          hint={`Instagram ${aggregateScopeLabel} · last ${days} days`}
          variant="funnel"
        />
      );
    }

    const fleetSteps = [
      {
        label: "Reach",
        value: fleetKpi.reach,
        source: fleetKpi.usedPostFallback
          ? "Post rollup"
          : "Daily IG analytics",
      },
      // 2026-05-07: Meta removed profile_views with no replacement, so this funnel skips that stage.
      {
        label: "Profile link taps",
        value: fleetKpi.igWebsiteClicks,
        source: "Daily IG analytics",
      },
    ].filter((step, index) => index === 0 || step.value > 0);

    if (
      fleetKpi.hasError ||
      !fleetKpi.hasPostRows ||
      (fleetSteps[0]?.value ?? 0) <= 0
    ) {
      return (
        <EvidenceTile
          state="empty"
          label="Funnel"
          title="Discovery funnel"
          note={`Instagram ${aggregateScopeLabel} reach has not produced a qualified acquisition path for this window yet. The funnel fills from daily IG analytics once reach and profile link taps are captured together.`}
          variant="bullet"
        />
      );
    }

    const maxFleetValue = Math.max(...fleetSteps.map((step) => step.value), 1);

    const fleetFunnelRows = fleetSteps.map((step, index) => {
      const previous = index > 0 ? (fleetSteps[index - 1]?.value ?? 0) : 0;
      const rate = previous > 0 ? (step.value / previous) * 100 : null;
      return {
        label: step.label,
        valueLabel: formatCompact(step.value),
        rateLabel: rate != null ? `${rate.toFixed(1)}%` : null,
        pct: Math.max(5, Math.min(100, (step.value / maxFleetValue) * 100)),
        color: index === 0 ? "var(--color-chart-1)" : "var(--color-chart-2)",
        source: step.source,
      };
    });

    return (
      <EvidenceCard
        title="Discovery funnel"
        description={`Instagram ${aggregateScopeLabel} · last ${days}d`}
        action={
          <InvestigateButton
            accountId={null}
            metric="conversion"
            metricLabel={`${aggregateScopeLabel === "scope" ? "Scoped" : "Workspace"} discovery funnel`}
            periodDays={days}
          />
        }
        footer={
          <span className="text-[0.6875rem] uppercase tracking-[0.08em] text-muted-foreground">
            SOURCE · Instagram {aggregateScopeLabel} KPI rollup across the last{" "}
            {days} days.
          </span>
        }
        contentClassName="flex h-full flex-col gap-4"
      >
        <div className="grid grid-cols-1 gap-3 text-[0.6875rem] sm:grid-cols-3">
          <Stat
            label="Reach"
            value={formatCompact(fleetKpi.reach)}
            tone="primary"
          />
          <Stat
            label="Profile link taps"
            value={formatCompact(fleetKpi.igWebsiteClicks)}
            tone="warning"
          />
          <Stat
            label="Interactions"
            value={formatCompact(fleetKpi.igTotalInteractions)}
            tone="primary"
          />
        </div>

        <FunnelBars steps={fleetFunnelRows} />

        <p className="text-[0.75rem] leading-relaxed text-muted-foreground">
          This view uses aggregate IG reach and profile link taps. Select a
          specific Instagram account for post-level converter attribution.
        </p>
      </EvidenceCard>
    );
  }

  if (hasError) {
    return (
      <EvidenceTile
        state="empty"
        label="Funnel"
        title="Discovery funnel"
        note="The views-to-follower correlation endpoint did not return a usable payload for this account. The funnel appears once daily views and follower deltas can be paired."
        variant="bullet"
      />
    );
  }

  if (isLoading || !data) {
    return (
      <EvidenceTile
        state="loading"
        index={14}
        title="Discovery funnel"
        hint={`Last ${days} days`}
        variant="funnel"
      />
    );
  }

  const { summary, topConverterPosts } = data;
  const correlationLabel: Record<string, string> = {
    strong: "Strong correlation",
    moderate: "Moderate correlation",
    weak: "Weak correlation",
    none: "No correlation",
  };
  const correlationTone: Record<string, string> = {
    strong: "var(--color-health-good)",
    moderate: "var(--color-warning)",
    weak: "var(--color-critical)",
    none: "var(--color-muted-foreground)",
  };
  const totalViews = Math.max(1, summary.avgDailyViews * data.periodDays);
  const conversionPct = Math.max(
    0,
    Math.min(100, summary.overallConversionRate * 100),
  );
  const followEstimate = Math.max(
    0,
    summary.avgDailyFollowerChange * data.periodDays,
  );
  const liveFunnelSteps = (data.funnelSteps ?? []).filter(
    (step) => step.available,
  );
  const hasFullFunnel = liveFunnelSteps.length >= 3;
  const fallbackFunnelSteps = [
    {
      label: "Views",
      value: totalViews,
      valueLabel: formatCompact(totalViews),
      rateLabel: null,
      pct: 100,
      color: "var(--color-chart-1)",
      source: "Post rollup",
    },
    {
      label: "Follower lift",
      value: followEstimate,
      valueLabel: `${followEstimate >= 0 ? "+" : ""}${Math.round(followEstimate)}`,
      rateLabel: null,
      pct: Math.max(6, Math.min(100, conversionPct * 12)),
      color:
        summary.avgDailyFollowerChange >= 0
          ? "var(--color-chart-positive)"
          : "var(--color-chart-danger)",
      source: "Follower history",
    },
    {
      label: "Conversion",
      value: conversionPct,
      valueLabel: `${conversionPct.toFixed(2)}%`,
      rateLabel: null,
      pct: Math.max(5, Math.min(100, conversionPct * 20)),
      color:
        correlationTone[summary.correlationStrength] ??
        "var(--color-muted-foreground)",
      source: "Correlation",
    },
  ];
  const maxFunnelValue = Math.max(
    ...liveFunnelSteps.map((step) => step.value),
    1,
  );
  const funnelSteps = hasFullFunnel
    ? liveFunnelSteps.map((step, index) => ({
        label: step.label,
        value: step.value,
        valueLabel: formatCompact(step.value),
        rateLabel:
          index === 0 || step.rateFromPrevious == null
            ? null
            : `${step.rateFromPrevious.toFixed(1)}%`,
        pct: Math.max(5, Math.min(100, (step.value / maxFunnelValue) * 100)),
        color:
          step.key === "link_taps"
            ? "var(--color-chart-2)"
            : step.key === "follows"
              ? "var(--color-health-good)"
              : "var(--color-chart-1)",
        source:
          step.source === "account_analytics"
            ? "Daily IG analytics"
            : step.source === "post_rollup"
              ? "Post rollup"
              : "Follower history",
      }))
    : fallbackFunnelSteps;

  return (
    <EvidenceCard
      title="Discovery funnel"
      description={`Avg ${formatCompact(summary.avgDailyViews)} views/day · last ${data.periodDays}d`}
      action={
        <InvestigateButton
          accountId={resolved === IG_FLEET_ACCOUNT_ID ? null : resolved}
          metric="conversion"
          metricLabel={
            resolved === IG_FLEET_ACCOUNT_ID
              ? `${aggregateScopeLabel === "scope" ? "Scoped" : "Workspace"} discovery funnel`
              : "Views → followers"
          }
          periodDays={data.periodDays}
        />
      }
      footer={
        <span className="text-[0.6875rem] uppercase tracking-[0.08em] text-muted-foreground">
          SOURCE ·{" "}
          {hasFullFunnel
            ? "IG daily account analytics for views, reach, follows, and profile link taps"
            : "daily views vs follower-change correlation"}{" "}
          across the last {data.periodDays} days.
        </span>
      }
      contentClassName="flex h-full flex-col gap-4"
    >
      <div className="grid grid-cols-1 gap-3 text-[0.6875rem] sm:grid-cols-3">
        <Stat
          label="Avg daily views"
          value={formatCompact(summary.avgDailyViews)}
          tone="primary"
        />
        <Stat
          label="Avg follower Δ/day"
          value={
            summary.avgDailyFollowerChange >= 0
              ? `+${Math.round(summary.avgDailyFollowerChange)}`
              : Math.round(summary.avgDailyFollowerChange).toString()
          }
          tone={summary.avgDailyFollowerChange >= 0 ? "good" : "crit"}
        />
        <Stat
          label="Conversion"
          value={`${(summary.overallConversionRate * 100).toFixed(2)}%`}
          tone="primary"
        />
      </div>

      <FunnelBars steps={funnelSteps} />

      <div
        className="flex items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-[0.75rem]"
        style={{
          borderColor:
            correlationTone[summary.correlationStrength] ??
            "var(--color-border)",
          background: `color-mix(in srgb, ${correlationTone[summary.correlationStrength] ?? "var(--color-foreground)"} 6%, transparent)`,
        }}
      >
        <Badge
          tone="outline"
          style={{ color: correlationTone[summary.correlationStrength] }}
        >
          {correlationLabel[summary.correlationStrength] ?? "Unknown"}
        </Badge>
        {summary.bestConversionDay ? (
          <span className="text-muted-foreground">
            · best day {summary.bestConversionDay.date} (+
            {summary.bestConversionDay.followerChange})
          </span>
        ) : null}
      </div>

      {topConverterPosts.length > 0 ? (
        <div>
          <div className="mb-2 text-[0.6875rem] uppercase tracking-[0.08em] text-muted-foreground">
            Top converter posts
          </div>
          <ul className="flex flex-col gap-1.5">
            {topConverterPosts.slice(0, 3).map((post) => (
              <li key={post.id} className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between text-[0.75rem]">
                  <span className="line-clamp-1 max-w-[70%] text-foreground">
                    {post.content || "(empty)"}
                  </span>
                  <span className="font-mono tabular-nums text-[var(--color-health-good)]">
                    +{post.dayFollowerChange}
                  </span>
                </div>
                <span className="text-[0.625rem] text-muted-foreground tabular-nums">
                  {formatCompact(post.views)} views ·{" "}
                  {new Date(post.publishedAt).toLocaleDateString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </EvidenceCard>
  );
}

function FunnelBars({
  steps,
}: {
  steps: Array<{
    label: string;
    valueLabel: string;
    rateLabel: string | null;
    pct: number;
    color: string;
    source: string;
  }>;
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/20 px-3 py-3">
      <div className="grid grid-cols-1 gap-2.5">
        {steps.map((step, index) => (
          <div
            key={step.label}
            className="grid grid-cols-[minmax(72px,0.5fr)_minmax(0,1fr)_minmax(52px,0.35fr)] items-center gap-3"
          >
            <div className="min-w-0">
              <div className="truncate text-[0.6875rem] text-muted-foreground">
                {step.label}
              </div>
              {step.rateLabel ? (
                <div className="mt-0.5 font-mono text-[0.5625rem] text-muted-foreground tabular-nums">
                  {step.rateLabel}
                </div>
              ) : null}
            </div>
            <div className="h-7 overflow-hidden rounded-md border border-border bg-card">
              <div
                className="h-full rounded-r-md"
                style={{
                  width: `${step.pct}%`,
                  background: `color-mix(in srgb, ${step.color} ${index === 0 ? 34 : 24}%, transparent)`,
                }}
              />
            </div>
            <div className="min-w-0 truncate text-right font-mono text-[0.75rem] text-foreground tabular-nums">
              {step.valueLabel}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[0.5625rem] uppercase tracking-[0.08em] text-muted-foreground">
        {Array.from(new Set(steps.map((step) => step.source))).map((source) => (
          <span key={source}>{source}</span>
        ))}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "primary" | "warning" | "good" | "crit";
}) {
  const color =
    tone === "warning"
      ? "var(--color-warning)"
      : tone === "good"
        ? "var(--color-health-good)"
        : tone === "crit"
          ? "var(--color-critical)"
          : "var(--color-foreground)";
  return (
    <div className="flex flex-col gap-0.5 rounded-md border border-border bg-muted/35 px-3 py-2">
      <span className="text-muted-foreground uppercase tracking-[0.04em]">
        {label}
      </span>
      <span
        className="text-[0.9375rem] font-semibold tabular-nums"
        style={{ color }}
      >
        {value}
      </span>
    </div>
  );
}
