import { memo, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { DAY_NAMES, STATUS_STYLE, formatHour, type Post } from './shared';
import { badgeLabelFor } from '@/lib/socialPlatform';
import {
  formatCampaignFactoryAuditStatus,
  formatCampaignFactoryReadiness,
  formatCampaignFactoryScheduleMode,
  formatCampaignFactorySurface,
  sortCampaignFactoryDraftQueue,
} from '@/lib/campaignFactory';
import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuRoot,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/ContextMenu';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { NovaCard } from "@/components/ui/NovaPrimitives";

/* =========================================================================
   LIST VIEW — chronological feed.
   Extracted from src/pages/Calendar.tsx verbatim.
   ========================================================================= */
function CalendarListViewInner({
  posts,
  weekStart,
  onOpenPost,
  onDuplicate,
  onDelete,
  onRepost,
  getDeleteDisabledReason,
}: {
  posts: Post[];
  weekStart: Date;
  onOpenPost: (p: Post) => void;
  onDuplicate?: (id: string) => void | Promise<void> | undefined;
  onDelete?: (id: string) => void | Promise<void> | undefined;
  onRepost?: (post: Post) => void | Promise<void> | undefined;
  getDeleteDisabledReason?: (post: Post) => string | null;
}) {
  const navigate = useNavigate();
  const sorted = useMemo(
    () => {
      if (posts.length > 0 && posts.every((post) => post.campaignFactory)) {
        return sortCampaignFactoryDraftQueue(posts);
      }
      return [...posts].sort((a, b) => {
        const dayDiff = a.day - b.day;
        if (dayDiff !== 0) return dayDiff;
        return a.hour * 60 + a.minute - (b.hour * 60 + b.minute);
      });
    },
    [posts],
  );

  const dateFor = (dayIdx: number) => {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + dayIdx);
    return d.getDate();
  };

  const timeLabelFor = (post: Post) =>
    post.isUnscheduledDraft ? 'Draft' : formatHour(post.hour, post.minute);

  return (
    <NovaCard contentClassName="p-0">
      <div className="hidden gap-3 border-b border-border px-5 py-3 text-[0.65625rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground md:grid md:grid-cols-[80px_90px_1fr_140px_100px_auto]">
        <div>Day</div>
        <div>Time</div>
        <div>Post</div>
        <div>Account</div>
        <div>Status</div>
        <div className="text-right">Platform</div>
      </div>

      {sorted.length === 0 ? (
        <div className="px-5 py-16 text-center">
          <div className="mb-1 text-[0.9375rem] font-medium text-foreground">
            Nothing scheduled this week
          </div>
          <div className="mb-3 text-[0.78125rem] text-muted-foreground">
            Adjust filters or compose a new post.
          </div>
          <Button
            type="button"
            onClick={() => navigate('/composer')}
            size="sm"
          >
            Compose your first post
            <span aria-hidden="true">→</span>
          </Button>
        </div>
      ) : (
      <div>
        {sorted.map((p) => {
          const status = STATUS_STYLE[p.status];
          const campaignFactorySurface = p.campaignFactory
            ? formatCampaignFactorySurface(p.campaignFactory)
            : null;
          const campaignFactoryScheduleMode = p.campaignFactory
            ? formatCampaignFactoryScheduleMode(p.campaignFactory)
            : null;
          const row = (
            <Button
              type="button"
              onClick={() => onOpenPost(p)}
              variant="ghost"
              className="group relative h-auto w-full rounded-none border-b border-border px-5 py-3 text-left last:border-b-0 md:grid md:grid-cols-[80px_90px_1fr_140px_100px_auto] md:items-center md:gap-3"
            >
              {/* Oxblood edge bar on hover — signature interaction move */}
              <span
                className="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ backgroundColor: 'var(--color-oxblood)' }}
                aria-hidden="true"
              />
              {/* Mobile (<md): Day+Time+Platform row, then Post title, then Account+Status chips.
                  Desktop (md+): flows into the 6-column grid via the md:grid on parent. */}
              <div className="flex items-center justify-between gap-3 md:contents">
                <div className="text-[0.71875rem] tabular-nums text-foreground md:flex-none">
                  {DAY_NAMES[p.day]} {dateFor(p.day)}
                </div>
                <div
                  className="text-[0.71875rem] font-semibold tabular-nums md:flex-none"
                  style={{ color: 'var(--color-oxblood)' }}
                >
                  {timeLabelFor(p)}
                </div>
                <div className="hidden min-w-0 text-[0.78125rem] text-foreground md:flex md:items-center md:gap-2">
                  <span
                    className="inline-block w-[2px] h-3.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: p.groupColor }}
                    aria-hidden="true"
                  />
                  <span className="truncate">{p.title}</span>
                  {p.campaignFactory && (
                    <span className="inline-flex min-w-0 items-center gap-1">
                      <Badge tone="oxblood" className="max-w-28 truncate">
                        {campaignFactorySurface}
                      </Badge>
                      {campaignFactoryScheduleMode && (
                        <Badge tone="secondary" className="max-w-28 truncate">
                          {campaignFactoryScheduleMode}
                        </Badge>
                      )}
                      {[
                        p.campaignFactory.campaign_id,
                        campaignFactorySurface,
                        campaignFactoryScheduleMode,
                        p.campaignFactory.recipe,
                        formatCampaignFactoryAuditStatus(p.campaignFactory.audit_status),
                        p.campaignFactory.readiness_status
                          ? formatCampaignFactoryReadiness(p.campaignFactory.readiness_status)
                          : null,
                        p.campaignFactory.content_pillar,
                        p.campaignFactory.cta_type,
                        p.campaignFactory.language,
                      ].filter(Boolean).slice(0, 6).map((value) => (
                        <Badge
                          key={value}
                          tone="outline"
                          className="max-w-28 truncate"
                        >
                          {value}
                        </Badge>
                      ))}
                    </span>
                  )}
                </div>
                <div className="hidden truncate text-[0.71875rem] tabular-nums text-muted-foreground md:block">
                  {p.account}
                </div>
                <div className="hidden md:block">
                  <Badge tone="secondary">{status.label}</Badge>
                </div>
                <div className="text-right text-[0.65625rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground tabular-nums md:flex-none">
                  {badgeLabelFor(p.platform)}
                </div>
              </div>
              <div className="mt-1.5 flex items-center gap-2 truncate text-[0.78125rem] text-foreground md:hidden">
                <span
                  className="inline-block w-[2px] h-3.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: p.groupColor }}
                  aria-hidden="true"
                />
                <span className="truncate">{p.title}</span>
                {p.campaignFactory && (
                  <>
                    <Badge tone="oxblood" className="max-w-24 truncate">
                      {campaignFactorySurface}
                    </Badge>
                    {campaignFactoryScheduleMode && (
                      <Badge tone="secondary" className="max-w-24 truncate">
                        {campaignFactoryScheduleMode}
                      </Badge>
                    )}
                  </>
                )}
              </div>
              <div className="mt-1.5 flex items-center gap-2 text-[0.65625rem] text-muted-foreground tabular-nums md:hidden">
                <span className="truncate">{p.account}</span>
                <span aria-hidden="true">·</span>
                <Badge tone="secondary" className="shrink-0">{status.label}</Badge>
              </div>
            </Button>
          );
          if (!onDuplicate && !onDelete) return <div key={p.id}>{row}</div>;
          return (
            <ContextMenuRoot key={p.id}>
              <ContextMenuTrigger asChild>{row}</ContextMenuTrigger>
              <ContextMenuContent>
                <ContextMenuItem onSelect={() => onOpenPost(p)}>Edit</ContextMenuItem>
                {onDuplicate && (
                  <ContextMenuItem onSelect={() => void onDuplicate(p.id)}>Duplicate</ContextMenuItem>
                )}
                {onRepost && p.platform === 'threads' && p.threadsPostId && (
                  <ContextMenuItem onSelect={() => void onRepost(p)}>Repost on Threads</ContextMenuItem>
                )}
                {onDelete && <ContextMenuSeparator />}
                {onDelete && (
                  <ContextMenuItem
                    destructive
                    disabled={!!getDeleteDisabledReason?.(p)}
                    title={getDeleteDisabledReason?.(p) ?? undefined}
                    onSelect={() => void onDelete(p.id)}
                  >
                    Delete
                  </ContextMenuItem>
                )}
              </ContextMenuContent>
            </ContextMenuRoot>
          );
        })}
      </div>
      )}
    </NovaCard>
  );
}

export const CalendarListView = memo(CalendarListViewInner);
