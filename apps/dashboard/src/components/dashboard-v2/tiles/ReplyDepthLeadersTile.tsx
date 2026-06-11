import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useReplyDepthLeaders } from '@/hooks/useReplyDepthLeaders';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { NovaCard, NovaEmpty } from "@/components/ui/NovaPrimitives";
import { Skeleton } from '@/components/ui/Skeleton';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/ToggleGroup';
import { calendarPostPath } from '@/lib/deepLinks';
import { scopedRoute } from '@/lib/scopedRoutes';
import { Avatar } from '../atoms/Avatar';
import { RangeChip, rangeToDays, usePersistedRange } from '../atoms/RangeChip';
import type { DashboardScopeProps } from '../scope';

/**
 * Reply-depth leaders — Threads Band 2, col-1-8 row-4-7.
 * Spec §5 Widget #8 (P0, GREENFIELD). Top 3 conversation trees by
 * reply_depth × replies. Mini tree glyph per row.
 */
function MiniTree({ depth, replies }: { depth: number; replies: number }) {
  // Stylized radial tree — ~12-20 nodes scaled by depth/replies.
  const nodes = Math.min(20, Math.max(4, replies / 5));
  const l1 = Math.min(6, Math.max(3, Math.round(nodes * 0.5)));
  const l2 = Math.max(1, depth - 1);
  return (
    <svg viewBox="0 0 60 40" width={60} height={40} aria-hidden="true" role="presentation">
      <circle cx={30} cy={20} r={3} fill="var(--color-oxblood)" />
      {Array.from({ length: l1 }).map((_, i) => {
        const a = (i / l1) * Math.PI * 2;
        const x = 30 + Math.cos(a) * 12;
        const y = 20 + Math.sin(a) * 12;
        return (
          <g key={i}>
            <line x1={30} y1={20} x2={x} y2={y} stroke="var(--color-border)" strokeWidth={0.6} />
            <circle cx={x} cy={y} r={1.6} fill="var(--color-oxblood)" />
            {Array.from({ length: l2 }).map((_, j) => {
              const a2 = a + (j - l2 / 2) * 0.25;
              const x2 = x + Math.cos(a2) * 6;
              const y2 = y + Math.sin(a2) * 6;
              return (
                <circle key={j} cx={x2} cy={y2} r={0.9} fill="var(--color-muted-foreground)" opacity={0.6} />
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}

interface AccountLeader {
  accountId: string;
  accountUsername: string | null;
  accountAvatarUrl: string | null;
  bestPostId: string;
  bestPublishedAt: string | null;
  bestContent: string | null;
  maxDepth: number;
  totalReplies: number;
  postsInWindow: number;
  depthSum: number;
  score: number;
}

type ReplySortMode = 'avg' | 'best' | 'total';
const REPLY_SORT_OPTIONS: readonly [ReplySortMode, string][] = [
  ['avg', 'Avg thread depth'],
  ['best', 'Best thread depth'],
  ['total', 'Total replies'],
];

export function ReplyDepthLeadersTile({ scopedAccount, accountIds, groupId }: DashboardScopeProps) {
  const [range, setRange] = usePersistedRange('dv2.replyDepthLeaders.range.v2', '30d');
  const [sortMode, setSortMode] = useState<ReplySortMode>('avg');
  const { leaders, isLoading, hasError } = useReplyDepthLeaders(rangeToDays(range), scopedAccount, accountIds, groupId);

  // Aggregate posts → accounts. Take max(replyDepth) + sum(replies) per account.
  // Mockup #10 ranks ACCOUNTS by their best thread, not posts directly.
  const accountRows: AccountLeader[] = useMemo(() => {
    const byAccount = new Map<string, AccountLeader>();
    for (const p of leaders) {
      if (!p.accountId) continue;
      const existing = byAccount.get(p.accountId);
      if (!existing) {
        byAccount.set(p.accountId, {
          accountId: p.accountId,
          accountUsername: p.accountUsername ?? null,
          accountAvatarUrl: p.accountAvatarUrl ?? null,
          bestPostId: p.id,
          bestPublishedAt: p.publishedAt,
          bestContent: p.content,
          maxDepth: p.replyDepth,
          totalReplies: p.replies,
          postsInWindow: 1,
          depthSum: p.replyDepth,
          score: p.score,
        });
      } else {
        existing.totalReplies += p.replies;
        existing.postsInWindow += 1;
        existing.depthSum += p.replyDepth;
        if (!existing.accountUsername && p.accountUsername) {
          existing.accountUsername = p.accountUsername;
        }
        if (!existing.accountAvatarUrl && p.accountAvatarUrl) {
          existing.accountAvatarUrl = p.accountAvatarUrl;
        }
        if (p.replyDepth > existing.maxDepth || (p.replyDepth === existing.maxDepth && p.score > existing.score)) {
          existing.maxDepth = p.replyDepth;
          existing.bestPostId = p.id;
          existing.bestPublishedAt = p.publishedAt;
          existing.bestContent = p.content;
          existing.score = p.score;
        }
      }
    }
    return Array.from(byAccount.values())
      .sort((a, b) => {
        if (sortMode === 'avg') {
          const avgA = a.depthSum / Math.max(1, a.postsInWindow);
          const avgB = b.depthSum / Math.max(1, b.postsInWindow);
          if (avgB !== avgA) return avgB - avgA;
        } else if (sortMode === 'total') {
          if (b.totalReplies !== a.totalReplies) return b.totalReplies - a.totalReplies;
        } else if (b.maxDepth !== a.maxDepth) return b.maxDepth - a.maxDepth;
        return b.totalReplies - a.totalReplies;
      })
      .slice(0, 6);
  }, [leaders, sortMode]);

  return (
    <NovaCard
      eyebrow="Reply-depth leaders"
      title={`Top ${Math.min(6, accountRows.length)} accounts`}
      description={`Ranked by ${sortMode === 'avg' ? 'avg thread depth' : sortMode === 'total' ? 'total replies' : 'best thread depth'}.`}
      action={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <RangeChip value={range} onChange={setRange} ariaLabel="Reply-depth window" />
          <Badge tone="outline">Conversation quality</Badge>
        </div>
      }
      contentClassName="flex h-full flex-col"
    >
        {accountRows.length > 0 ? (
          <>
            <ToggleGroup
              type="single"
              value={sortMode}
              onValueChange={(value) => {
                if (value) setSortMode(value as ReplySortMode);
              }}
              className="mb-2"
            >
              {REPLY_SORT_OPTIONS.map(([mode, label]) => (
                <ToggleGroupItem
                  key={mode}
                  value={mode}
                  sizeVariant="sm"
                >
                  {label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <div className="mb-2 text-[0.6875rem] text-muted-foreground">
              MiniTree: width = total replies · height = max depth.
            </div>
          </>
        ) : null}

        <div
          className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-2"
        >
          {accountRows.length === 0 ? (
            <NovaEmpty
              className="col-span-full"
              title={
                isLoading
                  ? 'Building reply leaderboard'
                  : hasError
                    ? 'Reply-depth leaderboard unavailable'
                    : 'No threads with replies in window'
              }
              description={
                isLoading
                  ? 'Building the account leaderboard from reply-depth sync.'
                  : hasError
                    ? 'Try syncing again in a moment.'
                    : 'Reply depth correlates with Threads ranking lift once conversations start accumulating.'
              }
            >
              <div className="grid w-full gap-x-6 sm:grid-cols-2">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <div
                  key={`empty-${i}`}
                  className="flex min-w-0 items-center gap-3 border-t border-border py-3 opacity-60"
                >
                  <Skeleton className="h-3.5 w-4 shrink-0 rounded" />
                  <Skeleton className="size-7 shrink-0 rounded-full" />
                  <div className="flex-1 min-w-0">
                    <Skeleton className="h-2.5 rounded" style={{ width: `${75 - i * 8}%` }} />
                    <Skeleton className="mt-1 h-1.5 w-2/5 rounded opacity-60" />
                  </div>
                  <svg
                    viewBox="0 0 48 32"
                    width={48}
                    height={32}
                    style={{ flexShrink: 0, opacity: 0.5 }}
                    aria-hidden="true"
                  >
                    <circle cx={24} cy={16} r={2.5} fill="var(--color-muted)" />
                    {[0, 1, 2, 3].map((j) => {
                      const a = (j / 4) * Math.PI * 2;
                      const x = 24 + Math.cos(a) * 9;
                      const y = 16 + Math.sin(a) * 9;
                      return (
                        <g key={j}>
                          <line x1={24} y1={16} x2={x} y2={y} stroke="var(--color-border)" strokeWidth={0.5} strokeDasharray="1 1" />
                          <circle cx={x} cy={y} r={1.3} fill="var(--color-muted)" />
                        </g>
                      );
                    })}
                  </svg>
                </div>
              ))}
              </div>
            </NovaEmpty>
          ) : (
            accountRows.map((r, i) => (
              <Link
                key={r.accountId}
                to={calendarPostPath(r.bestPostId, r.bestPublishedAt)}
                className="group flex min-w-0 items-center gap-3 rounded-lg border border-border bg-muted/35 px-3 py-2.5 text-foreground no-underline transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                title="Open best thread in calendar"
              >
                <Badge tone={i === 0 ? "oxblood" : "outline"} className="w-7 justify-center font-mono tabular-nums">
                  {i + 1}
                </Badge>
                <Avatar seed={r.accountUsername ?? r.accountId} src={r.accountAvatarUrl} size="sm" />
                <div className="flex-1 min-w-0">
                  <div
                    className="truncate text-sm font-medium"
                    title={r.bestContent ?? undefined}
                  >
                    {r.bestContent?.slice(0, 60) ?? 'No caption recorded'}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    Best D{r.maxDepth} · {r.totalReplies.toLocaleString()} replies across {r.postsInWindow} posts
                  </div>
                </div>
                <div style={{ flexShrink: 0 }}>
                  <MiniTree depth={r.maxDepth} replies={r.totalReplies} />
                </div>
              </Link>
            ))
          )}
        </div>

        <Button asChild variant="ghost" size="sm" className="mt-2 shrink-0 justify-start">
          <Link
            to={scopedRoute("/analytics", { scopedAccount, accountIds, groupId, platform: "threads" })}
          >
            Drill to analytics for full trees
          </Link>
        </Button>
    </NovaCard>
  );
}
