import { ShieldAlert } from "lucide-react";
import { InvestigateButton } from "@/components/analytics/InvestigateButton";
import { useAccountScopeStore } from "@/stores/useAccountScopeStore";
import {
  useOriginalityRisk,
  type OriginalityPlatform,
} from "@/hooks/useOriginalityRisk";
import { Badge } from "@/components/ui/Badge";
import { EvidenceCard } from "@/components/ui/EvidenceCard";
import { NovaEmpty, NovaMiniStat } from "@/components/ui/NovaPrimitives";
import { Skeleton } from "@/components/ui/Skeleton";

interface Props {
  platform: OriginalityPlatform;
  days: number;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
}

export function OriginalityRiskTile({
  platform,
  days,
  accountIds,
  groupId,
}: Props) {
  const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
  const accountId =
    scopedAccount && (platform === "all" || platform === scopedAccount.platform)
      ? scopedAccount.id
      : null;
  const effectivePlatform: OriginalityPlatform =
    platform === "instagram"
      ? "instagram"
      : platform === "threads"
        ? "threads"
        : "all";
  const data = useOriginalityRisk({
    platform: effectivePlatform,
    accountId,
    accountIds: accountId ? undefined : accountIds,
    groupId: accountId ? null : groupId,
    periodDays: Math.max(14, Math.min(90, days)),
  });

  if (data.hasError) {
    return (
      <EvidenceCard state="empty" eyebrow="Risk" title="Originality risk">
        <NovaEmpty
          title="Originality scoring unavailable"
          description="Originality scoring could not read a fingerprint payload for this scope. The score appears after recent posts have text and media fingerprints available for comparison."
        />
      </EvidenceCard>
    );
  }

  if (data.isLoading) {
    return (
      <EvidenceCard
        state="loading"
        eyebrow="Risk"
        title="Originality risk"
        description="Recent reuse scan · text similarity"
      >
        <div
          className="flex flex-col gap-3"
          role="status"
          aria-label="Loading originality risk"
        >
          <Skeleton className="h-28 w-full rounded-lg" />
          <Skeleton className="h-14 w-full rounded-lg" />
          <Skeleton className="h-24 w-full rounded-lg" />
        </div>
      </EvidenceCard>
    );
  }

  if (data.totalPosts === 0) {
    return (
      <EvidenceCard
        state="empty"
        eyebrow="Risk"
        title="Originality risk"
        description="No posts in scope"
      >
        <NovaEmpty
          title="No recent posts to score"
          description="No recent published posts were found in scope. The risk score appears once the selected window contains posts with captions or media that can be fingerprinted."
        />
      </EvidenceCard>
    );
  }

  const tone =
    data.severity === "crit"
      ? "var(--color-critical)"
      : data.severity === "warn"
        ? "var(--color-warning)"
        : "var(--color-health-good)";
  const topAccount = data.accountRisk[0] ?? null;
  const topPair = data.highRiskPairs[0] ?? null;

  return (
    <EvidenceCard
      eyebrow="Risk"
      title="Originality risk"
      description={`${data.riskPostCount}/${data.totalPosts} recent posts flagged · derived signal`}
      action={
        <InvestigateButton
          accountId={topAccount?.accountId ?? accountId}
          metric="reach"
          metricLabel="Originality risk"
          periodDays={data.periodDays}
        />
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-4">
          <RiskDial score={data.riskScore} color={tone} />
          <div className="min-w-0">
            <div
              className="text-4xl font-semibold tracking-[-0.04em] tabular-nums"
              style={{ color: tone }}
            >
              {data.riskScore}
            </div>
            <div className="mt-1 text-sm text-muted-foreground">risk score</div>
            <Badge
              tone="outline"
              className="mt-3 max-w-full gap-1.5 px-2 py-1 text-xs normal-case tracking-normal"
            >
              <ShieldAlert data-icon="inline-start" />
              <span className="truncate">
                {data.countdownToThreshold > 0
                  ? `${data.countdownToThreshold} posts before threshold`
                  : "threshold reached"}
              </span>
            </Badge>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <NovaMiniStat
            label="Flagged posts"
            value={data.riskPostCount.toLocaleString()}
            tone="danger"
          />
          <NovaMiniStat
            label="Reuse pairs"
            value={data.highRiskPairs.length.toLocaleString()}
          />
        </div>

        {topPair ? (
          <div className="rounded-lg border border-border bg-muted/35 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[0.68rem] font-medium uppercase tracking-wide text-muted-foreground">
                Closest match
              </span>
              <span
                className="font-mono text-xs tabular-nums"
                style={{ color: tone }}
              >
                {Math.round(topPair.similarity * 100)}%
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs leading-snug text-muted-foreground">
              {topPair.posts.map((post) => (
                <div
                  key={post.id}
                  className="min-w-0 rounded-lg border border-border bg-background/45 p-2"
                >
                  <div className="mb-1 font-mono text-[0.625rem] text-muted-foreground">
                    @{post.username ?? "account"}
                  </div>
                  <div className="line-clamp-2">
                    {post.preview || "No caption text"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-sm leading-relaxed text-muted-foreground">
            No high-similarity cross-account reuse detected in the current
            window.
          </p>
        )}
      </div>
    </EvidenceCard>
  );
}

function RiskDial({ score, color }: { score: number; color: string }) {
  const circumference = 2 * Math.PI * 42;
  const offset = circumference * (1 - Math.min(100, Math.max(0, score)) / 100);
  return (
    <svg
      viewBox="0 0 100 100"
      className="h-[112px] w-[112px]"
      role="img"
      aria-label={`Originality risk ${score}`}
    >
      <circle
        cx="50"
        cy="50"
        r="42"
        fill="none"
        stroke="var(--color-border)"
        strokeWidth="9"
      />
      <circle
        cx="50"
        cy="50"
        r="42"
        fill="none"
        stroke={color}
        strokeWidth="9"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 50 50)"
      />
      <text
        x="50"
        y="54"
        textAnchor="middle"
        className="fill-foreground font-mono text-[18px] font-semibold"
      >
        {score}
      </text>
    </svg>
  );
}
