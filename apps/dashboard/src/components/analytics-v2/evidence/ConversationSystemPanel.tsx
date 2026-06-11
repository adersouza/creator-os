import type { ScopedAccountLite } from "@/components/analytics/analyticsShared";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { AnalyticsActionLink } from "@/components/analytics-v2/AnalyticsActionLink";
import { Inbox, MessageCircle } from "lucide-react";
import { useGhostPostCount } from "@/hooks/useGhostPostCount";
import {
  type OriginalityPlatform,
  useOriginalityRisk,
} from "@/hooks/useOriginalityRisk";
import { useQuoteReplyRatio } from "@/hooks/useQuoteReplyRatio";
import { useReplyChainDistribution } from "@/hooks/useReplyChainDistribution";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import { scopedRoute } from "@/lib/scopedRoutes";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty, NovaMiniStat } from "@/components/ui/NovaPrimitives";
import { cn } from "@/lib/utils";

interface Props {
  days: number;
  scopedAccount?: ScopedAccountLite | null | undefined;
  accountIds?: string[] | undefined;
  platform?: OriginalityPlatform | undefined;
}

export function ConversationSystemPanel({
  days,
  scopedAccount,
  accountIds,
  platform = "threads",
}: Props) {
  const storeScope = useAccountScopeStore((s) => s.scopedAccount);
  const scope = scopedAccount ?? storeScope;
  const accountId = scope?.platform === "threads" && scope.id ? scope.id : null;
  const threadScopedIds = scope
    ? scope.platform === "threads" && scope.id
      ? [scope.id]
      : []
    : accountIds;
  const replyDepth = useReplyChainDistribution(days, accountId);
  const quoteReply = useQuoteReplyRatio(days, accountId, threadScopedIds);
  const ghost = useGhostPostCount(threadScopedIds);
  const originality = useOriginalityRisk({
    platform,
    accountId,
    periodDays: Math.max(14, Math.min(90, days)),
  });

  const totalDepth = replyDepth.buckets.reduce(
    (sum, bucket) => sum + bucket.count,
    0,
  );
  const deepPct =
    totalDepth > 0 ? (replyDepth.deepThreads / totalDepth) * 100 : 0;
  const quoteRatio = quoteReply.fleetRatio ?? 0;
  const totalQuotes = quoteReply.accounts.reduce(
    (sum, account) => sum + account.quotes,
    0,
  );
  const totalReplies = quoteReply.accounts.reduce(
    (sum, account) => sum + account.replies,
    0,
  );
  const ghostLinkPct =
    ghost.total > 0 ? Math.round((ghost.withLinks / ghost.total) * 100) : 0;
  const systemStatus = getSystemStatus({
    deepPct,
    quoteRatio,
    ghostTotal: ghost.total,
    riskScore: originality.riskScore,
  });

  return (
    <EvidenceCard
      eyebrow="Conversation system"
      title="Is conversation helping reach"
      description={`Threads · last ${days}d · replies, quotes, suppression, reuse`}
      action={
        <>
          <AnalyticsActionLink
            to={scopedRoute("/inbox", {
              scopedAccount: scope,
              accountIds,
              platform: "threads",
            })}
            label="Review replies"
            icon={Inbox}
            tone={systemStatus.tone === "bad" ? "primary" : "neutral"}
          />
          <InvestigateButton
            accountId={accountId}
            metric="engagement"
            metricLabel="Conversation system"
            periodDays={days}
          />
        </>
      }
      contentClassName="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(280px,0.85fr)]"
    >
      <section className="flex min-w-0 flex-col gap-4">
        <div className="grid gap-4 rounded-xl border border-border bg-muted/25 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
          <div className="min-w-0">
            <span className="text-[0.72rem] font-medium tracking-wide text-muted-foreground uppercase">
              System state
            </span>
            <strong
              className={cn(
                "mt-2 block text-3xl font-semibold tracking-tight text-foreground",
                systemStatus.tone === "good" && "text-success",
                systemStatus.tone === "bad" && "text-danger",
                systemStatus.tone === "warn" && "text-warning",
              )}
            >
              {systemStatus.label}
            </strong>
            <small className="mt-1 block text-[0.78rem] text-muted-foreground">
              {systemStatus.caption}
            </small>
          </div>
          <ConversationDial
            value={systemStatus.score}
            tone={systemStatus.tone}
          />
        </div>

        <div className="rounded-xl border border-border bg-muted/25 p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="text-[0.72rem] font-medium tracking-wide text-muted-foreground uppercase">
              Reply depth
            </span>
            <strong className="text-[0.78rem] font-medium text-foreground">
              {deepPct.toFixed(1)}% deep-chain
            </strong>
          </div>
          <div className="grid h-44 grid-cols-4 items-end gap-3">
            {replyDepth.buckets.map((bucket) => {
              const max = Math.max(
                1,
                ...replyDepth.buckets.map((item) => item.count),
              );
              const pct = (bucket.count / max) * 100;
              const isDeep = bucket.depth === "4+ turns";
              return (
                <div
                  key={bucket.depth}
                  className="flex min-h-0 flex-col items-center gap-2"
                >
                  <i
                    className={cn(
                      "w-full rounded-t-md bg-muted-foreground/45",
                      isDeep && "bg-primary",
                    )}
                    style={{ height: `${Math.max(5, pct)}%` }}
                  />
                  <span className="text-center text-[0.7rem] text-muted-foreground">
                    {bucket.depth.replace(" turns", "")}
                  </span>
                  <strong className="text-[0.72rem] font-medium tabular-nums text-foreground">
                    {bucket.count}
                  </strong>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <aside className="flex min-w-0 flex-col gap-3">
        <div className="rounded-xl border border-border bg-muted/25 p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="text-[0.72rem] font-medium tracking-wide text-muted-foreground uppercase">
              Conversation mode
            </span>
            <strong className="text-[0.78rem] font-medium text-foreground">
              {quoteRatio >= 1 ? "Quote-led" : "Reply-led"}
            </strong>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <NovaMiniStat label="Quotes" value={totalQuotes.toLocaleString()} />
            <NovaMiniStat label="Replies" value={totalReplies.toLocaleString()} />
            <NovaMiniStat label="Ratio" value={quoteRatio.toFixed(2)} />
          </div>
          <div className="mt-3 flex flex-col gap-2">
            {quoteReply.accounts.slice(0, 3).map((account) => (
              <div
                key={account.accountId}
                className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background/35 px-3 py-2"
              >
                <span className="min-w-0 truncate text-[0.78rem] text-muted-foreground">
                  @{account.username ?? "threads"}
                </span>
                <strong className="shrink-0 text-[0.78rem] font-medium tabular-nums text-foreground">
                  {account.ratio == null ? "-" : account.ratio.toFixed(2)}
                </strong>
              </div>
            ))}
            {quoteReply.accounts.length === 0 ? (
              <NovaEmpty
                className="p-4"
                icon={<MessageCircle data-icon aria-hidden="true" />}
                title="No quote/reply rows yet"
                description="Threads quote and reply account rows will appear once synced posts include both sides of the conversation split."
              />
            ) : null}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-muted/25 p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="text-[0.72rem] font-medium tracking-wide text-muted-foreground uppercase">
              Suppression queue
            </span>
            <strong
              className={cn(
                "text-[0.78rem] font-medium text-foreground",
                ghost.total > 0 ? "text-danger" : "text-success",
              )}
            >
              {ghost.total > 0 ? `${ghost.total} posts` : "Clear"}
            </strong>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-border/55">
            <i
              className="block h-full rounded-full bg-danger"
              style={{ width: `${Math.min(100, ghost.total * 10)}%` }}
            />
          </div>
          <div className="mt-3 flex items-center justify-between gap-3 text-[0.72rem] text-muted-foreground">
            <span>{ghost.withLinks} with links</span>
            <span>{ghostLinkPct}% link share</span>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-muted/25 p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="text-[0.72rem] font-medium tracking-wide text-muted-foreground uppercase">
              Originality risk
            </span>
            <strong
              className={cn(
                "text-[0.78rem] font-medium tabular-nums text-foreground",
                riskTone(originality.severity) === "good" && "text-success",
                riskTone(originality.severity) === "bad" && "text-danger",
                riskTone(originality.severity) === "warn" && "text-warning",
              )}
            >
              {originality.riskScore}
            </strong>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-border/55">
            <i
              className="block h-full rounded-full bg-primary"
              style={{ width: `${Math.min(100, originality.riskScore)}%` }}
            />
          </div>
          <div className="mt-3 flex items-center justify-between gap-3 text-[0.72rem] text-muted-foreground">
            <span>{originality.riskPostCount} flagged</span>
            <span>{originality.countdownToThreshold} before threshold</span>
          </div>
        </div>
      </aside>
    </EvidenceCard>
  );
}

function ConversationDial({
  value,
  tone,
}: {
  value: number;
  tone: "good" | "bad" | "warn" | "neutral";
}) {
  const color =
    tone === "good"
      ? "var(--color-health-good)"
      : tone === "bad"
        ? "var(--color-oxblood)"
        : tone === "warn"
          ? "var(--color-gold)"
          : "var(--color-muted-foreground)";
  const circumference = 2 * Math.PI * 36;
  const offset = circumference * (1 - Math.min(100, Math.max(0, value)) / 100);
  return (
    <svg
      viewBox="0 0 90 90"
      role="img"
      aria-label={`Conversation system score ${Math.round(value)}`}
    >
      <circle
        cx="45"
        cy="45"
        r="36"
        fill="none"
        stroke="var(--color-border)"
        strokeWidth="8"
      />
      <circle
        cx="45"
        cy="45"
        r="36"
        fill="none"
        stroke={color}
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        strokeWidth="8"
        transform="rotate(-90 45 45)"
      />
      <text
        x="45"
        y="50"
        textAnchor="middle"
        className="fill-foreground font-mono text-[17px] font-semibold"
      >
        {Math.round(value)}
      </text>
    </svg>
  );
}

function getSystemStatus({
  deepPct,
  quoteRatio,
  ghostTotal,
  riskScore,
}: {
  deepPct: number;
  quoteRatio: number;
  ghostTotal: number;
  riskScore: number;
}) {
  let score = 62;
  score += Math.min(18, deepPct * 1.2);
  if (quoteRatio > 1.4) score -= 10;
  if (quoteRatio > 2) score -= 8;
  score -= Math.min(22, ghostTotal * 3);
  score -= Math.min(18, riskScore * 0.22);
  score = Math.max(0, Math.min(100, score));
  if (score < 40) {
    return {
      score,
      label: "At risk",
      caption: "Conversation is likely hurting reach.",
      tone: "bad" as const,
    };
  }
  if (score < 64) {
    return {
      score,
      label: "Watch",
      caption: "Mixed signals need triage.",
      tone: "warn" as const,
    };
  }
  return {
    score,
    label: "Healthy",
    caption: "Replies and originality are supporting distribution.",
    tone: "good" as const,
  };
}

function riskTone(severity: "good" | "warn" | "crit") {
  if (severity === "crit") return "bad";
  if (severity === "warn") return "warn";
  return "good";
}
