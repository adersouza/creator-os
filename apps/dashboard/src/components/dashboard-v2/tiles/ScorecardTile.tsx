import { useFleetHealthAccounts } from '@/hooks/useFleetHealthAccounts';
import { useFleetMetrics } from '@/hooks/useFleetMetrics';
import { useAccountTokenDays } from '@/hooks/useAccountTokenDays';
import { useStrikesCount } from '@/hooks/useStrikesCount';
import { BulletChart } from '../atoms/BulletChart';
import { Badge } from '@/components/ui/Badge';
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Separator } from '@/components/ui/Separator';
import { fleetPlatformFor, shouldAuditQwe, type Platform } from '../shared';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';
import {
  dashboardTimeframeToFleetMetrics,
  type DashboardTimeframe,
} from '@/lib/dashboardUrlState';

interface Props {
  platform: Platform;
  timeframe: DashboardTimeframe;
  scopedAccount: AccountScopeValue | null;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
}

/**
 * Scorecard #9 — two live modes:
 *
 * 1. **Account-scoped** (when `scopedAccount` is set): four linear bullets
 *    showing Reach Δ, Quality, Token days-left, and 90d Strikes for the selected account.
 *    Research update: linear bullets replace radial rings so every score can be read
 *    on a common length scale instead of angle/arc.
 *
 * 2. **Fleet aggregate** (when scope is null): four real bullets — Reach Δ
 *    and quality score from `useFleetMetrics`, plus minimum token days-left from
 *    fleet health, plus strikes from the moderation/health endpoint.
 */
export function ScorecardTile({ platform, timeframe, scopedAccount, accountIds, groupId }: Props) {
  if (scopedAccount) {
    return <AccountScorecard platform={platform} timeframe={timeframe} scopedAccount={scopedAccount} />;
  }
  return <FleetScorecard platform={platform} timeframe={timeframe} accountIds={accountIds} groupId={groupId} />;
}

function reachDeltaToBulletFill(delta: number | null): number {
  if (delta == null || delta <= 0) return 0;
  // Preserves breakout ordering after +50%; linear mapping made +60% and +400% identical.
  if (delta <= 50) return Math.min(80, (delta / 50) * 80);
  return Math.min(100, 80 + ((Math.min(delta, 200) - 50) / 150) * 20);
}

// =========================================================================
// Account-scoped — 4 donut rings
// =========================================================================
function AccountScorecard({
  platform,
  timeframe,
  scopedAccount,
}: {
  platform: Platform;
  timeframe: DashboardTimeframe;
  scopedAccount: AccountScopeValue;
}) {
  const metricsTimeframe = dashboardTimeframeToFleetMetrics(timeframe);
  const metrics = useFleetMetrics(metricsTimeframe, fleetPlatformFor(platform), scopedAccount);
  const acct = metrics.accounts.find((a) => a.accountId === scopedAccount.id);
  const token = useAccountTokenDays({
    accountId: scopedAccount.id,
    platform: scopedAccount.platform,
  });
  const strikes = useStrikesCount({
    platform: scopedAccount.platform,
    accountId: scopedAccount.id,
    periodDays: 90,
  });

  const reachDelta = acct?.reachDeltaPct ?? null;
  const rawQwe = acct?.eqs ?? 0;
  // Per-account scorecards don't yet have a per-account qualifying-post
  // count from the RPC — fall back to the heuristic gate. When that lands
  // (FleetAccountAggregate gains a sample-size field), thread it through
  // here too.
  const qweAuditRequired = shouldAuditQwe(rawQwe / 10, (acct?.sends ?? 0) + (acct?.saves ?? 0));
  const qwe = qweAuditRequired ? 0 : rawQwe;

  const reachTone = reachDelta == null ? 'muted' : reachDelta < 0 ? 'crit' : reachDelta < 5 ? 'warn' : 'good';

  const qweTone = qweAuditRequired ? 'muted' : qwe < 30 ? 'crit' : qwe < 60 ? 'warn' : 'ox';

  const tokenDays = token.daysLeft;
  const tokenTone = tokenDays == null ? 'unknown' : tokenDays < 7 ? 'crit' : tokenDays < 21 ? 'warn' : 'good';
  const timeframeLabel = timeframe.toUpperCase();

  return (
    <NovaCard
      className="h-full"
      contentClassName="flex h-full flex-col gap-4"
      eyebrow="Performance summary"
      title={`@${scopedAccount.handle}`}
      description={`${timeframeLabel} · reach, quality, token health, and strikes`}
      action={<Badge tone="outline">{scopedAccount.platform.toUpperCase()}</Badge>}
    >
        <div className="grid gap-3 sm:grid-cols-2">
          <ScorecardBullet
            label="Reach Δ"
            value={reachDeltaToBulletFill(reachDelta)}
            display={
              reachDelta == null
                ? metrics.isLoading
                  ? 'Sync'
                  : '0%'
                : `${reachDelta >= 0 ? '+' : ''}${Math.round(reachDelta)}%`
            }
            target={50}
            tone={reachTone}
            muted={reachDelta == null}
          />
          <ScorecardBullet
            label="Quality"
            value={Math.max(0, Math.min(100, qwe))}
            display={qweAuditRequired ? 'Needs sample' : qwe > 0 ? `${(qwe / 10).toFixed(1)}/10` : '0/10'}
            target={60}
            tone={qweTone}
            muted={qweAuditRequired || qwe <= 0}
          />
          <ScorecardBullet
            label="Token"
            value={tokenDays == null ? 0 : Math.max(0, Math.min(100, (tokenDays / 60) * 100))}
            display={tokenDays == null ? token.isLoading ? 'Sync' : 'Unavailable' : `${tokenDays}d`}
            target={35}
            tone={tokenTone}
            muted={token.isLoading}
          />
          <ScorecardBullet
            label="Strikes"
            value={Math.max(0, Math.min(100, (strikes.ringValue / 3) * 100))}
            display={strikes.hasError ? 'Retry' : `${strikes.ringValue}/90d`}
            target={34}
            tone={strikes.hasError ? 'muted' : strikes.severity}
            muted={strikes.isLoading || strikes.hasError}
            inverse
            title="Strikes: count of policy/health flags in the last 30d. Account target <=12."
          />
        </div>

        {metrics.isLoading || token.isLoading || strikes.isLoading ? (
          <NovaEmpty
            className="mt-4 min-h-20 p-4"
            title="Syncing performance signals"
            description="Inputs fill as reach, account health, and issue history resolve."
          />
        ) : qweAuditRequired ? (
          <div className="mt-4 text-xs text-muted-foreground">
            Quality score unavailable: needs more qualifying post data.
          </div>
        ) : !acct ? (
          <div className="mt-4 text-xs text-muted-foreground">
            No 30d activity recorded for this account yet. Score bullets fill once posts publish.
          </div>
        ) : strikes.hasError ? (
          <div className="mt-4 text-xs text-muted-foreground">
            Strike count unavailable. Reach Δ, quality score, and token health are live.
          </div>
        ) : null}
    </NovaCard>
  );
}

// =========================================================================
// Fleet aggregate — 4 donut rings (band-2 left, ALL view)
// =========================================================================
function FleetScorecard({
  platform,
  timeframe,
  accountIds,
  groupId,
}: {
  platform: Platform;
  timeframe: DashboardTimeframe;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
}) {
  const metricsTimeframe = dashboardTimeframeToFleetMetrics(timeframe);
  const metrics = useFleetMetrics(metricsTimeframe, fleetPlatformFor(platform), null, { accountIds, groupId });
  const health = useFleetHealthAccounts(1);
  const strikes = useStrikesCount({
    platform: fleetPlatformFor(platform),
    periodDays: 90,
  });

  // No posts in the current window → treat Reach Δ + quality score as empty-state, not
  // as "catastrophic -100% drop". The hook honestly returns -100 when prior
  // had reach and current is zero (other consumers — HeroTile, ribbon,
  // anomaly feed — want that signal); the donut tile's UX intent is "data
  // or empty-state", so we gate locally.
  const noData = !metrics.isLoading && (metrics.postCount ?? 0) === 0;

  const reachDelta = noData ? null : metrics.reachDeltaPct;
  const rawQwe = noData ? 0 : (metrics.eqs ?? 0);
  const qweAuditRequired = shouldAuditQwe(
    rawQwe / 10,
    metrics.sendsPlusSaves,
    metrics.eqsQualifyingPostCount,
  );
  const qwe = qweAuditRequired ? 0 : rawQwe;

  const reachTone: 'good' | 'warn' | 'crit' | 'muted' =
    reachDelta == null ? 'muted' : reachDelta < 0 ? 'crit' : reachDelta < 5 ? 'warn' : 'good';

  const qweTone: 'ox' | 'muted' = noData || qweAuditRequired ? 'muted' : 'ox';
  const tokenDays = health.summary.minTokenDaysLeft;
  const tokenTone: 'good' | 'warn' | 'crit' | 'muted' =
    tokenDays == null ? 'muted' : tokenDays < 0 ? 'crit' : tokenDays < 7 ? 'crit' : tokenDays < 21 ? 'warn' : 'good';
  const strikePct =
    strikes.totalAccounts > 0
      ? Math.max(0, Math.min(100, (strikes.ringValue / strikes.totalAccounts) * 100))
      : 0;

  const timeframeLabel = timeframe.toUpperCase();
  const platformLabel = platform === 'all' ? `fleet · ${timeframeLabel}` : platform === 'threads' ? `Threads · ${timeframeLabel}` : `Instagram · ${timeframeLabel}`;

  return (
    <NovaCard
      className="h-full"
      contentClassName="flex h-full flex-col gap-4"
      eyebrow="Performance summary"
      title={platformLabel}
      description="Fleet reach, quality, token health, and strikes"
      action={<Badge tone="outline">{platform.toUpperCase()}</Badge>}
    >
        <div className="grid gap-3 sm:grid-cols-2">
          <ScorecardBullet
            label="Reach Δ"
            value={reachDeltaToBulletFill(reachDelta)}
            display={
              reachDelta == null
                ? metrics.isLoading
                  ? 'Sync'
                  : '0%'
                : `${reachDelta >= 0 ? '+' : ''}${Math.round(reachDelta)}%`
            }
            target={50}
            tone={reachTone}
            muted={noData || reachDelta == null}
          />
          <ScorecardBullet
            label="Quality"
            value={Math.max(0, Math.min(100, qwe))}
            display={qweAuditRequired ? 'Needs sample' : qwe > 0 ? `${(qwe / 10).toFixed(1)}/10` : '0/10'}
            target={60}
            tone={qweTone}
            muted={noData || qweAuditRequired || qwe <= 0}
          />
          <ScorecardBullet
            label="Token"
            value={tokenDays == null ? 0 : Math.max(0, Math.min(100, (tokenDays / 60) * 100))}
            display={tokenDays == null ? health.isLoading ? 'Sync' : 'Unavailable' : tokenDays < 0 ? '0d' : `${tokenDays}d`}
            target={35}
            tone={tokenTone}
            muted={health.isLoading || tokenDays == null}
          />
          <ScorecardBullet
            label="Strikes"
            value={strikePct}
            display={strikes.hasError ? 'Retry' : `${strikes.ringValue}/90d`}
            target={12}
            tone={strikes.hasError ? 'muted' : strikes.severity}
            muted={strikes.isLoading || strikes.hasError}
            inverse
            title="Strikes: count of policy/health flags in the last 30d. Fleet target <=34."
          />
        </div>

        {metrics.isLoading || strikes.isLoading ? (
          <NovaEmpty
            className="mt-4 min-h-20 p-4"
            title="Syncing performance signals"
            description="Inputs fill as reach, content quality, account health, and issue history resolve."
          />
        ) : qweAuditRequired ? (
          <div className="mt-4 text-xs text-muted-foreground">
            Quality score unavailable: needs more qualifying post data.
          </div>
        ) : health.isLoading ? (
          <div className="mt-4 text-xs text-muted-foreground">
            Token health syncing. Reach Δ + quality score are live.
          </div>
        ) : health.hasError ? (
          <div className="mt-4 text-xs text-muted-foreground">
            Token health unavailable. Reach Δ + quality score are live.
          </div>
        ) : strikes.hasError ? (
          <div className="mt-4 text-xs text-muted-foreground">
            Strike count unavailable. Reach Δ, quality score, and token health are live.
          </div>
        ) : null}
    </NovaCard>
  );
}

function ScorecardBullet({
  label,
  value,
  display,
  target,
  tone,
  muted = false,
  inverse = false,
  title,
}: {
  label: string;
  value: number;
  display: string;
  target: number;
  tone: 'good' | 'warn' | 'crit' | 'muted' | 'ox' | 'unknown';
  muted?: boolean | undefined;
  inverse?: boolean | undefined;
  title?: string | undefined;
}) {
  return (
    <div
      className="rounded-lg border border-border bg-muted/35 p-3"
      data-muted={muted ? "true" : undefined}
      data-inverse={inverse ? "true" : undefined}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <span className="text-xs font-medium text-muted-foreground" title={title}>
          {label}
        </span>
        <b className="text-sm font-semibold tabular-nums text-foreground" data-tone={tone}>
          {display}
        </b>
      </div>
      <Separator className="mb-2 opacity-60" />
      <BulletChart
        value={value}
        target={target}
        fullWidth
        highlightTop={!inverse && (tone === 'good' || tone === 'ox')}
      />
    </div>
  );
}
