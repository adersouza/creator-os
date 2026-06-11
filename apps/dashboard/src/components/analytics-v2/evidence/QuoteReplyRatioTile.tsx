import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { useQuoteReplyRatio } from "@/hooks/useQuoteReplyRatio";
import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty, NovaMiniStat } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";

interface Props {
  days: number;
  scopedAccount?: ScopedAccountLite | undefined;
  accountIds?: string[] | undefined;
}

export function QuoteReplyRatioTile({
  days,
  scopedAccount,
  accountIds,
}: Props) {
  const accountId =
    scopedAccount?.platform === "threads" && scopedAccount.id
      ? scopedAccount.id
      : null;
  const threadScopedIds = scopedAccount
    ? scopedAccount.platform === "threads" && scopedAccount.id
      ? [scopedAccount.id]
      : []
    : accountIds;
  const { fleetRatio, accounts, isLoading, hasError } = useQuoteReplyRatio(
    days,
    accountId,
    threadScopedIds,
  );

  if (hasError) {
    return (
      <EvidenceCard state="empty" eyebrow="Threads" title="Quote / reply ratio">
        <NovaEmpty
          title="Conversation split unavailable"
          description="Threads quote and reply counts did not return for this scope. The ratio stays empty until the endpoint can provide both sides of the conversation split."
        />
      </EvidenceCard>
    );
  }

  if (!isLoading && fleetRatio == null && accounts.length === 0) {
    return (
      <EvidenceCard state="empty" eyebrow="Threads" title="Quote / reply ratio">
        <NovaEmpty
          title="No quote/reply signal yet"
          description="No Threads posts in this window have enough quote and reply data yet. The tile fills once Threads posts collect conversation metrics."
        />
      </EvidenceCard>
    );
  }

  if (isLoading && fleetRatio == null && accounts.length === 0) {
    return (
      <EvidenceCard
        state="loading"
        eyebrow="Threads"
        title="Quote / reply ratio"
        description={`Threads · last ${days}d`}
      >
        <div
          className="flex flex-col gap-3"
          role="status"
          aria-label="Loading quote reply ratio"
        >
          <Skeleton className="h-16 w-full rounded-lg" />
          <Skeleton className="h-14 w-full rounded-lg" />
          <Skeleton className="h-24 w-full rounded-lg" />
        </div>
      </EvidenceCard>
    );
  }

  const ratio = fleetRatio ?? 0;
  const totalQuotes = accounts.reduce(
    (sum, account) => sum + account.quotes,
    0,
  );
  const totalReplies = accounts.reduce(
    (sum, account) => sum + account.replies,
    0,
  );
  const tone =
    ratio >= 1
      ? { label: "Quote-led", color: "var(--color-gold)" }
      : { label: "Reply-led", color: "var(--color-health-good)" };

  return (
    <EvidenceCard
      eyebrow="Threads"
      title="Quote / reply ratio"
      description={`Threads · last ${days}d`}
      action={
        <InvestigateButton
          accountId={accountId}
          metric="engagement"
          metricLabel="Quote / reply ratio"
          periodDays={days}
        />
      }
    >
      <div className="flex flex-col gap-5">
        <div className="flex items-end justify-between gap-4">
          <div>
            <div className="text-4xl font-semibold tracking-[-0.04em] tabular-nums text-foreground">
              {ratio.toFixed(2)}
            </div>
            <div className="mt-1 text-sm text-muted-foreground">
              quotes per reply
            </div>
          </div>
          <div className="text-right">
            <div className="text-[0.68rem] font-medium tracking-wide text-muted-foreground uppercase">
              Conversation mode
            </div>
            <div
              className="mt-1 text-[0.875rem] font-semibold"
              style={{ color: tone.color }}
            >
              {tone.label}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <NovaMiniStat
            label="Quotes"
            value={totalQuotes.toLocaleString()}
            tone="warning"
          />
          <NovaMiniStat
            label="Replies"
            value={totalReplies.toLocaleString()}
            tone="success"
          />
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[0.68rem] font-medium tracking-wide text-muted-foreground uppercase">
            Highest-ratio accounts
          </div>
          <div className="flex flex-col gap-1.5">
            {accounts.slice(0, 4).map((account) => (
              <div
                key={account.accountId}
                className="grid grid-cols-[minmax(0,1fr)_48px_48px_48px] items-center gap-2 rounded-lg border border-border bg-muted/35 px-3 py-2 text-xs"
              >
                <span className="truncate text-foreground">
                  @{account.username ?? "threads"}
                </span>
                <span className="text-right font-mono tabular-nums text-muted-foreground">
                  {account.ratio == null ? "—" : account.ratio.toFixed(2)}
                </span>
                <span className="text-right font-mono tabular-nums text-muted-foreground">
                  {account.quotes}
                </span>
                <span className="text-right font-mono tabular-nums text-muted-foreground">
                  {account.replies}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </EvidenceCard>
  );
}
