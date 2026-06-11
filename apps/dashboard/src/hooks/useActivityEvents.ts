import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { subscribe } from '@/services/realtimeManager';
import { queryClient } from '@/lib/queryClient';
import { queryKeys } from '@/lib/queryKeys';
import { useAuthUser } from '@/hooks/useAuthUser';
import { labelFor } from '@/lib/socialPlatform';

export type ActivityKind = 'publish' | 'error' | 'engagement' | 'ai';
export type ActivityBucket = 'critical' | 'today' | 'yesterday' | 'earlier';
export type ActivityPlatform = 'threads' | 'instagram';

export interface ActivityEvent {
  id: string;
  kind: ActivityKind;
  title: string;
  detail: string;
  account: string | null;
  groupName: string | null;
  groupColor: string | null;
  platform: ActivityPlatform | null;
  ago: string;
  bucket: ActivityBucket;
  sortAt: number;
  action?: { label: string; href?: string | undefined } | undefined;
  meta?: string | undefined;
}

interface State {
  events: ActivityEvent[];
  isLoading: boolean;
  hasError: boolean;
}

const MAX_EVENTS = 80;

function formatAgo(from: Date, now: Date): string {
  const diffMin = Math.max(0, Math.floor((now.getTime() - from.getTime()) / 60000));
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function bucketFor(from: Date, now: Date): ActivityBucket {
  const diffHours = (now.getTime() - from.getTime()) / (60 * 60 * 1000);
  if (diffHours < 24) return 'today';
  if (diffHours < 48) return 'yesterday';
  return 'earlier';
}

type ActivitySource = 'reauth' | 'fail' | 'pub';

interface ActivityRpcRow {
  event_id: string;
  kind: ActivityKind;
  source: ActivitySource;
  username: string | null;
  group_name: string | null;
  group_color: string | null;
  platform: ActivityPlatform | null;
  content: string | null;
  error_message: string | null;
  sort_at: string | null;
}

/**
 * Activity feed via `get_activity_events` RPC. Server joins posts →
 * accounts/instagram_accounts → account_groups + orders by recency;
 * client formats titles/`ago`/buckets (locale + client-clock dependent).
 * 5 queries + JS joins → 1 RPC.
 */
export function useActivityEvents(): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.system.activityEvents(userKey),
    enabled: !!userKey,
    // Realtime channel below invalidates this query on row changes, so a
    // 60s stale window is safe and stops sibling mounts (Layout +
    // ActivityAndActions) from each firing a fresh request.
    staleTime: 60_000,
    gcTime: 10 * 60_000,
    queryFn: async (): Promise<ActivityEvent[]> => {
      const { data, error } = await supabase.rpc('get_activity_events', { p_bucket_limit: 40 });
      if (error) throw error;
      if (!data) return [];
      const rows = data as ActivityRpcRow[];
      const now = new Date();

      const events: ActivityEvent[] = rows.map((row) => {
        const when = row.sort_at ? new Date(row.sort_at) : now;
        const handle = row.username ? `@${row.username}` : null;
        let title: string;
        let detail: string;
        let bucket: ActivityBucket;
        let action: ActivityEvent['action'];

        if (row.source === 'reauth') {
          const platformLabel = row.platform ? `${labelFor(row.platform)} ` : '';
          title = `Token expired · ${handle ?? 'Unnamed account'}`;
          detail = `${platformLabel}token is no longer valid. Reconnect to resume scheduling.`;
          bucket = 'critical';
          action = { label: 'Reconnect', href: '/welcome' };
        } else if (row.source === 'fail') {
          title = `Publish failed${handle ? ` · ${handle}` : ''}`;
          detail = row.error_message || row.content?.slice(0, 120) || 'No error message recorded.';
          const rawBucket = bucketFor(when, now);
          bucket = rawBucket === 'today' ? 'critical' : rawBucket;
          action = { label: 'Retry', href: '/calendar?status=failed' };
        } else {
          title = `Published${handle ? ` · ${handle}` : ''}`;
          detail = row.content?.slice(0, 140) || '(no caption)';
          bucket = bucketFor(when, now);
        }

        return {
          id: row.event_id,
          kind: row.kind,
          title,
          detail,
          account: handle,
          groupName: row.group_name,
          groupColor: row.group_color,
          platform: row.platform,
          ago: formatAgo(when, now),
          bucket,
          sortAt: when.getTime(),
          action,
        };
      });

      const bucketOrder: ActivityBucket[] = ['critical', 'today', 'yesterday', 'earlier'];
      events.sort((a, b) => {
        const bucketDelta = bucketOrder.indexOf(a.bucket) - bucketOrder.indexOf(b.bucket);
        if (bucketDelta !== 0) return bucketDelta;
        return b.sortAt - a.sortAt;
      });

      return events.slice(0, MAX_EVENTS);
    },
  });

  useEffect(() => {
    if (!authUser) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: queryKeys.system.activityEvents(userKey) });
      }, 600);
    };

    const unsubscribe = subscribe(
      `activity-events:${authUser.id}`,
      async (signal) => {
        const { data: { user } } = await supabase.auth.getUser();
        if (signal.aborted || !user) return null;
        return supabase
          .channel(`activity-events:${user.id}`)
          .on('postgres_changes', { event: '*', schema: 'public', table: 'posts', filter: `user_id=eq.${user.id}` }, schedule)
          .on('postgres_changes', { event: '*', schema: 'public', table: 'accounts', filter: `user_id=eq.${user.id}` }, schedule)
          .on('postgres_changes', { event: '*', schema: 'public', table: 'instagram_accounts', filter: `user_id=eq.${user.id}` }, schedule)
          .subscribe();
      },
      schedule,
    );

    return () => {
      if (timer) clearTimeout(timer);
      unsubscribe();
    };
  }, [authUser, userKey]);

  return {
    events: data ?? [],
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
