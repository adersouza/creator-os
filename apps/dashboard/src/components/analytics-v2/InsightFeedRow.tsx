import { useMemo } from 'react';
import { useAnomalyFeed, type AnomalyAlert } from '@/hooks/useAnomalyFeed';
import { useConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { useAccountScopeStore } from '@/stores/useAccountScopeStore';
import { NovaEmpty } from '@/components/ui/NovaPrimitives';
import { Skeleton } from '@/components/ui/Skeleton';
import type { Platform } from './shared';
import { InsightCard, type InsightCardSpec } from './insights/InsightCard';

interface Props {
  platform: Platform;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
  scopeLabel?: string | undefined;
}

/**
 * §5 insight feed — three equal cards driven by the live anomaly feed.
 * Filters by current platform, ranks by severity (crit > warn > note), takes
 * the top 3. Falls back to an empty-state tile when nothing's flagged in
 * the last 72h.
 *
 * Earlier this row shipped hardcoded mock data (`@lolanovaa55`, `aud_7f3a1b`,
 * "Apr 14") to production — a regression caught during the Wave 1 build.
 */
export function InsightFeedRow({ platform, accountIds, groupId, scopeLabel }: Props) {
  const scopedAccount = useAccountScopeStore((s) => s.scopedAccount);
  const { alerts, isLoading, hasError } = useAnomalyFeed({ hours: 72 }, 'all', scopedAccount, accountIds, groupId);
  const { accounts } = useConnectedAccounts();

  const ranked = useMemo(() => {
    const filtered = alerts.filter((a) => matchesPlatform(a, platform));
    return [...filtered]
      .sort((a, b) => severityRank(b.severity) - severityRank(a.severity))
      .slice(0, 3);
  }, [alerts, platform]);

  const cards = useMemo(() => {
    const usernameById = new Map<string, string>();
    for (const acct of accounts) {
      if (acct.handle) usernameById.set(acct.id, acct.handle);
    }
    return ranked.map((alert) => ({
      alert,
      spec: alertToCard(alert, usernameById),
    }));
  }, [ranked, accounts]);

  /**
   * Returns a click handler when the alert is account-scoped (drills into
   * that account), or `undefined` for fleet-level alerts so the card renders
   * as a plain article — no false affordance, no scroll-to-grid surprise.
   */
  const handlerFor = (alert: AnomalyAlert): (() => void) | undefined => {
    const accountId = alert.accountId ?? alert.instagramAccountId;
    if (!accountId) return undefined;
    const accountMeta = accounts.find((a) => a.id === accountId);
    if (!accountMeta) return undefined;
    return () => {
      useAccountScopeStore.getState().setScope({
        id: accountMeta.id,
        handle: accountMeta.handle,
        platform: accountMeta.platform,
      });
    };
  };

  const gridClass =
    cards.length <= 1
      ? "grid grid-cols-1 gap-4 items-stretch"
      : cards.length === 2
        ? "grid grid-cols-1 gap-4 items-stretch lg:grid-cols-2"
        : "grid grid-cols-1 gap-4 items-stretch lg:grid-cols-3";

  return (
    <div className={gridClass}>
      {isLoading && cards.length === 0 ? (
        <InsightFeedFallback message="Pulling the anomaly feed..." kind="loading" colSpan={3} />
      ) : hasError && cards.length === 0 ? (
        <InsightFeedFallback
          message="Could not load anomaly alerts right now."
          kind="error"
          colSpan={3}
        />
      ) : cards.length === 0 ? (
        <InsightFeedFallback
          message={`Nothing flagged for ${scopeLabel ?? 'this view'} in the last 72h. The nightly anomaly pass refreshes this row.`}
          kind="clear"
          colSpan={3}
        />
      ) : (
        cards.map(({ alert, spec }, i) => (
          <InsightCard
            key={`${alert.id}-${i}`}
            spec={spec}
            onClick={handlerFor(alert)}
          />
        ))
      )}
    </div>
  );
}

function matchesPlatform(alert: AnomalyAlert, platform: Platform): boolean {
  if (platform === 'all') return true;
  if (platform === 'threads') return alert.platform === 'threads';
  return alert.platform === 'instagram';
}

function severityRank(sev: string | null | undefined): number {
  const s = (sev ?? '').toLowerCase();
  if (s === 'critical' || s === 'crit' || s === 'high') return 3;
  if (s === 'warning' || s === 'warn' || s === 'medium') return 2;
  if (s === 'info' || s === 'note' || s === 'low') return 1;
  return 0;
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return '';
  try {
    return new Date(iso)
      .toLocaleString(undefined, { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
      .replace(' GMT', '');
  } catch {
    return '';
  }
}

function alertToCard(
  alert: AnomalyAlert,
  usernameById: Map<string, string>,
): InsightCardSpec {
  const accountKey = alert.accountId ?? alert.instagramAccountId;
  const username = accountKey ? usernameById.get(accountKey) : null;
  const subtitle = username
    ? `@${username}`
    : alert.platform === 'threads'
      ? 'Threads · fleet'
      : alert.platform === 'instagram'
        ? 'Instagram · fleet'
        : 'Fleet';

  return {
    timestamp: formatTimestamp(alert.createdAt),
    subtitle,
    title: alert.title,
    body: alert.description ?? summarizeInsightText(alert.aiAnalysis) ?? alert.alertType,
    evidenceLabel: "Source",
    evidenceValue: sourceLabelForAlert(alert),
  };
}

function sourceLabelForAlert(alert: AnomalyAlert): string {
  const hasAi = !!alert.aiAnalysis?.trim();
  const hasMetrics = alert.data && Object.keys(alert.data).length > 0;
  if (hasAi && hasMetrics) return 'anomaly_alerts · metrics + AI note';
  if (hasAi) return 'anomaly_alerts · AI note';
  if (hasMetrics) return 'anomaly_alerts · metrics';
  return 'anomaly_alerts';
}

function summarizeInsightText(text: string | null | undefined): string | null {
  if (!text) return null;
  const normalized = text
    .replace(/\*\*/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!normalized) return null;

  const firstSentence = normalized.match(/[^.!?]+[.!?]/)?.[0]?.trim() ?? normalized;
  const summary = firstSentence.replace(/^okay,\s*/i, '').replace(/^here'?s\s+/i, '');
  return summary.length > 220 ? `${summary.slice(0, 217).trim()}...` : summary;
}

function InsightFeedFallback({
  message,
  kind,
  colSpan,
}: {
  message: string;
  kind: "loading" | "error" | "clear";
  colSpan: number;
}) {
  return (
    <NovaEmpty
      className={colSpan === 3 ? 'w-full lg:col-span-3' : 'w-full'}
      title={
        kind === "error"
          ? "Anomaly feed unavailable"
          : kind === "loading"
            ? "Pulling anomaly feed"
            : "No anomalies flagged"
      }
      description={
        kind === "error"
          ? `${message} Refresh to retry the live anomaly read; no alerts are being fabricated.`
          : kind === "loading"
            ? "Juno33 is resolving the latest anomaly pass and will keep this row empty until live alerts return."
            : message
      }
    >
      {kind === "loading" ? (
        <div className="grid w-full max-w-xl gap-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
        </div>
      ) : null}
    </NovaEmpty>
  );
}
