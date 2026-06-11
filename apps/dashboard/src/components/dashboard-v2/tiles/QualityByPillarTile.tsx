import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { NovaCard, NovaEmpty, NovaInset } from "@/components/ui/NovaPrimitives";
import { Skeleton } from '@/components/ui/Skeleton';
import { useQualityByPillar, type PillarPlatform } from '@/hooks/useQualityByPillar';
import { cn } from '@/lib/utils';
import { scopedRoute } from '@/lib/scopedRoutes';
import { formatCompact } from '../shared';
import type { DashboardScopeProps } from '../scope';

const PILLAR_COLORS = [
  'bg-primary',
  'bg-warning',
  'bg-success',
  'bg-muted-foreground',
];

function labelize(value: string): string {
  return value
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

export function QualityByPillarTile({
  scopedAccount,
  accountIds,
  groupId,
  periodDays = 30,
  platform = 'all',
}: DashboardScopeProps & { periodDays?: number; platform?: PillarPlatform }) {
  const { pillars, thresholdMinPosts, hasError } = useQualityByPillar(periodDays, platform, scopedAccount, accountIds, groupId);
  const top = pillars.slice(0, 4);
  const classifiedPosts = pillars.reduce((sum, p) => sum + p.postCount, 0);
  const visiblePosts = top.reduce((sum, p) => sum + p.postCount, 0);
  const hasData = top.length > 0;

  return (
    <NovaCard variant="compact" className="h-full" contentClassName="flex h-full flex-col">
        <div className="flex items-baseline justify-between gap-2.5">
          <span className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Content quality · {periodDays}d</span>
          {hasData ? (
            <Button asChild size="sm">
              <Link to={scopedRoute('/ideas', { scopedAccount, accountIds, groupId }, { source: 'rough' })}>
                Make variants
              </Link>
            </Button>
          ) : (
            <Badge tone="outline">MIN {thresholdMinPosts} POSTS</Badge>
          )}
        </div>
        <div className="mt-2 text-xs leading-relaxed text-muted-foreground">
          {platform === 'instagram'
            ? 'Quality score = saves + sends per reach for Instagram posts in this scope.'
            : platform === 'threads'
              ? 'Quality score = sends plus replies per view for Threads posts in this scope.'
              : 'Quality score = saves + sends per reach. Threads reach uses views as the closest API-backed proxy.'}
        </div>

        {hasData ? (
          <>
            <div className="mt-3.5 flex flex-col gap-2.5">
              {top.map((pillar, i) => {
                const width = Math.max(5, Math.min(100, (pillar.qwe / 5) * 100));
                const overflows = pillar.qwe > 5;
                return (
                  <div key={pillar.pillar}>
                    <div className="flex items-center justify-between gap-2.5">
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          aria-hidden="true"
                          className={cn(
                            "size-2 shrink-0 rounded-sm",
                            PILLAR_COLORS[i % PILLAR_COLORS.length],
                          )}
                        />
                        <span className="truncate text-xs font-semibold text-foreground">
                          {labelize(pillar.pillar)}
                        </span>
                      </div>
                      <span className="text-xs font-bold text-primary tabular-nums">
                        {pillar.qwe.toFixed(pillar.qwe >= 10 ? 1 : 2)}%
                        {overflows ? ' →' : ''}
                      </span>
                    </div>
                    <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn(
                          "h-full rounded-full",
                          PILLAR_COLORS[i % PILLAR_COLORS.length],
                        )}
                        style={{
                          width: `${width}%`,
                        }}
                      />
                    </div>
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      {pillar.postCount} posts · {formatCompact(pillar.totalSaves)} saves · {formatCompact(pillar.totalSends)} sends · {formatCompact(pillar.totalReach)} reach
                    </div>
                  </div>
                );
              })}
            </div>

            <div
              className="mt-auto flex justify-between gap-3 rounded-lg border border-dashed border-border bg-muted/35 px-3 py-2"
            >
              <span className="text-xs text-muted-foreground">Classified sample</span>
              <span className="text-xs font-bold text-foreground tabular-nums">
                {formatCompact(classifiedPosts)} posts · {formatCompact(visiblePosts)} of {formatCompact(classifiedPosts)} classified
              </span>
            </div>
          </>
        ) : (
          <NovaInset className="mt-4 grid gap-4 border-dashed">
            <NovaEmpty
              className="min-h-0 border-0 bg-transparent p-0"
              title={hasError ? 'Content quality unavailable' : 'No qualified patterns yet'}
              description={
                hasError
                  ? 'Refresh to retry the content pattern read.'
                  : 'Performance patterns appear here once each group has enough live-backed reach.'
              }
            />
            <div className="grid w-full gap-3">
              {[0.78, 0.58, 0.42, 0.32].map((width, i) => (
                <div key={width}>
                  <div className="flex items-center justify-between gap-2.5">
                    <div className="flex flex-1 items-center gap-2">
                      <span
                        aria-hidden="true"
                        className={cn(
                          "size-2 rounded-sm opacity-50",
                          PILLAR_COLORS[i % PILLAR_COLORS.length],
                        )}
                      />
                      <Skeleton className="h-2.5" style={{ width: `${Math.max(32, width * 64)}%` }} />
                    </div>
                    <Skeleton className="h-2.5 w-[34px]" />
                  </div>
                  <Skeleton className="mt-1.5 h-2" style={{ width: `${width * 100}%` }} />
                </div>
              ))}
            </div>
          </NovaInset>
        )}
    </NovaCard>
  );
}
