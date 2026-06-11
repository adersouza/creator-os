import { useMemo } from "react";
import { useEngagerRetention } from "@/hooks/useEngagerRetention";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import type { AccountScopeValue } from "@/stores/useAccountScopeStore";
import { useConnectedAccounts } from "@/hooks/useConnectedAccounts";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatCompact } from "../shared";
export { hasMinimumEngagerRetentionSignal } from "./EngagerRetentionTile.helpers";
import { hasMinimumEngagerRetentionSignal } from "./EngagerRetentionTile.helpers";

interface Props {
  accountId?: string | null | undefined;
  platform?: "all" | "threads" | "instagram" | undefined;
  periodDays?: number | undefined;
  scopedAccount?: AccountScopeValue | null | undefined;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
}

/**
 * §18 Engager retention — returning vs new engagers across the period for one
 * account. Backed by api/analytics?action=engager-retention which combines
 * post_replies (Threads) + ig_comments (IG).
 *
 * Renders as a horizontal bullet bar (returning % | new %) — donut would
 * violate the Doc 3 §9 "no pies > 4 slices" rule. Top returning engagers
 * are listed below as a compact leaderboard.
 *
 * Returns null when no account is available for the active platform view.
 */
export function EngagerRetentionTile({
  accountId,
  platform = "all",
  periodDays = 30,
  scopedAccount: scopedAccountProp,
  accountIds,
  groupId,
}: Props) {
  const storeScopedAccount = useAccountScopeStore((s) => s.scopedAccount);
  const scopedAccount =
    scopedAccountProp !== undefined ? scopedAccountProp : storeScopedAccount;
  const { accounts } = useConnectedAccounts();

  const resolvedId = useMemo(() => {
    if (accountId) return accountId;
    if (scopedAccount?.id) {
      if (platform !== "all" && scopedAccount.platform !== platform)
        return null;
      return scopedAccount.id;
    }
    if (accountIds?.length) {
      const account = accounts.find(
        (a) =>
          accountIds.includes(a.id) &&
          (platform === "all" || a.platform === platform),
      );
      return account?.id ?? null;
    }
    if (platform === "instagram") {
      return accounts.find((a) => a.platform === "instagram")?.id ?? null;
    }
    if (platform === "threads") {
      return accounts.find((a) => a.platform === "threads")?.id ?? null;
    }
    // All-view default: first Threads account, then IG, so the tile still
    // renders when the workspace is single-platform.
    const firstThreads = accounts.find((a) => a.platform === "threads");
    return (
      firstThreads?.id ??
      accounts.find((a) => a.platform === "instagram")?.id ??
      null
    );
  }, [accountId, platform, scopedAccount, accountIds, accounts]);

  const { data, isLoading, hasError } = useEngagerRetention(
    resolvedId,
    periodDays,
    accountIds,
    groupId,
  );

  if (!resolvedId) {
    return null;
  }

  if (hasError) {
    return null;
  }

  if (isLoading || !data) {
    return (
      <EvidenceCard
        state="loading"
        title="Engager retention"
        description={`Returning vs new engagers · last ${periodDays}d`}
      >
        <div
          className="flex flex-col gap-3"
          role="status"
          aria-label="Loading engager retention"
        >
          <Skeleton className="h-12 w-full rounded-lg" />
          <Skeleton className="h-4 w-full rounded-lg" />
          <Skeleton className="h-28 w-full rounded-lg" />
        </div>
      </EvidenceCard>
    );
  }

  if (!hasMinimumEngagerRetentionSignal(data)) {
    return null;
  }

  const returningPct = Math.round(data.returningPercentage);
  const newPct = Math.max(0, 100 - returningPct);

  return (
    <EvidenceCard
      title="Engager retention"
      description={`${data.totalUnique.toLocaleString()} unique engagers · last ${data.periodDays}d`}
      action={
        <InvestigateButton
          accountId={resolvedId}
          metric="engagement"
          metricLabel="Engager retention"
          periodDays={data.periodDays}
        />
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <div className="flex h-3 overflow-hidden rounded-full bg-border">
            <div
              role="img"
              className="h-full"
              style={{
                width: `${returningPct}%`,
                background: "var(--color-chart-1)",
              }}
              aria-label={`Returning ${returningPct}%`}
            />
            <div
              role="img"
              className="h-full"
              style={{
                width: `${newPct}%`,
                background: "var(--color-chart-2)",
              }}
              aria-label={`New ${newPct}%`}
            />
          </div>
          <div className="flex flex-col gap-1 text-xs sm:flex-row sm:items-center sm:justify-between">
            <span className="flex min-w-0 items-center gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block size-2 rounded-full"
                style={{ background: "var(--color-chart-1)" }}
              />
              <span className="text-muted-foreground">
                Returning ·{" "}
                <span className="font-mono tabular-nums">{returningPct}%</span>{" "}
                · {formatCompact(data.returningCount)}
              </span>
            </span>
            <span className="flex min-w-0 items-center gap-1.5 sm:justify-end">
              <span
                aria-hidden="true"
                className="inline-block size-2 rounded-full"
                style={{ background: "var(--color-chart-2)" }}
              />
              <span className="text-muted-foreground">
                New · <span className="font-mono tabular-nums">{newPct}%</span>{" "}
                · {formatCompact(data.newCount)}
              </span>
            </span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[0.68rem] font-medium tracking-wide text-muted-foreground uppercase">
            Top returning engagers
          </div>
          {data.returningEngagers.length === 0 ? (
            <div className="rounded-lg border border-border bg-muted/35 px-3 py-2 text-sm text-muted-foreground">
              No repeat engagers in this window.
            </div>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {data.returningEngagers.slice(0, 5).map((eng) => (
                <li
                  key={eng.username}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/35 px-3 py-2 text-sm"
                >
                  <span className="min-w-0 truncate text-foreground">
                    @{eng.username}
                  </span>
                  <span className="font-mono tabular-nums text-muted-foreground">
                    {eng.engagementCount}×
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </EvidenceCard>
  );
}
