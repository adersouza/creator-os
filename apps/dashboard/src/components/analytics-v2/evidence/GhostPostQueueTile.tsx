import { CalendarDays } from "lucide-react";
import { useGhostPostCount } from "@/hooks/useGhostPostCount";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { AnalyticsActionLink } from "@/components/analytics-v2/AnalyticsActionLink";
import { Badge } from "@/components/ui/Badge";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";
import { scopedRoute } from "@/lib/scopedRoutes";

/**
 * §5 Ghost-post queue (Threads). Backed by useGhostPostCount: posts published
 * more than 24h ago with fewer than 10 views — a low-view queue signal.
 *
 * Renders fleet totals, WoW delta, and per-account leaderboard so the user
 * can triage which accounts are spiraling.
 */
interface Props {
  accountIds?: string[] | undefined;
}

export function GhostPostQueueTile({ accountIds }: Props = {}) {
  const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
  const threadScopedIds = scopedAccount
    ? scopedAccount.platform === "threads"
      ? [scopedAccount.id]
      : []
    : accountIds;
  const { total, withLinks, weekOverWeekDelta, accounts, isLoading, hasError } =
    useGhostPostCount(threadScopedIds);

  if (isLoading && accounts.length === 0) {
    return (
      <EvidenceCard
        state="loading"
        title="Ghost post queue"
        description="Posts >24h with <10 views"
      >
        <div
          className="flex flex-col gap-3"
          role="status"
          aria-label="Loading ghost post queue"
        >
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-9 w-full rounded-lg" />
          <Skeleton className="h-9 w-5/6 rounded-lg" />
        </div>
      </EvidenceCard>
    );
  }

  if (hasError) {
    return (
      <EvidenceCard state="empty" eyebrow="Threads" title="Ghost post queue">
        <NovaEmpty
          title="Ghost-post scan unavailable"
          description="The ghost-post scan did not return a usable payload. The queue appears once Threads posts have age and view-count data."
        />
      </EvidenceCard>
    );
  }

  if (total === 0) {
    return (
      <EvidenceCard
        state="empty"
        eyebrow="Threads"
        title="Ghost post queue"
        description="No low-view queue"
      >
        <NovaEmpty
          title="No ghost posts in this window"
          description="No Threads posts are older than 24 hours with fewer than 10 views in the current window. This clears the low-view queue, but does not prove overall account health."
        />
      </EvidenceCard>
    );
  }

  const deltaTone =
    weekOverWeekDelta > 5
      ? "var(--color-critical)"
      : weekOverWeekDelta < -5
        ? "var(--color-health-good)"
        : "var(--color-warning)";
  const linkPct = total > 0 ? Math.round((withLinks / total) * 100) : 0;

  return (
    <EvidenceCard
      title="Ghost post queue"
      description="Posts >24h with <10 views (Threads)"
      action={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <AnalyticsActionLink
            to={scopedRoute(
              "/calendar",
              {
                scopedAccount,
                accountIds: threadScopedIds,
                platform: "threads",
              },
              { status: "published" },
            )}
            label="Review posts"
            icon={CalendarDays}
            tone="primary"
          />
          <InvestigateButton
            accountId={scopedAccount?.id ?? accounts[0]?.accountId ?? null}
            metric="reach"
            metricLabel="Ghost-post suppression"
            periodDays={7}
          />
        </div>
      }
      footer={
        <p className="text-xs leading-relaxed text-muted-foreground">
          SOURCE · `posts.views_count &lt; 10` AND `posts.published_at &gt; 24h
          ago`, Threads-only. WoW Δ vs prior 7d. High link % suggests
          link-suppression; confirm against reach and webhook sync before
          acting.
        </p>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-3 gap-3 text-xs">
          <Stat
            label="Last 7d"
            value={total.toString()}
            tone="var(--color-critical)"
          />
          <Stat
            label="With links"
            value={`${withLinks} · ${linkPct}%`}
            tone={
              linkPct > 50 ? "var(--color-critical)" : "var(--color-foreground)"
            }
          />
          <Stat
            label="WoW Δ"
            value={
              weekOverWeekDelta >= 0
                ? `+${weekOverWeekDelta}`
                : weekOverWeekDelta.toString()
            }
            tone={deltaTone}
          />
        </div>

        {accounts.length > 0 ? (
          <div className="flex flex-col gap-2">
            <div className="text-[0.68rem] font-medium tracking-wide text-muted-foreground uppercase">
              Worst-affected accounts
            </div>
            <ul className="flex flex-col gap-1.5">
              {accounts.slice(0, 5).map((account) => (
                <li
                  key={account.accountId}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/35 px-3 py-2 text-sm"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="min-w-0 truncate text-foreground">
                      @{account.username ?? account.accountId.slice(0, 8)}
                    </span>
                    {account.hasLink ? (
                      <Badge tone="danger" className="text-[0.5625rem]">
                        Link
                      </Badge>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-3 text-xs tabular-nums">
                    <span className="text-muted-foreground">
                      {account.freshestAgeHours.toFixed(0)}h
                    </span>
                    <span className="font-mono text-[var(--color-critical)]">
                      {account.ghostCount}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </EvidenceCard>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-muted-foreground uppercase tracking-[0.04em]">
        {label}
      </span>
      <span
        className="text-[1.125rem] font-semibold tabular-nums"
        style={{ color: tone }}
      >
        {value}
      </span>
    </div>
  );
}
