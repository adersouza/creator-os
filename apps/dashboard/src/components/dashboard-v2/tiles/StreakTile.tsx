import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { usePostingStreak, type StreakPlatform } from '@/hooks/usePostingStreak';
import { cn } from '@/lib/utils';
import { scopedRoute } from '@/lib/scopedRoutes';
import type { DashboardScopeProps } from '../scope';

interface Props extends DashboardScopeProps {
  platform?: StreakPlatform | undefined;
  variant?: 'compact' | 'wide' | undefined;
}

/**
 * Streak (mockup new-widgets-2026 #2). Per-platform consecutive-day
 * streak, weekly goal tracker (4 posts/week per platform), 14-day dot
 * grid showing which recent calendar days had a published post.
 *
 * - `variant="compact"` (default) — span-4 ALL/IG view layout
 * - `variant="wide"` — span-12 Threads view band 4
 */
export function StreakTile({ platform = 'all', variant = 'compact', scopedAccount, accountIds, groupId }: Props) {
  const { streak, recentDaysPosted, postsThisWeek, weeklyGoal, goalHit, isLoading, hasError } = usePostingStreak(platform, scopedAccount, accountIds, groupId);

  const platformLabel = platform === 'threads' ? 'Threads' : platform === 'ig' ? 'Instagram' : 'Posted on at least one network';
  const goalText = `${postsThisWeek} of ${weeklyGoal} · ${goalHit ? 'goal hit' : 'below goal'}`;

  const showWide = variant === 'wide';
  const isCompact = variant === 'compact';

  return (
    <NovaCard
      className="h-full"
      contentClassName={isCompact ? 'flex h-full flex-col p-4' : 'flex h-full flex-row items-center gap-8'}
    >
      <div
        className={cn(
          'flex',
          showWide ? 'flex-row items-center gap-8' : 'flex-col items-stretch',
        )}
      >
        <div className={cn(showWide && 'shrink-0')}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Streak</span>
            {!goalHit && !isLoading && !hasError ? (
              <Button asChild size="sm">
                <Link to={scopedRoute('/calendar', { scopedAccount, accountIds, groupId, platform })}>
                  Fill gaps
                </Link>
              </Button>
            ) : (
              <Badge tone="outline">{platformLabel.toUpperCase()}</Badge>
            )}
          </div>
          <div className="mt-2 flex items-baseline gap-1.5">
            <span
              className={cn(
                'font-semibold leading-none tracking-normal tabular-nums',
                showWide ? 'text-[38px]' : 'text-[28px]',
                streak >= 3 ? 'text-primary' : 'text-foreground',
              )}
            >
              {streak}
            </span>
            <span className="text-xs text-muted-foreground">
              day {streak === 1 ? 'streak' : 'streak'}
            </span>
          </div>
        </div>

        <div className={cn('flex-1', showWide ? 'mt-0' : 'mt-3')}>
          <div
            className="mb-2 text-xs leading-relaxed text-muted-foreground"
          >
            Goal: {weeklyGoal} posts / week.{' '}
            <strong className={cn('font-semibold', goalHit ? 'text-success' : 'text-foreground')}>
              {goalText}
            </strong>
          </div>
          <div
            className="grid grid-cols-7 gap-1"
            role="group"
            aria-label="Last 14 days posting streak"
          >
            <div className="col-span-full text-[9px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">Last week</div>
            {recentDaysPosted.map((posted, i) => {
              const isToday = i === recentDaysPosted.length - 1;
              const rowLabel = i === 7 ? (
                <div key="this-week-label" className="col-span-full text-[9px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">This week</div>
              ) : null;
              return (
                <div key={`day-${i}`} className="contents">
                  {rowLabel}
                  <div
                    role="img"
                    aria-label={`${isToday ? 'Today' : `Day ${i + 1}`} · ${posted ? 'posted' : 'no post'}`}
                    className={cn(
                      'mx-auto aspect-square w-full rounded transition-colors',
                      showWide ? 'max-w-7' : 'max-w-[30px]',
                      posted
                        ? 'border border-primary/45 bg-primary'
                        : 'border border-border bg-foreground/5 opacity-70',
                      isToday && 'border-primary ring-2 ring-primary/20',
                    )}
                    title={isToday ? (posted ? 'Posted today' : 'No post today') : posted ? 'Published' : 'No post'}
                  />
                </div>
              );
            })}
          </div>
          {hasError ? (
            <NovaEmpty
              className="mt-3 min-h-20 p-3"
              title="Streak unavailable"
              description="Refresh the dashboard to retry the streak read."
            />
          ) : !isLoading && streak === 0 ? (
            <div className="mt-3 rounded-lg border border-dashed border-border bg-muted/35 p-3 text-xs leading-relaxed text-muted-foreground">
              {isCompact
                ? 'Publish today to start the streak.'
                : 'Publish at least once today to start your streak. Research shows 4×/week is the lower bound for compounding reach.'}
            </div>
          ) : null}
        </div>
      </div>
    </NovaCard>
  );
}
