// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useMemo } from "react";
import { useViewsBySource, type ViewsSource } from "@/hooks/useViewsBySource";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import {
  JunoStackedAreaChart,
} from "@/components/ui/JunoChart";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { chartTheme } from "@/lib/chartTheme";
import { formatCompact } from "../shared";

/**
 * Threads views-by-source stacked area (spec §2). Reads
 * account_analytics.threads_views_by_source captured daily during sync. Six
 * source buckets come off the Threads API (July 2025+): home, profile,
 * search, activity, ig, fb. Renders 100%-stacked so the operator sees the
 * *mix shift* over time, which is the shadowban / search-surface collapse
 * signal the hero narrative points at.
 *
 * When capture hasn't populated any rows yet (fresh migration, first 24h),
 * the empty state uses the shared shadcn/Nova evidence card instead of showing
 * a flatline.
 */

const SOURCES: { key: ViewsSource; label: string; color: string }[] = [
  { key: "home", label: "Home", color: chartTheme.categorical[0] },
  { key: "profile", label: "Profile", color: chartTheme.categorical[1] },
  {
    key: "search",
    label: "Search",
    color: chartTheme.categorical[3],
  },
  {
    key: "activity",
    label: "Activity",
    color: chartTheme.categorical[4],
  },
  {
    key: "ig",
    label: "IG",
    color: chartTheme.categorical[2],
  },
  {
    key: "fb",
    label: "FB",
    color: chartTheme.categorical[5],
  },
];

interface ViewsBySourceChartProps {
  /** Restrict to a single Threads account id (drill-in). */
  accountId?: string | null | undefined;
  /** Restrict to a specific set of Threads account ids (fleet subset). */
  accountIds?: string[] | null | undefined;
  /** Look-back window in days (7 / 14 / 30 / 90). */
  days?: number | undefined;
}

export function ViewsBySourceChart({
  accountId,
  accountIds,
  days = 30,
}: ViewsBySourceChartProps) {
  const { data, isLoading, hasError } = useViewsBySource({
    accountId: accountId ?? null,
    accountIds: accountIds ?? null,
    days,
  });

  // Percentage-stacked data: each day is normalized to 100% so the operator
  // sees the *mix* change (the canonical search-surface collapse signal)
  // rather than absolute views (the hero KPI strip covers that).
  const stackedPct = useMemo(() => {
    if (!data) return [];
    return data.series.map((d) => {
      const out: Record<string, number | string> = {
        date: d.date,
        __total: d.total,
      };
      if (d.total === 0) {
        for (const s of SOURCES) out[s.key] = 0;
        return out;
      }
      for (const s of SOURCES) {
        out[s.key] = (d[s.key] / d.total) * 100;
      }
      return out;
    });
  }, [data]);

  const hasAnyData =
    !!data && !data.empty && data.series.some((d) => d.total > 0);

  if (isLoading) {
    return (
      <EvidenceCard
        state="loading"
        eyebrow="Source mix"
        title="Reach source mix"
        description={`100% stacked · last ${days}d`}
        contentClassName="flex min-h-[260px] flex-col gap-3"
      >
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-[180px] w-full" />
        <div className="flex gap-2">
          <Skeleton className="h-4 w-16" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-14" />
        </div>
      </EvidenceCard>
    );
  }

  if (hasError) {
    return (
      <EvidenceCard
        state="empty"
        eyebrow="Source mix"
        title="Reach source mix"
        description="The source-mix endpoint did not return a usable payload for this scope."
      >
        <NovaEmpty
          className="min-h-[220px]"
          title="Source mix unavailable"
          description="The panel keeps its last stable state and will retry on the next analytics refresh."
        />
      </EvidenceCard>
    );
  }

  if (!hasAnyData) {
    return (
      <EvidenceCard
        state="empty"
        eyebrow="Source mix"
        title="Reach source mix"
        description={`100% stacked · last ${days}d`}
      >
        <NovaEmpty
          className="min-h-[220px]"
          title="No source mix yet"
          description="Threads source breakdown fills after the next daily sync records home, profile, search, activity, IG, or FB source buckets."
        />
      </EvidenceCard>
    );
  }

  return (
    <EvidenceCard
      eyebrow="Source mix"
      title="Reach source mix"
      description={`100% stacked · last ${days}d`}
      action={
        <InvestigateButton
          accountId={accountId ?? null}
          metric="views"
          metricLabel="Reach source mix"
          periodDays={days}
        />
      }
      contentClassName="flex min-h-[320px] flex-col gap-3"
      footer={
        <div className="flex w-full flex-col gap-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {SOURCES.map((s) => (
              <span
                key={s.key}
                className="inline-flex items-center gap-1.5 text-[0.6875rem] text-muted-foreground"
              >
                <span
                  aria-hidden="true"
                  className="inline-block size-2 rounded-sm"
                  style={{ backgroundColor: s.color }}
                />
                {s.label}
                {data && data.totals[s.key] > 0 ? (
                  <span className="tabular-nums text-muted-foreground/75">
                    · {formatCompact(data.totals[s.key])}
                  </span>
                ) : null}
              </span>
            ))}
          </div>
          <div className="text-[0.6875rem] text-muted-foreground">
            SOURCE · account_analytics.threads_views_by_source · CAPTURE · daily
            via Threads API
          </div>
        </div>
      }
    >
      <div className="flex-1 min-h-[220px] sm:min-h-[240px] px-2 pb-1">
        <JunoStackedAreaChart
          ariaLabel={`Reach source mix, 100% stacked over the last ${days} days`}
          data={stackedPct}
          series={SOURCES.map((source) => ({
            key: source.key,
            label: source.label,
            color: source.color,
          }))}
          xKey="date"
          xTickFormatter={formatAxisDate}
          tooltipLabelFormatter={formatTooltipDate}
        />
      </div>
    </EvidenceCard>
  );
}

function formatTooltipDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatAxisDate(iso: string) {
  const date = new Date(iso);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}
