import { useEffect, useState } from 'react';
import { Activity, CheckCircle2, ScrollText } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { getActivityLog } from '@/services/teamService';
import type { ActivityLogEntry } from '@/types/team';
import { SectionHeader, Panel } from './shared';
import { BetaProgramTab } from './BetaProgramTab';
import { DeletionStatusTab } from './DeletionStatusTab';
import { DataExportCard } from './DataExportCard';
import { CohortSharingCard } from './CohortSharingCard';

/* =========================================================================
   Labs tab — entry point for the beta program flagged features.
   ========================================================================= */
export function LabsTab() {
  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="Beta labs"
        description="Features in active testing. Stable-enough to ship, rough-enough to flag."
      />
      <BetaProgramTab />
    </div>
  );
}

/* =========================================================================
   Data & privacy tab — export + deletion requests.
   ========================================================================= */
export function DataTab() {
  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="Data & privacy"
        description="Export, deletion requests, and retention controls. GDPR / Meta Platform Policy compliant."
      />
      <DataExportCard />
      <CohortSharingCard />
      <DeletionStatusTab />
    </div>
  );
}

const UX_EVENTS = [
  'composer_opened',
  'composer_media_upload_success',
  'composer_media_upload_failure',
  'composer_readiness_fix_clicked',
  'composer_schedule_success',
  'composer_schedule_failure',
  'composer_notify_push_state',
  'handoff_opened',
  'handoff_completed',
  'first_post_wizard_opened',
  'first_post_wizard_step_completed',
  'account_readiness_action_clicked',
  'pwa_setup_step_completed',
  'calendar_command_used',
  'post_publish_followup_saved',
  'empty_state_cta_clicked',
  'web_vitals',
];

export function UxHealthTab() {
  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="UX health"
        description="Privacy-safe publishing workflow telemetry. This panel documents what Juno33 measures without exposing captions, media URLs, tokens, emails, or post content."
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Event coverage
              </div>
              <div className="mt-1 text-[0.875rem] font-semibold text-foreground">
                Publishing workstation telemetry contract
              </div>
            </div>
            <div className="rounded-md border border-border bg-card px-2 py-1 text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {UX_EVENTS.length} events
            </div>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {UX_EVENTS.map((event) => (
              <div
                key={event}
                className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-[0.75rem] text-muted-foreground"
              >
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-[var(--color-health-good)]" aria-hidden="true" />
                <code className="min-w-0 flex-1 truncate font-mono">{event}</code>
              </div>
            ))}
          </div>
        </Panel>

        <Panel>
          <div className="inline-flex items-center gap-2 text-[0.6875rem] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            <Activity className="h-4 w-4" aria-hidden="true" />
            Privacy boundary
          </div>
          <div className="mt-3 flex flex-col gap-3 text-[0.8125rem] leading-snug text-muted-foreground">
            <p>
              Client telemetry strips content-bearing keys before PostHog capture and before the server endpoint receives the event.
            </p>
            <p>
              The API rejects unsafe property keys and rate-limits per authenticated user. Current data is written to logs; aggregated charts can be added once persistence is introduced.
            </p>
          </div>
        </Panel>
      </div>
    </div>
  );
}

/* =========================================================================
   Audit log — workspace_activity read-only surface. Gives owners an at-a-glance
   ledger of role changes, invite events, subscription changes, etc. Required
   for SOC 2 / compliance storytelling, and just generally useful for agency
   operators who manage multiple client workspaces.
   ========================================================================= */

const ACTIVITY_LABEL: Record<string, string> = {
  member_invited: 'Member invited',
  member_joined: 'Member joined',
  member_removed: 'Member removed',
  member_role_changed: 'Role changed',
  post_created: 'Post created',
  post_published: 'Post published',
  post_scheduled: 'Post scheduled',
  post_deleted: 'Post deleted',
  account_connected: 'Account connected',
  account_removed: 'Account removed',
  workspace_created: 'Workspace created',
  workspace_settings_updated: 'Settings updated',
  invite_created: 'Invite sent',
  invite_revoked: 'Invite revoked',
  ownership_transferred: 'Ownership transferred',
  subscription_created: 'Subscription started',
  subscription_updated: 'Subscription updated',
  subscription_canceled: 'Subscription canceled',
  addon_added: 'Add-on purchased',
  addon_removed: 'Add-on removed',
  trial_started: 'Trial started',
  trial_ended: 'Trial ended',
};

function formatAuditTime(d: Date): string {
  const ms = Date.now() - d.getTime();
  const min = Math.floor(ms / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  const dy = Math.floor(hr / 24);
  if (dy < 7) return `${dy}d`;
  return d.toLocaleDateString();
}

export function AuditTab() {
  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);
  const [entries, setEntries] = useState<ActivityLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    if (!currentWorkspace?.id) {
      setEntries([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    (async () => {
      try {
        const rows = await getActivityLog(currentWorkspace.id, 100);
        if (!cancelled) setEntries(rows);
      } catch {
        if (!cancelled) setEntries([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [currentWorkspace?.id]);

  return (
    <div className="flex flex-col gap-6">
      <SectionHeader
        title="Audit log"
        description="Last 100 workspace events: membership, billing, settings changes. Kept for 90 days."
      />

      <Panel className="!p-0">
        {loading ? (
          <div className="p-10 text-center text-[0.75rem] text-muted-foreground">Loading…</div>
        ) : entries.length === 0 ? (
          <div className="p-10 text-center">
            <div className="w-10 h-10 rounded-full bg-muted border border-border mx-auto mb-3 flex items-center justify-center">
              <ScrollText className="w-4 h-4 text-muted-foreground" />
            </div>
            <div className="text-[0.84375rem] font-medium text-foreground">Nothing logged yet</div>
            <div className="text-[0.75rem] text-muted-foreground mt-1">
              Workspace events (invites, role changes, publishes) will appear here.
            </div>
          </div>
        ) : (
          <ul>
            {entries.map((entry, i) => (
              <li
                key={entry.id}
                className={cn(
                  'flex items-start gap-3 px-5 py-3 text-[0.78125rem]',
                  i > 0 && 'border-t border-border',
                )}
              >
                <div
                  className="size-1.5 rounded-full mt-[7px] shrink-0 bg-muted-foreground/60"
                  aria-hidden="true"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="font-medium text-foreground">
                      {ACTIVITY_LABEL[entry.action] || entry.action}
                    </span>
                    {entry.userName && (
                      <span className="text-muted-foreground">· {entry.userName}</span>
                    )}
                  </div>
                  {entry.details && Object.keys(entry.details).length > 0 && (
                    <div className="text-[0.71875rem] text-muted-foreground mt-0.5 font-mono truncate">
                      {Object.entries(entry.details)
                        .filter(([k]) => !k.startsWith('_'))
                        .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
                        .join(' · ')}
                    </div>
                  )}
                </div>
                <time
                  dateTime={entry.timestamp.toISOString()}
                  className="text-[0.6875rem] text-muted-foreground tabular-nums shrink-0"
                >
                  {formatAuditTime(entry.timestamp)}
                </time>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
