import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, CalendarPlus, CheckCircle2, ExternalLink, GitCompare, ShieldCheck } from 'lucide-react';
import { z } from 'zod';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { NovaCard } from "@/components/ui/NovaPrimitives";
import { useOperatorSnapshot } from '@/hooks/useOperatorSnapshot';
import { apiFetch } from '@/lib/apiFetch';
import { appToast } from '@/lib/toast';
import type { Platform } from './shared';

type PortfolioMatrixProps = {
  capacityStart: string;
  groupFilter: string;
  platformFilter: Platform | 'all';
  scopedAccount?: { id: string; handle: string; platform?: Platform | undefined } | null;
  accountIds?: string[] | undefined;
  accountId?: string | null | undefined;
  accountHandle?: string | null | undefined;
  onComposeForAccountDate: (accountId: string, dateKey: string) => void;
};

type CapacityAccount = ReturnType<typeof useOperatorSnapshot>['snapshot']['fleetCapacity']['accounts'][number];
type CapacityDay = CapacityAccount['days'][number];

const dryRunResponseSchema = z.object({
	success: z.boolean().optional(),
	intentId: z.string(),
	actionName: z.string().optional(),
});

const requestApprovalResponseSchema = z.object({
	success: z.boolean().optional(),
	approvalId: z.string(),
	intentId: z.string(),
});

function toneClass(tone: string) {
  if (tone === 'critical') return 'border-[color-mix(in_srgb,var(--color-critical)_35%,transparent)] bg-[color-mix(in_srgb,var(--color-critical)_12%,transparent)] text-[var(--color-critical)]';
  if (tone === 'warning') return 'border-[color-mix(in_srgb,var(--color-warning)_35%,transparent)] bg-[color-mix(in_srgb,var(--color-warning)_14%,transparent)] text-foreground';
  return 'border-[color-mix(in_srgb,var(--color-health-good)_28%,transparent)] bg-[color-mix(in_srgb,var(--color-health-good)_14%,transparent)] text-foreground';
}

function dayLabel(date: string) {
  return new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' });
}

function matchesFilters(
  account: CapacityAccount,
  filters: Pick<PortfolioMatrixProps, 'groupFilter' | 'platformFilter' | 'scopedAccount' | 'accountIds' | 'accountId' | 'accountHandle'>,
) {
  if (filters.scopedAccount) return account.accountId === filters.scopedAccount.id;
  if (filters.accountId && account.accountId !== filters.accountId) return false;
  if (filters.accountHandle && account.handle.replace(/^@/, '') !== filters.accountHandle.replace(/^@/, '')) return false;
  if (filters.accountIds?.length && !filters.accountIds.includes(account.accountId)) return false;
  if (filters.groupFilter !== 'all' && account.groupId !== filters.groupFilter) return false;
  if (filters.platformFilter !== 'all' && account.platform !== filters.platformFilter) return false;
  return true;
}

function cellLabel(day: CapacityDay) {
  const parts = [
    day.planned > 0 ? `${day.planned} planned` : null,
    day.failed > 0 ? `${day.failed} failed` : null,
    day.deadLetter > 0 ? `${day.deadLetter} DLQ` : null,
    day.approvalPending > 0 ? `${day.approvalPending} approval` : null,
  ].filter(Boolean);
  if (parts.length === 0) return day.hasGap ? 'Gap' : 'Clear';
  return parts.join(' · ');
}

export function PortfolioMatrix(props: PortfolioMatrixProps) {
  const navigate = useNavigate();
  const { snapshot, isLoading, refetch } = useOperatorSnapshot({ capacityStart: props.capacityStart });
  const capacity = snapshot.fleetCapacity;
  const [intentBusyKey, setIntentBusyKey] = useState<string | null>(null);

  const accounts = useMemo(
    () => capacity.accounts.filter((account) => matchesFilters(account, props)),
    [capacity.accounts, props],
  );

  const days = useMemo(() => {
    const fromCapacity = capacity.days.map((day) => day.date);
    if (fromCapacity.length > 0) return fromCapacity.slice(0, 7);
    return Array.from({ length: 7 }, (_, index) => {
      const start = new Date(`${props.capacityStart}T00:00:00`);
      start.setDate(start.getDate() + index);
      return start.toISOString().slice(0, 10);
    });
  }, [capacity.days, props.capacityStart]);

  const summary = useMemo(() => {
    let gaps = 0;
    let conflicts = 0;
    let failed = 0;
    let approvals = 0;
    for (const account of accounts) {
      for (const day of account.days) {
        if (day.hasGap) gaps += 1;
        if (day.hasConflict) conflicts += 1;
        failed += day.failed + day.deadLetter;
        approvals += day.approvalPending;
      }
    }
    return { gaps, conflicts, failed, approvals };
  }, [accounts]);

  if (isLoading && capacity.accounts.length === 0) {
    return (
      <NovaCard contentClassName="p-6" className="text-sm text-muted-foreground">
        Loading portfolio capacity matrix...
      </NovaCard>
    );
  }

  async function requestCapacityApproval(account: CapacityAccount, day: CapacityDay) {
    const busyKey = `${account.accountId}:${day.date}:${day.recommendedAction}`;
    const fillGap = day.recommendedAction === 'fill_gap';
    const rebalance = day.recommendedAction === 'rebalance_conflict';
    if (!fillGap && !rebalance) return;
    setIntentBusyKey(busyKey);
    try {
      const actionName = fillGap ? 'trigger_queue_fill' : 'reschedule_post';
      const payload = fillGap
        ? {
            accountId: account.accountId,
            groupId: account.groupId,
            platform: account.platform,
            targetDate: day.date,
            source: 'calendar_portfolio_gap',
          }
        : {
            accountId: account.accountId,
            groupId: account.groupId,
            platform: account.platform,
            sourceDate: day.date,
            source: 'calendar_portfolio_rebalance',
            reason: 'Portfolio capacity conflict needs approval-reviewed rebalance.',
          };
      const dryRun = await apiFetch('/api/operator?action=dry-run', dryRunResponseSchema, {
        method: 'POST',
        json: {
          action_name: actionName,
          payload,
          account_id: account.accountId,
          group_id: account.groupId,
          risk_level: rebalance ? 'high' : 'medium',
          expires_in_hours: 24,
        },
      });
      const approval = await apiFetch('/api/operator?action=request-approval', requestApprovalResponseSchema, {
        method: 'POST',
        json: {
          intent_id: dryRun.intentId,
          urgency: rebalance ? 'high' : 'medium',
          context: fillGap
            ? `Fill calendar gap for ${account.handle} on ${day.date}.`
            : `Review rebalance for ${account.handle} conflict on ${day.date}.`,
        },
      });
      appToast.success('Approval request created.');
      navigate(`/approval-queue?status=pending&approvalId=${encodeURIComponent(approval.approvalId)}`);
    } catch (error) {
      appToast.error('Could not create approval request.', {
        description: error instanceof Error ? error.message : undefined,
      });
    } finally {
      setIntentBusyKey(null);
    }
  }

  return (
    <NovaCard contentClassName="p-0">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border bg-background/70 px-4 py-4">
        <div>
          <div className="text-[0.65625rem] font-bold uppercase tracking-[0.14em] text-muted-foreground">
            Portfolio capacity
          </div>
          <div className="mt-1 text-[0.9375rem] font-semibold text-foreground">
            Account-day matrix for the selected week
          </div>
          <div className="mt-1 max-w-2xl text-[0.75rem] leading-relaxed text-muted-foreground">
            Cells combine scheduled posts, auto-post queue coverage, failed items, pending approvals, and account gaps. Actions route to existing recovery surfaces.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={summary.failed > 0 ? 'danger' : 'secondary'}>{summary.failed} failed/DLQ</Badge>
          <Badge tone={summary.gaps > 0 ? 'outline' : 'secondary'}>{summary.gaps} gaps</Badge>
          <Badge tone="outline">{summary.approvals} approvals</Badge>
          {summary.conflicts > 0 && <Badge tone="danger">{summary.conflicts} conflicts</Badge>}
          <Button type="button" variant="outline" size="sm" onClick={() => void refetch()}>
            Refresh
          </Button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <div className="p-5 text-sm text-muted-foreground">
          No accounts match the current Calendar filters.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1040px] border-collapse text-left">
            <thead>
              <tr className="border-b border-border bg-background">
                <th className="w-[280px] px-4 py-3 text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                  Account
                </th>
                {days.map((date) => (
                  <th key={date} className="px-3 py-3 text-center text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                    {dayLabel(date)}
                  </th>
                ))}
                <th className="w-[170px] px-4 py-3 text-right text-[0.6875rem] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((account) => {
                const firstProblem = account.days.find((day) => day.recommendedAction !== 'none');
                return (
                  <tr key={account.accountId} className="border-b border-border last:border-b-0">
                    <td className="px-4 py-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span
                            className="size-2.5 rounded-full"
                            style={{ background: account.groupColor ?? 'var(--color-muted-foreground)' }}
                          />
                          <span className="truncate text-sm font-semibold text-foreground">{account.handle}</span>
                          <Badge tone="outline">{account.platform}</Badge>
                        </div>
                        <div className="mt-0.5 truncate text-[0.6875rem] text-muted-foreground">
                          {account.groupName} · {account.displayName}
                        </div>
                      </div>
                    </td>
                    {days.map((date) => {
                      const day = account.days.find((item) => item.date === date);
                      if (!day) {
                        return <td key={`${account.accountId}-${date}`} className="px-3 py-2 text-center text-xs text-muted-foreground">-</td>;
                      }
                      const icon =
                        day.failed > 0 || day.deadLetter > 0 ? AlertTriangle :
                          day.approvalPending > 0 ? ShieldCheck :
                            day.hasConflict ? GitCompare :
                              day.hasGap ? CalendarPlus : CheckCircle2;
                      const Icon = icon;
                      return (
                        <td key={`${account.accountId}-${date}`} className="px-3 py-2">
                          <Button
                            type="button"
                            variant="outline"
                            className={`mx-auto flex min-h-12 w-full max-w-[108px] flex-col items-center justify-center gap-1 rounded-md border px-2 py-2 text-xs font-semibold tabular-nums transition hover:-translate-y-0.5 ${toneClass(day.tone)}`}
                            onClick={() => {
                              if (day.failed > 0 || day.deadLetter > 0) {
                                navigate(`/calendar?status=failed&accountId=${account.accountId}&date=${date}`);
                              } else if (day.approvalPending > 0) {
                                navigate('/approval-queue?status=pending');
                              } else if (day.hasConflict) {
                                void requestCapacityApproval(account, day);
                              } else if (day.hasGap) {
                                void requestCapacityApproval(account, day);
                              } else {
                                navigate(`/calendar?accountId=${account.accountId}&date=${date}`);
                              }
                            }}
                            title={`${account.handle} ${date}: ${cellLabel(day)}`}
                          >
                            <span className="inline-flex items-center gap-1">
                              <Icon data-icon="inline-start" />
                              {day.planned}
                            </span>
                            <span className="font-normal text-[10px] opacity-80">{cellLabel(day)}</span>
                          </Button>
                        </td>
                      );
                    })}
                    <td className="px-4 py-3 text-right text-xs text-muted-foreground">
                      {firstProblem ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="ml-auto"
                          onClick={() => {
                            if (firstProblem.recommendedAction === 'fill_gap') {
                              void requestCapacityApproval(account, firstProblem);
                            } else if (firstProblem.recommendedAction === 'review_approval') {
                              navigate('/approval-queue?status=pending');
                            } else if (firstProblem.recommendedAction === 'rebalance_conflict') {
                              void requestCapacityApproval(account, firstProblem);
                            } else {
                              navigate(`/calendar?status=failed&accountId=${account.accountId}&date=${firstProblem.date}`);
                            }
                          }}
                        >
                          {intentBusyKey === `${account.accountId}:${firstProblem.date}:${firstProblem.recommendedAction}` ? 'Requesting' : 'Resolve'}
                          <ExternalLink data-icon="inline-end" />
                        </Button>
                      ) : (
                        <span className="text-muted-foreground">Covered</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </NovaCard>
  );
}
