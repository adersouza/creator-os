import { useCallback, useEffect, useRef, useState } from 'react';
import { Download } from 'lucide-react';
import { appToast } from '@/lib/toast';
import { randomUUID } from '@/lib/uuid';
import { supabase } from '@/services/supabase';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

type ExportStatus = 'idle' | 'pending' | 'processing' | 'complete' | 'failed';

interface ExportJob {
  jobId: string;
  status: ExportStatus;
  downloadUrl?: string | undefined;
  expiresAt?: string | undefined;
}

type PostExportRow = {
  status?: string | null | undefined;
  platform?: string | null | undefined;
  views_count?: number | null | undefined;
  likes_count?: number | null | undefined;
  replies_count?: number | null | undefined;
  reposts_count?: number | null | undefined;
  quotes_count?: number | null | undefined;
  shares_count?: number | null | undefined;
  ig_reach?: number | null | undefined;
  ig_impressions?: number | null | undefined;
  ig_saved?: number | null | undefined;
  ig_shares?: number | null | undefined;
  ig_comment_count?: number | null | undefined;
};

type ThreadsAccountExportRow = {
  followers_count?: number | null | undefined;
};

type InstagramAccountExportRow = {
  follower_count?: number | null | undefined;
};

type SmartLinkExportRow = {
  click_count?: number | null | undefined;
};

function countUniqueWorkspaceIds(rows: Array<{ workspace_id: string }> | null | undefined): number {
  return new Set((rows ?? []).map((row) => row.workspace_id)).size;
}

export function DataExportCard() {
  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);
  const [job, setJob] = useState<ExportJob | null>(null);
  const [starting, setStarting] = useState(false);
  const downloadUrlRef = useRef<string | null>(null);

  const clearDownloadUrl = useCallback(() => {
    if (downloadUrlRef.current) {
      URL.revokeObjectURL(downloadUrlRef.current);
      downloadUrlRef.current = null;
    }
  }, []);

  useEffect(() => () => clearDownloadUrl(), [clearDownloadUrl]);

  const requestExport = async () => {
    if (starting) return;
    if (!currentWorkspace?.id) {
      appToast.error('No workspace selected.');
      return;
    }

    setStarting(true);
    clearDownloadUrl();
    setJob({ jobId: randomUUID(), status: 'processing' });

    try {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) throw new Error('Not authenticated');

      const [workspaceResp, membersResp, membershipsResp, invitesResp, activityResp] = await Promise.all([
        supabase.from('workspaces').select('*').eq('id', currentWorkspace.id).maybeSingle(),
        supabase.from('workspace_members').select('*').eq('workspace_id', currentWorkspace.id),
        supabase.from('workspace_members').select('workspace_id').eq('user_id', user.id),
        supabase.from('workspace_invites').select('*').eq('workspace_id', currentWorkspace.id),
        supabase.from('workspace_activity').select('*').eq('workspace_id', currentWorkspace.id).order('created_at', { ascending: false }),
      ]);

      if (workspaceResp.error) throw workspaceResp.error;
      if (membersResp.error) throw membersResp.error;
      if (membershipsResp.error) throw membershipsResp.error;
      if (invitesResp.error) throw invitesResp.error;
      if (activityResp.error) throw activityResp.error;

      const hasMultipleWorkspaces = countUniqueWorkspaceIds(membershipsResp.data) > 1;
      const [
        groupsResp,
        accountsResp,
        instagramResp,
        postsResp,
        userSettingsResp,
        agencyBrandingResp,
        autoPostConfigResp,
        autoPostGroupConfigResp,
        autoPostGroupStateResp,
        autoPostQueueResp,
        watchdogAlertsResp,
        unifiedLinksResp,
        smartLinksResp,
      ] = hasMultipleWorkspaces
        ? await Promise.all([
            Promise.resolve({ data: [], error: null }),
            Promise.resolve({ data: [], error: null }),
            Promise.resolve({ data: [], error: null }),
            Promise.resolve({ data: [], error: null }),
            Promise.resolve({ data: null, error: null }),
            Promise.resolve({ data: null, error: null }),
            supabase.from('auto_post_config').select('*').eq('workspace_id', currentWorkspace.id).maybeSingle(),
            supabase.from('auto_post_group_config').select('*').eq('workspace_id', currentWorkspace.id),
            supabase.from('auto_post_group_state').select('*').eq('workspace_id', currentWorkspace.id),
            supabase.from('auto_post_queue').select('*').eq('workspace_id', currentWorkspace.id).order('scheduled_for', { ascending: true }),
            supabase.from('watchdog_alerts').select('*').eq('workspace_id', currentWorkspace.id).order('created_at', { ascending: false }),
            supabase.from('unified_links').select('*').eq('workspace_id', currentWorkspace.id),
            Promise.resolve({ data: [], error: null }),
          ])
        : await Promise.all([
            supabase.from('account_groups').select('*').eq('user_id', user.id),
            supabase.from('accounts').select('*').eq('user_id', user.id),
            supabase.from('instagram_accounts').select('*').eq('user_id', user.id),
            supabase.from('posts').select('*').eq('user_id', user.id).order('updated_at', { ascending: false, nullsFirst: false }),
            supabase.from('user_settings').select('*').eq('user_id', user.id),
            supabase.from('agency_branding').select('*').eq('user_id', user.id).maybeSingle(),
            supabase.from('auto_post_config').select('*').eq('workspace_id', currentWorkspace.id).maybeSingle(),
            supabase.from('auto_post_group_config').select('*').eq('workspace_id', currentWorkspace.id),
            supabase.from('auto_post_group_state').select('*').eq('workspace_id', currentWorkspace.id),
            supabase.from('auto_post_queue').select('*').eq('workspace_id', currentWorkspace.id).order('scheduled_for', { ascending: true }),
            supabase.from('watchdog_alerts').select('*').eq('workspace_id', currentWorkspace.id).order('created_at', { ascending: false }),
            supabase.from('unified_links').select('*').eq('workspace_id', currentWorkspace.id),
            supabase.from('smart_links').select('*').eq('user_id', user.id).order('updated_at', { ascending: false, nullsFirst: false }),
          ]);

      if (groupsResp.error) throw groupsResp.error;
      if (accountsResp.error) throw accountsResp.error;
      if (instagramResp.error) throw instagramResp.error;
      if (postsResp.error) throw postsResp.error;
      if (userSettingsResp.error) throw userSettingsResp.error;
      if (agencyBrandingResp.error) throw agencyBrandingResp.error;
      if (autoPostConfigResp.error) throw autoPostConfigResp.error;
      if (autoPostGroupConfigResp.error) throw autoPostGroupConfigResp.error;
      if (autoPostGroupStateResp.error) throw autoPostGroupStateResp.error;
      if (autoPostQueueResp.error) throw autoPostQueueResp.error;
      if (watchdogAlertsResp.error) throw watchdogAlertsResp.error;
      if (unifiedLinksResp.error) throw unifiedLinksResp.error;
      if (smartLinksResp.error) throw smartLinksResp.error;

      const threadAccounts = (accountsResp.data ?? []) as ThreadsAccountExportRow[];
      const instagramAccounts = (instagramResp.data ?? []) as InstagramAccountExportRow[];
      const posts = (postsResp.data ?? []) as PostExportRow[];
      const smartLinks = (smartLinksResp.data ?? []) as SmartLinkExportRow[];

      const analytics = hasMultipleWorkspaces
        ? null
        : {
            generatedAt: new Date().toISOString(),
            accountCounts: {
              threads: threadAccounts.length,
              instagram: instagramAccounts.length,
              total: threadAccounts.length + instagramAccounts.length,
            },
            followerFootprint: {
              threads: threadAccounts.reduce((sum, account) => sum + (account.followers_count ?? 0), 0),
              instagram: instagramAccounts.reduce((sum, account) => sum + (account.follower_count ?? 0), 0),
            },
            posts: {
              total: posts.length,
              draft: posts.filter((post) => post.status === 'draft').length,
              scheduled: posts.filter((post) => post.status === 'scheduled').length,
              published: posts.filter((post) => post.status === 'published').length,
              failed: posts.filter((post) => post.status === 'failed' || post.status === 'publish_failed').length,
            },
            platformBreakdown: {
              threads: posts.filter((post) => post.platform === 'threads').length,
              instagram: posts.filter((post) => post.platform === 'instagram').length,
            },
            engagement: {
              totalReach: posts.reduce((sum, post) => sum + (post.ig_reach ?? post.ig_impressions ?? post.views_count ?? 0), 0),
              totalInteractions: posts.reduce(
                (sum, post) =>
                  sum +
                  (post.likes_count ?? 0) +
                  (post.replies_count ?? 0) +
                  (post.reposts_count ?? 0) +
                  (post.quotes_count ?? 0) +
                  (post.shares_count ?? 0) +
                  (post.ig_saved ?? 0) +
                  (post.ig_shares ?? 0) +
                  (post.ig_comment_count ?? 0),
                0,
              ),
            },
            smartLinks: {
              totalLinks: smartLinks.length,
              totalClicks: smartLinks.reduce((sum, link) => sum + (link.click_count ?? 0), 0),
            },
          };

      const payload = {
        exportedAt: new Date().toISOString(),
        scope: {
          workspaceId: currentWorkspace.id,
          mode: hasMultipleWorkspaces ? 'workspace_only' : 'workspace_plus_user_scoped',
          omittedTables: hasMultipleWorkspaces
            ? ['account_groups', 'accounts', 'instagram_accounts', 'posts', 'user_settings', 'agency_branding', 'smart_links', 'analytics']
            : [],
          note: hasMultipleWorkspaces
            ? 'User-scoped tables were omitted because they are not workspace-scoped in the current data model.'
            : null,
        },
        workspace: workspaceResp.data ?? currentWorkspace,
        user: {
          id: user.id,
          email: user.email ?? null,
          metadata: user.user_metadata ?? {},
          appMetadata: user.app_metadata ?? {},
        },
        preferences: {
          theme: (() => {
            try {
              return localStorage.getItem('juno33-theme');
            } catch {
              return null;
            }
          })(),
          locale: (() => {
            try {
              return localStorage.getItem('juno33-locale');
            } catch {
              return null;
            }
          })(),
        },
        settings: hasMultipleWorkspaces
          ? null
          : {
              userSettings: userSettingsResp.data ?? null,
              agencyBranding: agencyBrandingResp.data ?? null,
            },
        analytics,
        members: membersResp.data ?? [],
        invites: invitesResp.data ?? [],
        activity: activityResp.data ?? [],
        watchdogAlerts: watchdogAlertsResp.data ?? [],
        accountGroups: groupsResp.data ?? [],
        threadsAccounts: accountsResp.data ?? [],
        instagramAccounts: instagramResp.data ?? [],
        posts: postsResp.data ?? [],
        autopilot: {
          config: autoPostConfigResp.data ?? null,
          groupConfig: autoPostGroupConfigResp.data ?? [],
          groupState: autoPostGroupStateResp.data ?? [],
          queue: autoPostQueueResp.data ?? [],
        },
        links: {
          unifiedLinks: unifiedLinksResp.data ?? [],
          smartLinks: smartLinksResp.data ?? [],
        },
      };

      const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: 'application/json',
      });
      const downloadUrl = URL.createObjectURL(blob);
      downloadUrlRef.current = downloadUrl;

      setJob({
        jobId: randomUUID(),
        status: 'complete',
        downloadUrl,
        expiresAt: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
      });
      appToast.success('Your data export is ready', {
        description: hasMultipleWorkspaces
          ? 'User-scoped tables were omitted to keep the archive limited to this workspace.'
          : 'Click Download to save the archive.',
      });
    } catch (err) {
      const description = err instanceof Error ? err.message : 'Could not start export.';
      setJob({
        jobId: randomUUID(),
        status: 'failed',
      });
      appToast.error('Could not start export', { description });
    } finally {
      setStarting(false);
    }
  };

  const triggerDownload = () => {
    if (!job?.downloadUrl) return;
    const stamp = new Date().toISOString().slice(0, 10);
    const slug = (currentWorkspace?.name || 'workspace')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
    const anchor = document.createElement('a');
    anchor.href = job.downloadUrl;
    anchor.download = `juno33-${slug || 'workspace'}-export-${stamp}.json`;
    anchor.click();
  };

  const inFlight = starting || job?.status === 'pending' || job?.status === 'processing';
  const buttonLabel = (() => {
    if (starting) return 'Preparing archive…';
    if (job?.status === 'pending' || job?.status === 'processing') return 'Preparing archive…';
    if (job?.status === 'complete' && job.downloadUrl) return 'Download archive';
    if (job?.status === 'failed') return 'Retry export';
    return 'Request export';
  })();

  return (
    <Card>
      <CardContent className="flex items-start gap-4 p-5">
        <span
          className="flex size-9 shrink-0 items-center justify-center rounded-md bg-[color-mix(in_srgb,var(--color-oxblood)_10%,transparent)] text-[color:var(--color-oxblood)]"
          aria-hidden="true"
        >
          <Download data-icon="inline-start" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[0.84375rem] font-medium text-foreground">Download your data</div>
          <p className="mt-0.5 max-w-[52ch] text-[0.75rem] leading-relaxed text-muted-foreground">
            Generate a portable archive of this workspace. Workspace activity, links, alerts, and autopilot config are always included; user-scoped posts, connected accounts, settings, and analytics summaries are included when they belong only to this workspace.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button
              type="button"
              onClick={() => (job?.status === 'complete' && job.downloadUrl ? triggerDownload() : void requestExport())}
              disabled={inFlight}
              variant="outline"
              size="sm"
              className={cn(
                "text-[color:var(--color-oxblood)] hover:border-[color:var(--color-oxblood)]",
                inFlight && "cursor-progress opacity-60",
              )}
            >
              {buttonLabel}
            </Button>
          {job?.status === 'complete' && job.expiresAt && (
            <span className="text-[0.71875rem] text-muted-foreground">
              Expires {new Date(job.expiresAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
            </span>
          )}
        </div>
      </div>
      </CardContent>
    </Card>
  );
}
